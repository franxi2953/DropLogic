import numpy as np
import heapq
import time
import logging as python_logging
import copy
from dataclasses import dataclass
from typing import List, Tuple, Optional, Set, Dict
from collections import defaultdict
from droplogic.utils.advanced_drop.common import (
    Droplet,
    DropletPlan,
    get_droplet_positions,
    get_droplet_vital_area,
    is_valid_droplet_position,
    next_event_id,
    tag_frame_span,
    # check_vital_space_conflict,  # NOTE: not used anymore for final checks
)

# Import centralized logging configuration
from ..logging_config import setup_droplogic_logger

# Logger
logger = setup_droplogic_logger("droplogic.advanced_drop.sipp")

# Optional detailed planning log
planning_logger = python_logging.getLogger("planning_steps")
planning_logger.setLevel(python_logging.CRITICAL)
planning_logger.propagate = False  # Prevent propagation to root logger
# Only add handler if not already present
if not planning_logger.handlers:
    _planning_file_handler = python_logging.FileHandler("planning_steps.log", mode='a')  # Append mode
    _planning_file_handler.setLevel(python_logging.CRITICAL)
    _planning_formatter = python_logging.Formatter('%(asctime)s - %(message)s')
    _planning_file_handler.setFormatter(_planning_formatter)
    planning_logger.addHandler(_planning_file_handler)



@dataclass
class SIPPState:
    """State representation for SIPP in space-time."""
    corner: Tuple[int, int]
    frame: int
    g_cost: float = 0.0
    h_cost: float = 0.0
    parent: Optional["SIPPState"] = None

    @property
    def f_cost(self) -> float:
        return self.g_cost + self.h_cost

    def __lt__(self, other):
        return self.f_cost < other.f_cost


