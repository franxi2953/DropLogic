"""
Droplet Merge Module (hub-aware, SIPP-routed with travel-point docking)

- Routes ALL merging droplets to a single docking cell ("travel_point") inside
  the final merged footprint that is anchored at the requested target corner.
- Final footprint is a pruned N×N square (closest-to-center kept) sized to the
  exact electrode count; then relaxed via relax_droplet_shape if available.
- Allows overlap ONLY at the docking cell (merge_hub = travel_point) from a
  chosen docking frame onward, including relaxation vs the target droplet when
  merging-into-existing.
- Avoids aliasing: returns a COPY of the droplets list.
"""

from typing import List, Tuple, Optional, Dict, Set, Union
import numpy as np
import json

from .common import (
    Droplet,
    DropletPlan,
    create_droplet,
    get_droplet_positions,
    relax_droplet_shape,
)
from .move import move  # SIPP planner with hub relaxation


# ---------- helpers ----------

def _manhattan(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _validate_corner(matrix: np.ndarray, corner: Tuple[int, int]) -> None:
    r, c = corner
    H, W = matrix.shape
    if not (0 <= r < H and 0 <= c < W):
        raise ValueError(f"Corner out of bounds: {corner}")
    if matrix[r, c] == -1:
        raise ValueError(f"Corner on forbidden cell: {corner}")


def _build_square_pruned_shape(k: int) -> Set[Tuple[int, int]]:
    """
    Build a compact footprint of exactly k cells as a pruned N×N square anchored
    at (0,0) (upper-left corner), then prune farthest-from-center cells.
    Returns a set of relative offsets {(dr, dc)} with 0 <= dr,dc.
    """
    if k <= 0:
        return {(0, 0)}

    n = int(np.ceil(np.sqrt(k)))
    square = {(i, j) for i in range(n) for j in range(n)}
    if len(square) == k:
        return square

    # Prune to exactly k by farthest-from-center first
    to_remove = len(square) - k
    center_r, center_c = n // 2, n // 2
    by_dist = []
    for r, c in square:
        d = abs(r - center_r) + abs(c - center_c)
        by_dist.append((d, r, c))
    by_dist.sort(reverse=True)  # farthest first
    for _ in range(to_remove):
        _, rr, cc = by_dist.pop(0)
        square.remove((rr, cc))

    # Re-anchor to (0, 0)
    if square:
        min_r = min(r for r, c in square)
        min_c = min(c for r, c in square)
        return {(r - min_r, c - min_c) for r, c in square}
        
    return square


def _relax_shape_safe(rel: Set[Tuple[int, int]]) -> Set[Tuple[int, int]]:
    try:
        return relax_droplet_shape(rel)
    except Exception:
        return rel


def _apply_forced_dimensions(
    shape: Set[Tuple[int, int]], 
    total_electrodes: int,
    forced_width: Optional[int] = None,
    forced_height: Optional[int] = None
) -> Set[Tuple[int, int]]:
    """
    Build a rectangular shape with forced dimensions anchored at (0,0).
    Fills from the corner outward, maintaining the forced width/height.
    
    Args:
        shape: Original shape (ignored, rebuilt from scratch)
        total_electrodes: Number of electrodes to place
        forced_width: Fixed width (columns) if specified
        forced_height: Fixed height (rows) if specified
    
    Returns:
        Set of (row, col) offsets forming a rectangle anchored at (0,0)
    """
    if forced_width is not None and forced_height is not None:
        # Both dimensions forced - use them directly
        width, height = forced_width, forced_height
    elif forced_width is not None:
        # Width forced, calculate height
        width = forced_width
        height = int(np.ceil(total_electrodes / width))
    elif forced_height is not None:
        # Height forced, calculate width
        height = forced_height
        width = int(np.ceil(total_electrodes / height))
    else:
        # No forced dimensions, return original shape
        return shape
    
    # Build rectangle from corner (0,0) filling row by row
    result = set()
    count = 0
    for r in range(height):
        for c in range(width):
            if count >= total_electrodes:
                break
            result.add((r, c))
            count += 1
        if count >= total_electrodes:
            break
    
    return result


def _earliest_docking_frame(docking: Tuple[int, int], merging: List[Droplet]) -> int:
    """Lower bound on first arrival (unit-time moves)."""
    if not merging:
        return 0
    return max(_manhattan(d.origin_corner, docking) for d in merging)


def _activate_static_target_in_plan(
    plan: DropletPlan,
    target_id: int,
    target_corner: Tuple[int, int],
    target_shape_rel: Set[Tuple[int, int]],
    matrix_shape: Tuple[int, int],
) -> DropletPlan:
    """Devuelve un plan COPIA con el target añadido como estático en todos los frames actuales."""
    # Copias superficiales
    frames = list(plan.frames)
    active = list(plan.active_droplets_per_frame) if plan.active_droplets_per_frame else [[] for _ in frames]
    trajs = dict(plan.droplet_trajectories or {})
    H, W = matrix_shape

    # Trayectoria estática del target a lo largo de los frames existentes
    static_traj = [target_corner] * len(frames)
    trajs[target_id] = static_traj

    # Pintar el target y marcarlo activo en cada frame
    target_abs = [(target_corner[0] + dr, target_corner[1] + dc) for (dr, dc) in target_shape_rel]
    for i, fr in enumerate(frames):
        fr2 = fr.copy()
        for (x, y) in target_abs:
            if 0 <= x < H and 0 <= y < W:
                fr2[x, y] = 1
        frames[i] = fr2

        if active:
            a = set(active[i]) if i < len(active) else set()
            a.add(target_id)
            if i < len(active):
                active[i] = sorted(a)
            else:
                active.append(sorted(a))

    return DropletPlan(
        frames=frames,
        frame_count=len(frames),
        droplet_trajectories=trajs,
        active_droplets_per_frame=active,
        events=plan.events,
        planning_success=plan.planning_success,
        conflicts_resolved=plan.conflicts_resolved,
        targets_reached=plan.targets_reached,
        event_id_per_frame=[]
    )

# ---------- main ----------

def merge(
    droplets: List[Droplet],
    matrix: np.ndarray,
    droplet_ids: List[int],
    target: Union[int, Tuple[int, int]],
    logger=None,
    existing_plan: Optional[DropletPlan] = None,
    forced_width: Optional[int] = None,
    forced_height: Optional[int] = None,
    hold_final_position: bool = False,
) -> Tuple[List[Droplet], DropletPlan]:

    # logger
    if logger is None:
        from ..logging_config import setup_droplogic_logger
        logger = setup_droplogic_logger("droplogic.advanced_drop.merge")

    if not droplet_ids:
        raise ValueError("droplet_ids cannot be empty")
    
    # Collect droplets to merge
    id_to_d = {d.id: d for d in droplets}
    missing = [i for i in droplet_ids if i not in id_to_d]
    if missing:
        raise ValueError(f"droplet_ids not found: {missing}")
    merging = [id_to_d[i] for i in droplet_ids]

    # Target: droplet id (merge into existing) or (r,c) corner (create new)
    update_existing = False
    target_droplet: Optional[Droplet] = None
    if isinstance(target, int):
        if target not in id_to_d:
            raise ValueError(f"Target droplet id not found: {target}")
        target_droplet = id_to_d[target]
        target_corner = target_droplet.origin_corner
        update_existing = True
    elif isinstance(target, tuple) and len(target) == 2:
        target_corner = target
    else:
        raise ValueError("target must be droplet id (int) or (row,col) tuple")

    _validate_corner(matrix, target_corner)

    # ---- Final footprint & docking (travel_point) ----
    total_electrodes = sum(len(d.shape) for d in merging) + (len(target_droplet.shape) if update_existing else 0)

    # Build pruned N×N relative to target_corner (as upper-left), then relax
    square_rel = _build_square_pruned_shape(total_electrodes)
    
    # Apply forced dimensions if specified
    if forced_width is not None or forced_height is not None:
        square_rel = _apply_forced_dimensions(square_rel, total_electrodes, forced_width, forced_height)
    
    square_rel = _relax_shape_safe(square_rel)

    # Absolute footprint cells
    abs_cells = {(target_corner[0] + dr, target_corner[1] + dc) for (dr, dc) in square_rel}
    # Docking cell (travel_point): prefer target corner if inside footprint
    if target_corner in abs_cells:
        travel_point = target_corner
    else:
        travel_point = min(abs_cells, key=lambda p: (p[0] - target_corner[0]) ** 2 + (p[1] - target_corner[1]) ** 2)

    merged_corner = target_corner  # merged droplet anchored at requested corner
    logger.debug(f"[MERGE DEBUG] total_electrodes={total_electrodes} "
                 f"footprint_size={len(square_rel)} travel_point={travel_point} merged_corner={merged_corner}")

    # ---- Plan motion ----
    # Always use SIPP with hub relaxation at travel_point

    # all joiners aim at travel_point
    for d in merging:
        d.target_corner = travel_point

    # Hub-ignore pairs (among joiners)
    ids = [d.id for d in merging]
    hub_pairs: Set[Tuple[int, int]] = set()
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            hub_pairs.add(tuple(sorted((ids[i], ids[j]))))

    # Ignore vital space pairs for all merging droplets
    ignore_vital_pairs: Set[Tuple[int, int]] = set()
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ignore_vital_pairs.add(tuple(sorted((ids[i], ids[j]))))

    # Docking window
    docking_lb = _earliest_docking_frame(travel_point, merging)

    # For merge-into-existing: ignore vs target at hub, exclude target from temp reservations
    all_active = list(droplets)
    if existing_plan and existing_plan.active_droplets_per_frame:
        active_ids = set(existing_plan.active_droplets_per_frame[-1])
        all_active = [d for d in droplets if d.id in active_ids]

    if update_existing and target_droplet is not None:
        for j in ids:
            hub_pairs.add(tuple(sorted((target_droplet.id, j))))
        # If no existing_plan, exclude target from all_active
        if not existing_plan:
            all_active = [d for d in all_active if d.id != target_droplet.id]


    sipp_plan = move(
        merging,
        matrix,
        mode="sipp",
        existing_plan=existing_plan,
        ignore_vital_space_pairs=ignore_vital_pairs,
        max_frames=300,
        planning_timeout=180.0,
        all_active_droplets=all_active,
        reserve_final_positions=False,
        merge_hub=travel_point,            # relaxation at docking cell
        hub_ignore_pairs=hub_pairs,
        hub_ignore_from_frame=docking_lb,
    )

    # Check arrivals
    arrivals_ok = True
    for d in merging:
        traj = sipp_plan.droplet_trajectories.get(d.id, [])
        last = traj[-1] if traj else None
        logger.debug(f"[MERGE DEBUG] traj end for id={d.id}: {last} (dock={travel_point})")
        if (not traj) or (last != travel_point):
            arrivals_ok = False
            break

    if not arrivals_ok:
        logger.warning("merge: not all droplets reached docking cell; returning motion plan only")
        return list(droplets), sipp_plan

    # if update_existing and target_droplet is not None:
    #     # rehidrata el target en los frames de sipp_plan (no bloqueó la planificación)
    #     sipp_plan = _activate_static_target_in_plan(
    #         plan=sipp_plan,
    #         target_id=target_droplet.id,
    #         target_corner=target_droplet.origin_corner,  # el target no se mueve durante el docking
    #         target_shape_rel=target_droplet.shape,       # su shape actual (la nueva se aplica en consolidación)
    #         matrix_shape=matrix.shape,
    #     )

    # ---- Build final visualization plan (WITHOUT committing merged droplet yet) ----
    frames = list(sipp_plan.frames)
    active_per_frame = (
        list(sipp_plan.active_droplets_per_frame)
        if sipp_plan.active_droplets_per_frame else
        [[d.id for d in droplets]] * len(frames)
    )

    trajs: Dict[int, List[Tuple[int, int]]] = dict(sipp_plan.droplet_trajectories or {})
    frame_count = len(frames)

    # Activate merged footprint from docking frame onward to prevent liquid escape
    for frame_idx in range(max(0, docking_lb), frame_count):
        # Add merged footprint to this frame
        for (dr, dc) in square_rel:
            x, y = merged_corner[0] + dr, merged_corner[1] + dc
            if 0 <= x < frames[frame_idx].shape[0] and 0 <= y < frames[frame_idx].shape[1]:
                frames[frame_idx][x, y] = 1

    # Consolidation frame: paint survivors + merged footprint using local data
    final_frame = np.zeros_like(frames[-1] if frames else matrix)
    merging_ids = set(d.id for d in merging)

    # survivors (non-merging droplets) stay put
    if existing_plan and existing_plan.active_droplets_per_frame:
        last_active = set(existing_plan.active_droplets_per_frame[-1])
        survivors = [d for d in droplets if d.id in last_active and d.id not in merging_ids and (not update_existing or d.id != target_droplet.id)]
    else:
        survivors = [d for d in droplets if d.id not in merging_ids and (not update_existing or d.id != target_droplet.id)]
    for d in survivors:
        for x, y in get_droplet_positions(d, d.origin_corner):
            if 0 <= x < final_frame.shape[0] and 0 <= y < final_frame.shape[1]:
                final_frame[x, y] = 1

    # Paint merged footprint at merged_corner using the local shape (no object yet)
    for (dr, dc) in square_rel:
        x, y = merged_corner[0] + dr, merged_corner[1] + dc
        if 0 <= x < final_frame.shape[0] and 0 <= y < final_frame.shape[1]:
            final_frame[x, y] = 1
    frames.append(final_frame)
    frame_count += 1

    # Active droplets: replace merging ids with future merged_id (compute id but don't create yet)
    existing_ids_now = {d.id for d in droplets}
    merged_id_future = (target_droplet.id if update_existing and target_droplet is not None
                        else (max(existing_ids_now) + 1 if existing_ids_now else 1))

    last_active = set(active_per_frame[-1]) if active_per_frame else set(d.id for d in droplets)
    last_active = {aid for aid in last_active if aid not in merging_ids}
    last_active.add(merged_id_future)
    # print(f"Final active droplets in plan: {last_active}")
    active_per_frame.append(sorted(last_active))

    # Trajectories: extend one frame, merged appears static at merged_corner
    for did, path in list(trajs.items()):
        last = path[-1] if path else id_to_d.get(did, None).origin_corner
        if did not in merging_ids:
            trajs[did] = path + [last]
        else:
            last = path[-1] if path else travel_point
            trajs[did] = path + [last]

    if merged_id_future not in trajs:
        trajs[merged_id_future] = [merged_corner] * frame_count

    # If an existing plan was provided, avoid re-activating droplets that were inactive in that plan.
    # Allowed active ids = droplets that were active in the last frame of existing_plan, plus
    # the merging droplets (they're being moved) and the future merged id (appears in last frame).
    if existing_plan and existing_plan.active_droplets_per_frame:
        original_active_ids = set(existing_plan.active_droplets_per_frame[-1])
        # Ensure reservoir/target stays consistent
        if update_existing and target_droplet is not None:
            original_active_ids.add(target_droplet.id)

        allowed_active_ids = set(original_active_ids) | set(d.id for d in merging) | {merged_id_future}

        # Filter each frame's active list
        for fi in range(len(active_per_frame)):
            active_per_frame[fi] = sorted([aid for aid in active_per_frame[fi] if aid in allowed_active_ids])
        # Also ensure the final appended active frame is filtered (it may have been appended after)
        # (active_per_frame already includes that final frame by this point)

    # ---- NOW create / update the merged droplet object ----
    total_e = total_electrodes
    if update_existing and target_droplet is not None:
        merged_droplet = target_droplet
        merged_droplet.shape = square_rel
        merged_droplet.electrode_count = total_e
        merged_droplet.origin_corner = merged_corner
        logger.debug(
            f"[MERGE DEBUG] updated existing droplet id={merged_droplet.id} at {merged_corner}, size={len(square_rel)}"
        )
        # Keep all droplets in list - merging droplets remain but inactive in plan
    else:
        # Create new droplet at merged_corner
        merged_droplet = create_droplet(merged_id_future, merged_corner, square_rel)
        merged_droplet.electrode_count = total_e
        merged_droplet.shape = square_rel
        merged_droplet.target_corner = merged_corner
        # Add to droplets list
        droplets.append(merged_droplet)
        logger.debug(
            f"[MERGE DEBUG] created new droplet id={merged_id_future} at {merged_corner}, size={len(square_rel)}"
        )
        # Keep all droplets in list - merging droplets remain but inactive in plan

    # Build final DropletPlan
    new_plan = DropletPlan(
        frames=frames,
        frame_count=frame_count,
        droplet_trajectories=trajs,
        active_droplets_per_frame=active_per_frame,
        events=[],
        planning_success=True,
        conflicts_resolved=[],
        targets_reached={did: (trajs.get(did, []) and trajs[did][-2] == travel_point)
                         for did in (d.id for d in merging)},
        event_id_per_frame=[]
    )

    # Commit final origins from trajectories
    for d in droplets:
        t = trajs.get(d.id, [])
        if t:
            d.origin_corner = t[-1]

    # If hold_final_position flag is set, activate merged footprint in all frames to prevent liquid escape
    if hold_final_position:
        logger.debug("hold_final_position=True: Activating merged footprint in all frames")
        merged_footprint_positions = {(merged_corner[0] + dr, merged_corner[1] + dc) for (dr, dc) in square_rel}
        for frame_idx in range(len(frames)):
            for x, y in merged_footprint_positions:
                if 0 <= x < frames[frame_idx].shape[0] and 0 <= y < frames[frame_idx].shape[1]:
                    frames[frame_idx][x, y] = 1

    # print(f"Active droplets final frame: {active_per_frame[-1]}")
    # Debug: save droplets to file
    debug_data = {d.id: {'origin_corner': d.origin_corner, 'shape': list(d.shape), 'electrode_count': d.electrode_count} for d in droplets}
    with open('merge_debug.json', 'w') as f:
        json.dump(debug_data, f, indent=4)
    # Return COPY to avoid aliasing in callers that clear/extend
    return list(droplets), new_plan