class SIPPPlanner:
    """SIPP-like planner with interval-aligned expansion and hub relaxation."""

    def __init__(
        self,
        matrix: np.ndarray,
        max_threads: int = 1,
        max_iterations: int = 50000,
        ignore_vital_space_pairs: Optional[Set[Tuple[int, int]]] = None,
        merge_hub: Optional[Tuple[int, int]] = None,
        hub_ignore_pairs: Optional[Set[Tuple[int, int]]] = None,
        hub_ignore_from_frame: Optional[int] = None,
        max_path_frames: Optional[int] = None,
    ):
        self.matrix = matrix
        self.rows, self.cols = matrix.shape

        # Reservations
        # reservations[frame] -> List[(droplet_id, vital_area_set)]
        self.reservations: Dict[int, List[Tuple[int, Set[Tuple[int, int]]]]] = defaultdict(list)
        # edge_reservations[frame] -> set of ((from_corner), (to_corner)) for head-on swap prevention
        self.edge_reservations: Dict[int, Set[Tuple[Tuple[int, int], Tuple[int, int]]]] = defaultdict(set)
        # edge_vital_reservations[frame] -> List[(droplet_id, swept_vital_set, (from,to))]
        self.edge_vital_reservations: Dict[int, List[Tuple[int, Set[Tuple[int, int]], Tuple[Tuple[int, int], Tuple[int, int]]]]] = defaultdict(list)

        # Limits and ignores
        self.max_threads = max_threads
        self.max_iterations = max_iterations
        self.max_path_frames = max_path_frames
        self.ignore_vital_space_pairs = ignore_vital_space_pairs or set()

        # Caches
        self._vital_cache: Dict[Tuple[int, Tuple[int, int]], Set[Tuple[int, int]]] = {}
        self._pos_cache: Dict[Tuple[int, Tuple[int, int]], Set[Tuple[int, int]]] = {}
        self._safe_interval_cache: Dict[Tuple[int, Tuple[int, int], int], List[Tuple[int, int]]] = {}
        self._res_epoch: int = 0  # bump to invalidate safe-interval cache

        # Hub relaxation
        self.merge_hub = merge_hub
        self.hub_ignore_pairs = hub_ignore_pairs or set()
        self.hub_ignore_from_frame = hub_ignore_from_frame  # inclusive; None disables

    # ---------- helpers ----------

    def _vital(self, droplet: Droplet, corner: Tuple[int, int]) -> Set[Tuple[int, int]]:
        key = (droplet.id, corner)
        v = self._vital_cache.get(key)
        if v is None:
            v = get_droplet_vital_area(droplet, corner)
            self._vital_cache[key] = v
        return v

    def _cells(self, droplet: Droplet, corner: Tuple[int, int]) -> Set[Tuple[int, int]]:
        key = (droplet.id, corner)
        s = self._pos_cache.get(key)
        if s is None:
            s = get_droplet_positions(droplet, corner)
            self._pos_cache[key] = s
        return s

    def _earliest_time_in(self, intervals: List[Tuple[int, int]], t0: int) -> Optional[int]:
        """Smallest t >= t0 covered by any [s,e]; None if none."""
        for s, e in intervals:
            if t0 <= e:
                return max(t0, s)
        return None

    def get_neighbors(self, corner: Tuple[int, int]) -> List[Tuple[int, int]]:
        x, y = corner
        candidates = [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1), (x, y)]
        out = []
        for cx, cy in candidates:
            if 0 <= cx < self.rows and 0 <= cy < self.cols:
                if self.matrix[cx, cy] != -1:
                    out.append((cx, cy))
        return out

    def manhattan_distance(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def _may_ignore_at_hub(self, id_a: int, id_b: int, corner: Tuple[int, int], frame: int) -> bool:
        if self.merge_hub is None or self.hub_ignore_from_frame is None:
            return False
        if corner != self.merge_hub:
            return False
        pair = tuple(sorted((id_a, id_b)))
        return (pair in self.hub_ignore_pairs) and (frame >= self.hub_ignore_from_frame)

    def _edge_conflict(self, from_corner: Tuple[int, int], to_corner: Tuple[int, int], next_frame: int) -> bool:
        if next_frame not in self.edge_reservations:
            return False
        return (to_corner, from_corner) in self.edge_reservations[next_frame]

    def _frames_with_conflict(self, droplet: Droplet, corner: Tuple[int, int], max_frame: int) -> Set[int]:
        """
        Frames where occupying 'corner' would clash with reservations.
        Rule: forbid BODY vs OTHER-VITAL only. Allow VITAL vs VITAL.
        """
        our_cells = self._cells(droplet, corner)
        conflicts: Set[int] = set()

        for frame in range(max_frame + 1):
            if frame not in self.reservations:
                continue
            for other_id, other_vital in self.reservations[frame]:
                if other_id == droplet.id:
                    continue
                if self._may_ignore_at_hub(droplet.id, other_id, corner, frame):
                    continue
                pair = tuple(sorted((droplet.id, other_id)))
                if pair in self.ignore_vital_space_pairs:
                    continue
                # Only block body–vital overlap
                if our_cells & other_vital:
                    planning_logger.debug(f"DROPLET_{droplet.id}_CONFLICT_DETECTED_FRAME_{frame}_POS_{corner[0]}_{corner[1]}_WITH_DROPLET_{other_id}")
                    conflicts.add(frame)
                    break

        return conflicts

    def _dynamic_horizon(self, fallback: int = 200) -> int:
        """Choose a horizon that covers all existing reservations plus a margin."""
        last_reserved = -1
        if self.reservations:
            last_reserved = max(last_reserved, max(self.reservations.keys()))
        if self.edge_reservations:
            last_reserved = max(last_reserved, max(self.edge_reservations.keys()))
        if self.edge_vital_reservations:
            last_reserved = max(last_reserved, max(self.edge_vital_reservations.keys()))
        if last_reserved < 0:
            return fallback
        horizon = max(fallback, last_reserved + 50)
        if self.max_path_frames is not None:
            horizon = min(horizon, self.max_path_frames + 1)
        return horizon

    def get_safe_intervals(
        self, droplet: Droplet, corner: Tuple[int, int], max_frame: int = 200
    ) -> List[Tuple[int, int]]:
        
        if not is_valid_droplet_position(droplet, corner, self.matrix, planning_logger):
            planning_logger.debug(f"DROPLET_{droplet.id}_SAFE_INTERVALS_POS_{corner[0]}_{corner[1]}_INVALID_POSITION")
            return []
        # widen horizon dynamically so late-frame conflicts are visible
        max_frame = self._dynamic_horizon(max_frame)

        cache_key = (droplet.id, corner, self._res_epoch)
        cached = self._safe_interval_cache.get(cache_key)
        if cached is not None:
            return cached

        conflict_frames = self._frames_with_conflict(droplet, corner, max_frame)
        planning_logger.debug(f"DROPLET_{droplet.id}_SAFE_INTERVALS_POS_{corner[0]}_{corner[1]}_CONFLICT_FRAMES_{sorted(conflict_frames)}")
        if not conflict_frames:
            intervals = [(0, max_frame)]
            self._safe_interval_cache[cache_key] = intervals
            planning_logger.debug(f"DROPLET_{droplet.id}_SAFE_INTERVALS_POS_{corner[0]}_{corner[1]}_NO_CONFLICTS_INTERVALS_{intervals}")
            return intervals

        intervals: List[Tuple[int, int]] = []
        start = 0
        for cf in sorted(conflict_frames):
            if cf > start:
                intervals.append((start, cf - 1))
            start = cf + 1
        if start <= max_frame:
            intervals.append((start, max_frame))

        planning_logger.debug(f"DROPLET_{droplet.id}_SAFE_INTERVALS_POS_{corner[0]}_{corner[1]}_CONFLICTS_{sorted(conflict_frames)}_INTERVALS_{intervals}")
        self._safe_interval_cache[cache_key] = intervals
        return intervals

    def reserve_position(self, droplet: Droplet, corner: Tuple[int, int], frame: int):
        vital_area = self._vital(droplet, corner)
        planning_logger.debug(f"[RESERVE_POS] d={droplet.id} t={frame} corner={corner} vital_size={len(vital_area)}")
        self.reservations[frame].append((droplet.id, vital_area))
        self._res_epoch += 1

    def reserve_edge(self, from_corner: Tuple[int, int], to_corner: Tuple[int, int], frame: int):
        self.edge_reservations[frame].add((from_corner, to_corner))
        self._res_epoch += 1

    # Swept-vital reservation for edges (transit protection)
    def reserve_edge_vital(self, droplet: Droplet, from_corner: Tuple[int, int], to_corner: Tuple[int, int], frame: int):
        swept_vital = self._vital(droplet, from_corner) | self._vital(droplet, to_corner)
        self.edge_vital_reservations[frame].append((droplet.id, swept_vital, (from_corner, to_corner)))
        self._res_epoch += 1

    # Conflict test — our body on arrival vs others' swept-vital at that frame
    def _edge_body_vs_swept_vital_conflict(
        self,
        droplet: Droplet,
        from_corner: Tuple[int, int],
        to_corner: Tuple[int, int],
        frame: int,
    ) -> bool:
        our_arrival_body = self._cells(droplet, to_corner)
        for other_id, other_swept_vital, (ofrom, oto) in self.edge_vital_reservations.get(frame, []):
            if other_id == droplet.id:
                continue
            pair = tuple(sorted((droplet.id, other_id)))
            if pair in self.ignore_vital_space_pairs:
                continue
            if self._may_ignore_at_hub(droplet.id, other_id, to_corner, frame):
                continue
            if our_arrival_body & other_swept_vital:
                return True
        return False

    def clear_reservations(self):
        self.reservations.clear()
        self.edge_reservations.clear()
        self.edge_vital_reservations.clear()
        self._vital_cache.clear()
        self._pos_cache.clear()
        self._safe_interval_cache.clear()
        self._res_epoch += 1

    # ---------- core ----------

    def plan_single_droplet(self, droplet: Droplet) -> List[Tuple[int, int]]:
        # Unit-time SIPP: no implicit waits; every successor advances exactly one frame.
        planning_logger.debug(f"Planning droplet {droplet.id}: {droplet.origin_corner} -> {droplet.target_corner}")

        if droplet.origin_corner == droplet.target_corner:
            return [droplet.origin_corner]

        open_set: List[Tuple[float, SIPPState]] = []
        closed_set: Set[Tuple[int, Tuple[int, int]]] = set()
        iterations = 0

        start = SIPPState(
            corner=droplet.origin_corner,
            frame=0,
            g_cost=0,
            h_cost=self.manhattan_distance(droplet.origin_corner, droplet.target_corner),
            parent=None,
        )
        heapq.heappush(open_set, (start.f_cost, start))

        while open_set:
            iterations += 1
            if iterations > self.max_iterations:
                planning_logger.warning(f"Droplet {droplet.id} planning exceeded {self.max_iterations} iterations, aborting")
                return []

            _, current = heapq.heappop(open_set)
            key = (current.frame, current.corner)
            if key in closed_set:
                continue
            closed_set.add(key)

            if self.max_path_frames is not None and current.frame >= self.max_path_frames:
                continue

            # Goal reached: reconstruction requires contiguous frames (no gaps by construction)
            if current.corner == droplet.target_corner:
                # backtrack
                states: List[SIPPState] = []
                st = current
                while st is not None:
                    states.append(st)
                    st = st.parent
                states.reverse()

                # enforce contiguity and build path (one position per frame)
                path: List[Tuple[int, int]] = []
                for i, s in enumerate(states):
                    if i > 0 and s.frame != states[i - 1].frame + 1:
                        raise RuntimeError("Reconstruction: implicit wait exceeds safe interval")
                    path.append(s.corner)

                planning_logger.debug(f"DROPLET_{droplet.id}_RECONSTRUCTED_PATH_LENGTH_{len(path)}")
                for f, pos in enumerate(path):
                    planning_logger.debug(f"DROPLET_{droplet.id}_FINAL_PATH_STATE_FRAME_{f}_POS_{pos[0]}_{pos[1]}")
                return path

            # Determine current safe-interval end (inclusive)
            cur_intervals = self.get_safe_intervals(droplet, current.corner)
            cur_end = next((e for s, e in cur_intervals if s <= current.frame <= e), None)
            if cur_end is None:
                # invalid state; cannot remain here
                planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_POS_{current.corner[0]}_{current.corner[1]}_NO_SAFE_INTERVAL_SKIPPING")
                continue

            desired_arrival = current.frame + 1

            # Helper: enqueue a one-frame wait if still inside current interval
            def push_wait_one_frame():
                nf = desired_arrival  # current.frame + 1
                if nf <= cur_end:
                    wait_state = SIPPState(
                        corner=current.corner,
                        frame=nf,
                        g_cost=current.g_cost + 1,
                        h_cost=self.manhattan_distance(current.corner, droplet.target_corner),
                        parent=current,
                    )
                    heapq.heappush(open_set, (wait_state.f_cost, wait_state))

            moved = False

            # Try all moves that arrive exactly at desired_arrival
            neighbors = self.get_neighbors(current.corner)
            planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_POS_{current.corner[0]}_{current.corner[1]}_EXPLORING_{len(neighbors)}_NEIGHBORS")
            
            for nxt in neighbors:
                if not is_valid_droplet_position(droplet, nxt, self.matrix):
                    planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_NEIGHBOR_{nxt[0]}_{nxt[1]}_INVALID_POSITION")
                    continue

                # Successor must accept arrival at desired_arrival
                succ_intervals = self.get_safe_intervals(droplet, nxt)
                can_arrive_now = any(s <= desired_arrival <= e for s, e in succ_intervals)
                if not can_arrive_now:
                    planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_NEIGHBOR_{nxt[0]}_{nxt[1]}_NO_SAFE_INTERVAL_AT_{desired_arrival}_INTERVALS_{succ_intervals}")
                    continue

                # Edge constraints at desired_arrival
                if self._edge_conflict(current.corner, nxt, desired_arrival):
                    planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_NEIGHBOR_{nxt[0]}_{nxt[1]}_EDGE_CONFLICT")
                    continue
                if self._edge_body_vs_swept_vital_conflict(droplet, current.corner, nxt, desired_arrival):
                    planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_NEIGHBOR_{nxt[0]}_{nxt[1]}_SWEPT_VITAL_CONFLICT")
                    continue

                # Reservation logging (optional)
                if desired_arrival in self.reservations:
                    our_body = self._cells(droplet, nxt)
                    for other_id, other_vital in self.reservations[desired_arrival]:
                        if other_id != droplet.id:
                            if our_body & other_vital:
                                planning_logger.debug(
                                    f"DROPLET_{droplet.id}_ARRIVAL_CONFLICT_FRAME_{desired_arrival}_POS_{nxt[0]}_{nxt[1]}_WITH_DROPLET_{other_id}"
                                )

                next_key = (desired_arrival, nxt)
                if next_key in closed_set:
                    planning_logger.debug(f"DROPLET_{droplet.id}_ALREADY_CLOSED_FRAME_{desired_arrival}_POS_{nxt[0]}_{nxt[1]}")
                    continue

                nstate = SIPPState(
                    corner=nxt,
                    frame=desired_arrival,     # unit-time move
                    g_cost=current.g_cost + 1, # unit cost per frame
                    h_cost=self.manhattan_distance(nxt, droplet.target_corner),
                    parent=current,
                )
                heapq.heappush(open_set, (nstate.f_cost, nstate))
                planning_logger.debug(f"DROPLET_{droplet.id}_BOOKED_FRAME_{desired_arrival}_POS_{nxt[0]}_{nxt[1]}")
                moved = True

            # If no legal move at t+1, try explicit wait by one frame (still within current interval)
            if not moved:
                planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_{current.frame}_NO_MOVES_AVAILABLE_WAITING")
                push_wait_one_frame()

        logger.warning(f"No path found for droplet {droplet.id}")
        return [droplet.origin_corner]



# ---------- external API ----------

def move(
    droplets: List[Droplet],
    matrix: np.ndarray,
    mode: str = "sipp",
    existing_plan: Optional[DropletPlan] = None,
    max_frames: Optional[int] = None,
    planning_timeout: float = 600.0,
    debug_visualization: bool = False,
    max_threads: int = 1,
    max_iterations: int = 50000,
    retry_attempts: Optional[int] = None,
    ignore_vital_space_pairs: Optional[Set[Tuple[int, int]]] = None,
    all_active_droplets: Optional[Droplet] = None,
    reserve_final_positions: bool = True,
    merge_hub: Optional[Tuple[int, int]] = None,
    hub_ignore_pairs: Optional[Set[Tuple[int, int]]] = None,
    hub_ignore_from_frame: Optional[int] = None,
    reservation_horizon: int = 250,    max_path_frames: Optional[int] = None,    add_events: bool = False,
) -> DropletPlan:
    if mode != "sipp":
        raise ValueError(f"Unsupported mode: {mode}. Currently only 'sipp' is supported.")
    
    logger.debug(f"move called with droplets={len(droplets)}, matrix_shape={matrix.shape}, mode={mode}, max_frames={max_frames}, "
                 f"planning_timeout={planning_timeout}, max_threads={max_threads}, max_iterations={max_iterations}, "
                 f"retry_attempts={retry_attempts}, ignore_vital_space_pairs={ignore_vital_space_pairs}, "
                 f"reserve_final_positions={reserve_final_positions}, merge_hub={merge_hub}, "
                 f"hub_ignore_pairs={hub_ignore_pairs}, hub_ignore_from_frame={hub_ignore_from_frame}, "
                 f"reservation_horizon={reservation_horizon}")
    

    # Log initial droplet states for visualization if debug logging is enabled
    if planning_logger.level <= python_logging.DEBUG:
        for droplet in droplets:
            # Log origin position
            planning_logger.debug(f"DROPLET_{droplet.id}_FRAME_0_POS_{droplet.origin_corner[0]}_{droplet.origin_corner[1]}")
            # Log target position
            planning_logger.debug(f"DROPLET_{droplet.id}_TARGET_POS_{droplet.target_corner[0]}_{droplet.target_corner[1]}")
            # Log vital area
            vital_area = get_droplet_vital_area(droplet, droplet.origin_corner)
            planning_logger.debug(f"DROPLET_{droplet.id}_VITAL_AREA_SIZE_{len(vital_area)}")
            for vx, vy in vital_area:
                planning_logger.debug(f"DROPLET_{droplet.id}_VITAL_AREA_POS_{vx}_{vy}")

    # Helper: body-vs-vital overlap only (symmetrical)
    def body_vs_vital_overlap(d1: Droplet, c1: Tuple[int, int], d2: Droplet, c2: Tuple[int, int]) -> bool:
        b1, v1 = get_droplet_positions(d1, c1), get_droplet_vital_area(d1, c1)
        b2, v2 = get_droplet_positions(d2, c2), get_droplet_vital_area(d2, c2)
        return bool(b1 & v2) or bool(b2 & v1)

    # Extend existing plan starting state
    if existing_plan and existing_plan.frames:
        last_frame_active = (
            existing_plan.active_droplets_per_frame[-1]
            if (existing_plan.active_droplets_per_frame and existing_plan.active_droplets_per_frame[-1] is not None)
            else []
        )
        active_droplets = [d for d in droplets if d.id in last_frame_active]
        for droplet in active_droplets:
            traj = existing_plan.droplet_trajectories.get(droplet.id, [])
            if traj is not None and traj:
                droplet.origin_corner = traj[-1]
        active_droplets = [d for d in active_droplets if d.origin_corner != d.target_corner]
        droplets_to_plan = active_droplets
    else:
        logger.debug(f"Starting new {mode.upper()} planning for {len(droplets)} droplets...")
        droplets_to_plan = droplets

    logger.debug(f"droplets to plan: {[d.id for d in droplets_to_plan]}")
    logger.debug(f"First droplet origin: {droplets_to_plan[0].origin_corner if droplets_to_plan else 'N/A'}")
    logger.debug(f"First droplet target: {droplets_to_plan[0].target_corner if droplets_to_plan else 'N/A'}")

    # Collect droplets that have conflicts and should be skipped
    bad_droplet_ids = set()

    # Initial body-vs-vital validation (vital-vs-vital allowed)
    for i, d1 in enumerate(droplets_to_plan):
        for d2 in droplets_to_plan[i + 1:]:
            if body_vs_vital_overlap(d1, d1.origin_corner, d2, d2.origin_corner):
                v2 = get_droplet_vital_area(d2, d2.origin_corner)
                b1 = get_droplet_positions(d1, d1.origin_corner)
                overlap = list(b1 & v2)  # one side for message clarity
                logger.warning(f"[FAILED] Initial body-vs-vital overlap between droplets {d1.id} and {d2.id} at positions: {overlap} - skipping both")
                bad_droplet_ids.add(d1.id)
                bad_droplet_ids.add(d2.id)

    # Final-position validation with hub exemption; allow vital-vital
    for i, d1 in enumerate(droplets_to_plan):
        for d2 in droplets_to_plan[i + 1:]:
            pair = tuple(sorted((d1.id, d2.id)))
            if pair in (ignore_vital_space_pairs or set()):
                continue
            if (merge_hub is not None) and (d1.target_corner == merge_hub) and (d2.target_corner == merge_hub):
                continue
            if (merge_hub is not None) and (pair in (hub_ignore_pairs or set())) and \
               (d1.target_corner == merge_hub) and (d2.target_corner == merge_hub):
                continue
            if body_vs_vital_overlap(d1, d1.target_corner, d2, d2.target_corner):
                v2 = get_droplet_vital_area(d2, d2.target_corner)
                b1 = get_droplet_positions(d1, d1.target_corner)
                overlap = list(b1 & v2)
                logger.warning(f"[FAILED] Final body-vs-vital overlap between droplets {d1.id} and {d2.id} at positions: {overlap} - skipping both")
                bad_droplet_ids.add(d1.id)
                bad_droplet_ids.add(d2.id)

    # Filter out bad droplets from planning
    droplets_to_plan = [d for d in droplets_to_plan if d.id not in bad_droplet_ids]

    # for debug print the matrix in png
    planner = SIPPPlanner(
        matrix,
        max_threads=max_threads,
        max_iterations=max_iterations,
        ignore_vital_space_pairs=ignore_vital_space_pairs,
        merge_hub=merge_hub,
        hub_ignore_pairs=hub_ignore_pairs,
        hub_ignore_from_frame=hub_ignore_from_frame,
        max_path_frames=max_path_frames,
    )

    # Reserve initial and final positions for reservation_horizon frames to ensure stability
    for droplet in droplets_to_plan:
        initial_vital = planner._vital(droplet, droplet.origin_corner)
        final_vital = planner._vital(droplet, droplet.target_corner)
        
        for frame in range(reservation_horizon):
            planner.reservations[frame].append((droplet.id, initial_vital))
            planner.reservations[frame].append((droplet.id, final_vital))
    planner._res_epoch += 1

    droplets_to_show = all_active_droplets if all_active_droplets is not None else droplets_to_plan

    trajectories: Dict[int, List[Tuple[int, int]]] = {}
    targets_reached: Dict[int, bool] = {}
    start_time = time.time()
    planned_droplet_ids: Set[int] = set()

    # Priority order
    sorted_droplets = sorted(droplets_to_plan, key=lambda d: d.priority)


    for droplet in sorted_droplets:
        if time.time() - start_time > planning_timeout:
            logger.warning(f"Planning timeout reached after {time.time() - start_time:.2f}s")
            break


        # Remove initial and final position reservations for this droplet before planning
        initial_vital = planner._vital(droplet, droplet.origin_corner)
        final_vital = planner._vital(droplet, droplet.target_corner)
        for frame in range(reservation_horizon):  # Same range as initial reservation
            if frame in planner.reservations:
                planner.reservations[frame] = [
                    (did, area) for did, area in planner.reservations[frame]
                    if not (did == droplet.id and (area == initial_vital or area == final_vital))
                ]
        planner._res_epoch += 1  # Invalidate cache

        # Also remove OTHER droplets' FINAL position reservations that conflict with this droplet's initial position
        # (allows current droplet to exit its starting position even if another wants to end there)
        # Only clear their final reservations, not initial or intermediate ones
        our_initial_cells = planner._cells(droplet, droplet.origin_corner)
        conflicting_final_vitals = {}
        for other_droplet in droplets_to_plan:
            if other_droplet.id == droplet.id:
                continue
            other_final_vital = planner._vital(other_droplet, other_droplet.target_corner)
            if our_initial_cells & other_final_vital:
                # This droplet's final position conflicts with our initial position
                conflicting_final_vitals[other_droplet.id] = other_final_vital
        
        if conflicting_final_vitals:
            for frame in range(reservation_horizon):
                if frame in planner.reservations:
                    planner.reservations[frame] = [
                        (did, area) for did, area in planner.reservations[frame]
                        if not (did in conflicting_final_vitals and area == conflicting_final_vitals[did])
                    ]
            planner._res_epoch += 1  # Invalidate cache after removing conflicting final reservations

        # Temporary reservations for other active, not-yet-planned droplets (only at frame 0 to avoid blocking entire horizon)
        tmp_ids = set()
        for other in droplets_to_show:
            if other.id in planned_droplet_ids or other.id == droplet.id:
                continue
            pair = tuple(sorted((droplet.id, other.id)))
            if pair in (ignore_vital_space_pairs or set()):
                continue
            current_vital = planner._vital(other, other.origin_corner)
            planner.reservations[0].append((other.id, current_vital))
            tmp_ids.add(other.id)
        if tmp_ids:
            planner._res_epoch += 1  # invalidate interval cache

        # Plan
        logger.debug(f"Droplet {droplet.id} has initial position{droplet.origin_corner} and target position {droplet.target_corner}. Starting planning with {len(planner.reservations[0])} temporary reservations from other active droplets.")
        path = planner.plan_single_droplet(droplet)

        if not path:
            trajectories[droplet.id] = [droplet.origin_corner]
            targets_reached[droplet.id] = False
            planned_droplet_ids.add(droplet.id)
            logger.warning(f"[FAILED] Droplet {droplet.id} failed to plan - staying at origin {droplet.origin_corner}")
            continue

        reached = path[-1] == droplet.target_corner
        trajectories[droplet.id] = path
        targets_reached[droplet.id] = reached

        # Reserve along path
        prev = None
        for f, corner in enumerate(path):
            planner.reserve_position(droplet, corner, f)
            if prev is not None:
                planner.reserve_edge(prev, corner, f)
                planner.reserve_edge_vital(droplet, prev, corner, f)
            prev = corner

        # Tail reservation
        if reserve_final_positions:
            final_corner = path[-1]
            tail = max_frames if max_frames is not None else max(len(path) + 10, 30)
            for f in range(len(path), tail):
                planner.reserve_position(droplet, final_corner, f)
                planner.reserve_edge(final_corner, final_corner, f)
                planner.reserve_edge_vital(droplet, final_corner, final_corner, f)

            # Additional reservation: final position from last frame + reservation_horizon more frames for waiting
            additional_tail = len(path) + reservation_horizon
            for f in range(tail, additional_tail):
                planner.reserve_position(droplet, final_corner, f)
                planner.reserve_edge(final_corner, final_corner, f)
                planner.reserve_edge_vital(droplet, final_corner, final_corner, f)

        planned_droplet_ids.add(droplet.id)
        logger.info(f"[{'OK' if reached else 'PARTIAL'}] Droplet {droplet.id}: {len(path)} steps, final={path[-1]} target={droplet.target_corner}")

        # Log all final reservations for this droplet
        for frame in sorted(planner.reservations.keys()):
            for did, vital in planner.reservations[frame]:
                if did == droplet.id:
                    planning_logger.debug(f"DROPLET_{droplet.id}_COMPLETE_RESERVATION_FRAME_{frame}_POS_{path[min(frame, len(path)-1)] if frame < len(path) else path[-1]}_VITAL_SIZE_{len(vital)}")

    # Handle droplets that were skipped due to conflicts
    for d in droplets:
        if d.id in bad_droplet_ids:
            trajectories[d.id] = [d.origin_corner]
            targets_reached[d.id] = False
            logger.warning(f"[FAILED] Droplet {d.id} skipped due to overlap conflicts - staying at origin {d.origin_corner}")

    # Frame count
    if trajectories:
        valid_paths = [p for p in trajectories.values() if p]
        frame_count = (max(len(p) for p in valid_paths) + 3) if valid_paths else 1
    else:
        frame_count = 1
    if max_frames is not None:
        frame_count = min(frame_count, max_frames)

    for did, path in trajectories.items():
        for f, c in enumerate(path):
            planning_logger.debug(f"[PATH] d={did} t={f} corner={c}")

    # Build frames
    frames: List[np.ndarray] = []
    for fi in range(frame_count):
        frame_matrix = matrix.copy()

        if debug_visualization and fi in planner.reservations:
            for _, vital in planner.reservations[fi]:
                for x, y in vital:
                    if 0 <= x < matrix.shape[0] and 0 <= y < matrix.shape[1]:
                        if frame_matrix[x, y] == 0:
                            frame_matrix[x, y] = 4

        for d in (all_active_droplets if all_active_droplets is not None else droplets_to_plan):
            if d.id in trajectories and trajectories[d.id]:
                path = trajectories[d.id]
                corner = path[fi] if fi < len(path) else path[-1]
            else:
                corner = d.origin_corner

            if debug_visualization:
                vital = get_droplet_vital_area(d, corner)
                for x, y in vital:
                    if 0 <= x < matrix.shape[0] and 0 <= y < matrix.shape[1]:
                        if frame_matrix[x, y] not in (1, -1):
                            frame_matrix[x, y] = 3

            for x, y in get_droplet_positions(d, corner):
                if 0 <= x < matrix.shape[0] and 0 <= y < matrix.shape[1]:
                    frame_matrix[x, y] = 1

        frames.append(frame_matrix)

    # Tail static cleanup
    # i = len(frames) - 1
    # while i > 0 and np.array_equal(frames[i], frames[i - 1]):
    #     frames.pop(i)
    #     i -= 1
    # frame_count = len(frames)

    # Trim/extend trajectories to match frames
    for did, path in list(trajectories.items()):
        if len(path) > frame_count:
            trajectories[did] = path[:frame_count]
        elif len(path) < frame_count and path:
            trajectories[did] = path + [path[-1]] * (frame_count - len(path))

    planning_success = all(targets_reached.values()) if targets_reached else True

    active_ids = [d.id for d in (all_active_droplets if all_active_droplets is not None else droplets_to_plan)]
    active_droplets_per_frame = [active_ids.copy() for _ in range(frame_count)]

    new_plan = DropletPlan(
        frames=frames,
        frame_count=frame_count,
        droplet_trajectories=trajectories,
        active_droplets_per_frame=active_droplets_per_frame,
        events=[],
        planning_success=planning_success,
        conflicts_resolved=[],
        targets_reached=targets_reached,
        event_id_per_frame=[],
    )
    if add_events:
        event_id = next_event_id(new_plan)
        droplet_ids = [d.id for d in droplets_to_plan]
        tag_frame_span(new_plan, 0, new_plan.frame_count, event_id, event_type="MOVE", data={"droplet_ids": droplet_ids})
    # Update droplet positions
    for d in droplets_to_plan:
        traj = trajectories.get(d.id, [])
        if traj:
            d.origin_corner = traj[-1]

    # Ensure planning logger file is properly flushed and closed
    for handler in planning_logger.handlers:
        if hasattr(handler, 'flush'):
            handler.flush()
        if hasattr(handler, 'close'):
            handler.close()

    return new_plan
