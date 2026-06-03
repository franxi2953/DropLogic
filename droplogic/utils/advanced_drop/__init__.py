"""
Advanced Drop Module for Enhanced Droplet Manipulation

This module provides the AdvancedDrop class for sophisticated multi-droplet planning
and computer vision-based position validation on DMF chips.

Key Features:
- SIPP-based multi-droplet movement planning with collision avoidance
- Real-time droplet position validation using computer vision
- Vital space enforcement and conflict resolution
- Integration with DropSystem hardware systems
"""
import time
import numpy as np
from .move import move
from .feedback import DropletPositionValidator
from .plan_executor import PlanExecutor
from .common import DropletPlan, DropletList, next_event_id, tag_frame_span, backfill_initial_event, get_droplet_positions, calculate_droplet_center
from .splitting import reservoir_extraction, isometric_split
from .mixing import mix
from .merge import merge
from ..drop_vision.condensate_detector import CondensateDetector
from ..drop_vision.imaging_capture import capture_channel_frame
from typing import Tuple, List, Optional, Set, Union, Dict, Any
import math

__all__ = ['AdvancedDrop']

class AdvancedDrop:
    """
    Advanced Drop functionality container for DropSystems.

    Clean, intuitive API for droplet manipulation with asynchronous execution.

    Key Components:
    - droplets: Smart list with CRUD operations (create, read, update, delete)
    - executor: Asynchronous plan executor for non-blocking execution
    - Planning: SIPP-based multi-droplet path planning
    - Validation: Computer vision-based position verification

    Usage:
        advanced_drop = AdvancedDrop(system)

        # Droplet management
        advanced_drop.droplets.create_droplet(1, (10, 10), (50, 50))
        advanced_drop.droplets.delete_droplet(1)

        # Planning
        plan = advanced_drop.move(mode="sipp")

        # Asynchronous execution
        advanced_drop.executor.start(enable_visualizers=True)
        status = advanced_drop.executor.get_execution_status()
        advanced_drop.executor.stop()
    """

    def __init__(self, system):
        """
        Initialize AdvancedDrop with DropSystem reference.

        Args:
            system: The DropSystem instance (BOXMini, Simulator, etc.)
        """
        self.system = system
        # Ensure the DropSystem references this AdvancedDrop instance so
        # the DropletPositionValidator (which requires access to
        # system_context.advanced_drop) can be constructed during init.
        try:
            # Only set if not already present to avoid overwriting
            if not hasattr(system, 'advanced_drop') or getattr(system, 'advanced_drop') is None:
                system.advanced_drop = self
        except Exception:
            # Best-effort only; ignore if system doesn't allow attribute assignment
            pass

        # ===== INITIALIZATION GROUP =====
        # Initialize validator only if system has required modules (XY stage and camera/microscope)
        has_xy_stage = hasattr(system, 'xy_stage') and system.xy_stage is not None
        has_camera = (hasattr(system, 'camera') and system.camera is not None) or \
                      (hasattr(system, 'microscope') and system.microscope is not None)

        # Initialize visualizer from system if available
        if hasattr(system, 'visualizers') and hasattr(system.visualizers, 'matrix') and system.visualizers.matrix is not None:
            self.visualizer = system.visualizers.matrix
        else:
            self.visualizer = None

        # ===== STATE MANAGEMENT =====
        self.droplets = DropletList(system, self)  # Smart list with management methods
        # Initialize plan with base frame - will be populated by plan_sipp() or reservoir_extraction()

        # Create initial frame using current system matrix state
        try:
            current_matrix = self.matrix  # This calls the matrix property which gets system state
            if current_matrix is not None:
                initial_frame = current_matrix.copy().astype(np.int32)
            else:
                # Matrix is None, use zeros
                initial_frame = np.zeros((128, 128), dtype=np.int32)
                self.system.logger.warning("System matrix is None, using default zero matrix")
        except Exception as e:
            # Fallback to zeros if matrix access fails
            initial_frame = np.zeros((128, 128), dtype=np.int32)
            self.system.logger.warning(f"Failed to access system matrix: {e}, using default zero matrix")

        # Create initial empty frame (all electrodes off)
        initial_frame = np.zeros((128, 128), dtype=np.int32)

        self.plan = DropletPlan(
            frames=[initial_frame],
            frame_count=1,
            droplet_trajectories={},
            active_droplets_per_frame=[[]],  # No droplets initially
            events=[],
            planning_success=True,
            conflicts_resolved=[],
            targets_reached={},
            event_id_per_frame=[]
        )

        # ===== ASYNCHRONOUS EXECUTOR =====
        self.executor = PlanExecutor(system, self)

        # ===== VALIDATOR =====
        if has_xy_stage and has_camera:
            self.validator = DropletPositionValidator(system_context=system, advanced_drop=self)
        else:
            self.validator = None

        # ===== CONDENSATE DETECTOR =====
        if has_camera:
            try:
                self._condensate_detector = CondensateDetector()
                if not self._condensate_detector.is_loaded():
                    self.system.logger.warning("Failed to load condensate detection models")
                    self._condensate_detector = None
            except Exception as e:
                self.system.logger.warning(f"Failed to initialize condensate detector: {e}")
                self._condensate_detector = None
        else:
            self._condensate_detector = None
        
        # ===== EVENT ID COUNTER =====
        self.plan._next_event_id = 1

        # Backfill initial frame with event
        backfill_initial_event(self.plan)


    @property
    def matrix(self):
        """Get the current electrode matrix from the DropSystem."""
        try:
            matrix_data = self.system.state.get("electrode_matrix", {}).get("matrix")
            if matrix_data is not None:
                # Convert to numpy array if it's a list
                if isinstance(matrix_data, list):
                    return np.array(matrix_data)
                return matrix_data
            else:
                raise ValueError("No electrode matrix found in DropSystem state")
        except Exception as e:
            raise ValueError(f"Could not access electrode matrix from DropSystem: {e}")

    def remove_duplicates(self, start_idx: int = 0, end_idx: int = -1) -> None:
        """
        Remove consecutive duplicate frames from the plan within the specified range.
        
        Args:
            start_idx: Starting frame index (inclusive, default 0)
            end_idx: Ending frame index (inclusive, default -1 for last frame)
        """
        if not self.plan or len(self.plan.frames) <= 1:
            return

        # Normalize end_idx
        if end_idx == -1:
            end_idx = len(self.plan.frames) - 1
        elif end_idx >= len(self.plan.frames):
            end_idx = len(self.plan.frames) - 1
        
        # Clamp start_idx
        start_idx = max(0, min(start_idx, len(self.plan.frames) - 1))
        
        if start_idx >= end_idx:
            return

        # Identify indices to keep within the range
        seen = set()
        keep_indices = []
        
        # Always keep frames outside the range
        for i in range(len(self.plan.frames)):
            if i < start_idx or i > end_idx:
                keep_indices.append(i)
            else:
                # Within range, check for duplicates
                frame_tuple = tuple(self.plan.frames[i].flatten())
                if frame_tuple not in seen:
                    seen.add(frame_tuple)
                    keep_indices.append(i)
                # If duplicate, skip it
        
        keep_indices.sort()

        # If no changes, return
        if len(keep_indices) == len(self.plan.frames):
            return

        # Apply the filtering like in _remove_duplicate_frames
        old_to_new = {old_idx: new_idx for new_idx, old_idx in enumerate(keep_indices)}
        
        # Filter frames
        self.plan.frames = [self.plan.frames[i] for i in keep_indices]

        # Filter active_droplets_per_frame
        if self.plan.active_droplets_per_frame:
            self.plan.active_droplets_per_frame = [self.plan.active_droplets_per_frame[i] for i in keep_indices]

        # Filter event_id_per_frame
        if self.plan.event_id_per_frame:
            self.plan.event_id_per_frame = [self.plan.event_id_per_frame[i] for i in keep_indices]

        # Filter trajectories
        for droplet_id, traj in self.plan.droplet_trajectories.items():
            if len(traj) >= len(keep_indices):
                self.plan.droplet_trajectories[droplet_id] = [traj[i] for i in keep_indices]

        # Adjust events: map old frame indices to new ones
        new_events = []
        for frame_idx, etype, data in self.plan.events:
            if frame_idx in old_to_new:
                new_frame_idx = old_to_new[frame_idx]
                new_events.append((new_frame_idx, etype, data))
        self.plan.events = new_events

        # Update frame_count
        self.plan.frame_count = len(self.plan.frames)

        # Adjust executor current_frame if necessary
        if hasattr(self, 'executor') and self.executor:
            with self.executor.execution_lock:
                # Map the old current_frame to the new index, or clamp to last frame
                self.executor.state.current_frame = old_to_new.get(self.executor.state.current_frame, len(keep_indices) - 1)
        """Remove consecutive duplicate frames from a plan, preserving the last frame."""
        if len(self.plan.frames) <= 1:
            return

        # Identify indices to keep (last occurrence of each unique frame)
        # Always preserve the last frame since it represents the final state after the operation
        seen = set()
        keep_indices = []
        for i in range(len(self.plan.frames) - 1, -1, -1):  # iterate backwards
            frame_tuple = tuple(self.plan.frames[i].flatten())
            if frame_tuple not in seen:
                seen.add(frame_tuple)
                keep_indices.append(i)
        keep_indices.sort()  # sort to maintain order

        # things to manage now
        # class DropletPlan:
        #   """Represents a complete plan for droplet manipulation operations on a DMF chip."""
        #   frames: List[np.ndarray]  # List of 2D arrays showing electrode ON/OFF states for each frame
        #   frame_count: int  # Total number of frames in the plan (should equal len(frames))
        #   droplet_trajectories: Dict[int, List[Tuple[int, int]]]  # Maps droplet ID to list of (row,col) positions over time
        #   active_droplets_per_frame: List[List[int]]  # List of lists; each sublist contains droplet IDs active in that frame
        #   events: List[Tuple[int, str, Any]]  # Chronological log of events: (frame_index, event_type, metadata_dict)
        #   planning_success: bool  # True if all droplet targets were successfully reached
        #   conflicts_resolved: List[Dict]  # List of dicts documenting any conflicts that were detected and resolved
        #   targets_reached: Dict[int, bool]  # Maps droplet ID to boolean indicating if its target position was reached
        #   event_id_per_frame: List[Optional[int]] = field(default_factory=list)  # Tags each frame with an event ID (or None)

        # frames need to be filtered by keep_indices
        # frame_count needs to be updated to len(keep_indices)
        # droplet_trajectories need to filter the List[Tuple[int, int]] to only include positions corresponding to kept frames
        # active_droplets_per_frame needs to be filtered by keep_indices
        # events_id_per_frame needs to be filtered by keep_indices
        # events is tricky. event_type and metadata_dict can stay the same, but frame_index needs to be remapped to the new indices. 
        #     To do so, we need to see where each event type appears for the first type in events_id_per_frame, and then remap the frame_index to the new index in keep_indices.
        # planning_success, conflicts_resolved, targets_reached can stay the same since they are overall plan properties, not frame-specific.

        # Filter frames
        self.plan.frames = [self.plan.frames[i] for i in keep_indices]

        # Filter active_droplets_per_frame
        self.plan.active_droplets_per_frame = [self.plan.active_droplets_per_frame[i] for i in keep_indices]

        # Filter event_id_per_frame
        self.plan.event_id_per_frame = [self.plan.event_id_per_frame[i] for i in keep_indices]

        # Filter trajectories
        for traj in self.plan.droplet_trajectories.values():
            traj[:] = [traj[i] for i in keep_indices]

        # Adjust events: map old frame indices to new ones
        old_to_new = {old_idx: new_idx for new_idx, old_idx in enumerate(keep_indices)}
        new_events = []
        for frame_idx, etype, data in self.plan.events:
            new_frame_idx = old_to_new.get(frame_idx, len(keep_indices) - 1)
            # Adjust frame_span if present
            if isinstance(data, dict) and "frame_span" in data:
                a, b = data["frame_span"]
                new_a = old_to_new.get(a, len(keep_indices) - 1)
                new_b = old_to_new.get(b, len(keep_indices) - 1)
                data = dict(data)  # Make a copy
                data["frame_span"] = (new_a, new_b)
            new_events.append((new_frame_idx, etype, data))
        self.plan.events = new_events

        # Update frame_count
        self.plan.frame_count = len(self.plan.frames)

    def move(self, mode="sipp", remove_duplicate_frames: bool = False, merge_on_failure: bool = True, **kwargs):
        """Plan coordinated movement for current droplets using the specified mode."""
        if not self.droplets:
            raise ValueError("No droplets defined. Use create_droplet() first.")

        # Create a matrix with only non-planning droplets marked
        # Start with the last matrix from the plan if available, otherwise current matrix state
        planning_matrix = self.plan.frames[-1].copy() if self.plan and self.plan.frames else self.matrix.copy()

        # Determine which droplets will be planned (those not at their target)
        droplets_to_plan_ids = {d.id for d in self.droplets if d.origin_corner != d.target_corner}
        
        # Save original corners to revert if needed
        original_corners = {d.id: d.origin_corner for d in self.droplets if d.id in droplets_to_plan_ids}

        # Remove the droplets that will be planned from the matrix
        # They'll be handled by SIPP's reservation system instead
        for droplet in self.droplets:
            # print(f"Droplet {droplet.id}: origin={droplet.origin_corner}, target={droplet.target_corner}, droplets_to_plan_ids={droplets_to_plan_ids}")
            if droplet.id in droplets_to_plan_ids:
                # Clear this droplet's electrodes from the matrix
                positions = get_droplet_positions(droplet, droplet.origin_corner)
                for x, y in positions:
                    if 0 <= x < planning_matrix.shape[0] and 0 <= y < planning_matrix.shape[1]:
                        if planning_matrix[x, y] == 1:  # Only clear if it's a droplet (not forbidden)
                            planning_matrix[x, y] = 0

        # Get new plan from core planning function
        new_plan = move(self.droplets, planning_matrix, mode=mode, existing_plan=self.plan, **kwargs)

        if not merge_on_failure and not new_plan.planning_success:
            self.system.logger.warning("Plan failed and merge_on_failure is False. Reverting origin corners.")
            for droplet in self.droplets:
                if droplet.id in original_corners:
                    droplet.origin_corner = original_corners[droplet.id]
            # Return new_plan so caller can inspect failures, but do not assign it to self.plan
            return new_plan

        # Extend the plan with partial results if planning failed for some droplets
        if self.plan and len(self.plan.frames) > 0:
            self.plan = self.extend_plan(self.plan, new_plan, remove_duplicate_frames=remove_duplicate_frames)
            # Update overall planning success
            self.plan.planning_success = self.plan.planning_success and new_plan.planning_success
        else:
            self.plan = new_plan
        #print all droplet final places
        for droplet in self.droplets:
            final_pos = droplet.origin_corner
        return self.plan

    def extend_plan(self, existing_plan: DropletPlan, new_plan: DropletPlan, event_type: str = "extend", event_data: Optional[Dict[str, Any]] = None, remove_duplicate_frames: bool = False) -> DropletPlan:
        """Extend an existing plan with a new plan, ensuring continuity of active droplets and proper event tagging.
        
        Args:
            existing_plan: The base DropletPlan to extend
            new_plan: The new DropletPlan to append
            event_type: Type of event for tagging the new plan frames (default: "extend")
            event_data: Optional metadata dictionary for the event
            remove_duplicate_frames: If True, removes consecutive duplicate frames across the entire combined plan.
                                    WARNING: This can merge the last frame of one event with the first frame of the next event,
                                    potentially losing/merging event boundaries. Use with caution, specially if you want to use 
                                    merge_sequential_events() later on.
        
        Returns:
            A new DropletPlan combining both input plans with proper continuity
        """
        
        if not new_plan.frames:
            return existing_plan

        # Tag the new_plan with event_type if it's not "extend"
        if event_type != "extend":
            # Ensure new_plan has _next_event_id
            if not hasattr(new_plan, '_next_event_id'):
                new_plan._next_event_id = getattr(existing_plan, '_next_event_id', 1)
            # Tag the entire new_plan span
            eid = next_event_id(new_plan)
            tag_frame_span(new_plan, start_idx=0, count=new_plan.frame_count,
                        event_id=eid, event_type=event_type, data=event_data or {})
            
        # for debug log the events and event_id_per_frame of the new plan and the old plan
        # self.system.logger.info(f"[EXTEND_PLAN] Existing plan events: {existing_plan.events}")
        # self.system.logger.info(f"[EXTEND_PLAN] Existing plan event_id_per_frame: {existing_plan.event_id_per_frame}")
        # self.system.logger.info(f"[EXTEND_PLAN] New plan events: {new_plan.events}")
        # self.system.logger.info(f"[EXTEND_PLAN] New plan event_id_per_frame: {new_plan.event_id_per_frame}")
        # self.system.logger.info(f"[EXTEND PLAN] Frames length: existing={len(existing_plan.frames)}, new={len(new_plan.frames)}")
        # self.system.logger.info(f"[EXTEND PLAN] event_id_per_frame length: existing={len(existing_plan.event_id_per_frame)}, new={len(new_plan.event_id_per_frame)}")
        
        # ---------- identify active droplets from existing plan not manipulated in new plan ----------
        # Get active droplets from the last frame of existing plan
        existing_active_droplets = set()
        if existing_plan.active_droplets_per_frame and existing_plan.active_droplets_per_frame[-1]:
            existing_active_droplets = set(existing_plan.active_droplets_per_frame[-1])

        # Debug: log last active droplets of the previous plan
        # self.system.logger.info(f"[EXTEND_PLAN] Last active droplets of previous plan: {sorted(existing_active_droplets)}")

        # Get droplets manipulated in new plan
        new_plan_droplets = set(new_plan.droplet_trajectories.keys())

        # self.system.logger.info(f"[EXTEND_PLAN] New plan: {sorted(new_plan_droplets)}")

        # Find droplets that are active in existing plan but not manipulated in new plan
        kept_active_droplets = existing_active_droplets - new_plan_droplets

        # print("NEW PLAN DROPLETS: ", sorted(new_plan_droplets))

        # self.system.logger.info(f"[EXTEND_PLAN] Keep active droplets: {sorted(kept_active_droplets)}")

        # ---------- combine frames ----------
        combined_frames = existing_plan.frames.copy()
        existing_plan.frame_count = len(existing_plan.frames)
        new_plan.frame_count = len(new_plan.frames)
        combined_frame_count = existing_plan.frame_count + new_plan.frame_count

        # For each new frame, create a copy and ensure kept-active droplets are drawn
        for new_frame in new_plan.frames:
            frame_copy = new_frame.copy()

            # Draw kept-active droplets on the new frame
            for droplet_id in kept_active_droplets:
                # Get the position of this droplet in the current frame
                frame_idx = len(combined_frames) - existing_plan.frame_count
                # For kept droplets, they stay at their last position from existing plan
                if droplet_id in existing_plan.droplet_trajectories and existing_plan.droplet_trajectories[droplet_id]:
                    pos = existing_plan.droplet_trajectories[droplet_id][-1]  # Last position from existing plan
                    # Find the droplet object to get its shape
                    droplet_obj = next((d for d in self.droplets if d.id == droplet_id), None)
                    if droplet_obj:
                        # Draw the droplet shape at its position
                        for rel_x, rel_y in droplet_obj.shape:
                            abs_x, abs_y = pos[0] + rel_x, pos[1] + rel_y
                            if 0 <= abs_x < frame_copy.shape[0] and 0 <= abs_y < frame_copy.shape[1]:
                                frame_copy[abs_x, abs_y] = 1

            combined_frames.append(frame_copy)

        # ---------- combine actives ----------
        combined_active = (existing_plan.active_droplets_per_frame or []) + (new_plan.active_droplets_per_frame or [])

        # Extend active droplets list to include kept-active droplets for new plan frames
        for i in range(len(new_plan.frames)):
            frame_active = combined_active[existing_plan.frame_count + i].copy() if existing_plan.frame_count + i < len(combined_active) else []
            # Add kept-active droplets to each new frame
            frame_active.extend(kept_active_droplets)
            # Remove duplicates while preserving order
            seen = set()
            frame_active = [x for x in frame_active if not (x in seen or seen.add(x))]
            combined_active[existing_plan.frame_count + i] = frame_active

        # Check for electrode conflicts between kept-active droplets and new plan droplets during new frames only
        electrode_conflicts = []
        for frame_idx, frame in enumerate(combined_frames[existing_plan.frame_count:], existing_plan.frame_count):
            # Get electrodes that are newly activated in this frame (not including kept droplets)
            new_frame_electrodes = set(zip(*np.where(frame == 1)))

            # Subtract electrodes that belong to kept-active droplets
            for kept_id in kept_active_droplets:
                if kept_id in existing_plan.droplet_trajectories and existing_plan.droplet_trajectories[kept_id]:
                    pos = existing_plan.droplet_trajectories[kept_id][-1]
                    droplet_obj = next((d for d in self.droplets if d.id == kept_id), None)
                    if droplet_obj:
                        kept_electrodes = {(pos[0] + rel_x, pos[1] + rel_y) for rel_x, rel_y in droplet_obj.shape}
                        new_frame_electrodes -= kept_electrodes

            # Now check if any kept droplets overlap with the remaining new electrodes
            for kept_id in kept_active_droplets:
                if kept_id in existing_plan.droplet_trajectories and existing_plan.droplet_trajectories[kept_id]:
                    pos = existing_plan.droplet_trajectories[kept_id][-1]
                    droplet_obj = next((d for d in self.droplets if d.id == kept_id), None)
                    if droplet_obj:
                        kept_electrodes = {(pos[0] + rel_x, pos[1] + rel_y) for rel_x, rel_y in droplet_obj.shape}
                        # Check for overlap with electrodes activated by new plan (excluding kept droplets)
                        overlap = kept_electrodes & new_frame_electrodes
                        if overlap:
                            # Find which droplets in the new plan are active in this frame
                            active_in_new_plan = set()
                            if frame_idx < len(combined_active):
                                active_in_new_plan = set(combined_active[frame_idx]) - kept_active_droplets

                            electrode_conflicts.append({
                                'frame': frame_idx,
                                'kept_droplet': kept_id,
                                'new_plan_droplets': sorted(list(active_in_new_plan)),
                                'conflicting_electrodes': list(overlap)
                            })

        # Issue warnings for electrode conflicts during new plan execution
        if electrode_conflicts:
            for conflict in electrode_conflicts:
                self.system.logger.warning(
                    f"Electrode conflict during new plan execution in frame {conflict['frame']}: "
                    f"kept-active droplet {conflict['kept_droplet']} shares electrodes "
                    f"with new plan droplets {conflict['new_plan_droplets']} "
                    f"at positions {conflict['conflicting_electrodes']}"
                )

        # ---------- combine trajectories ----------
        # log for debug the legth of the trajectories before combining
        # and the frames count of both plans

        combined_trajectories = {}
        for droplet_id, trajectory in existing_plan.droplet_trajectories.items():
            if trajectory is not None:
                combined_trajectories[droplet_id] = trajectory.copy()
            else:
                # Find the droplet to get origin_corner
                droplet_obj = next((d for d in self.droplets if d.id == droplet_id), None)
                origin_pos = droplet_obj.origin_corner if droplet_obj else (0, 0)
                combined_trajectories[droplet_id] = [origin_pos] * existing_plan.frame_count

        for droplet_id, trajectory in new_plan.droplet_trajectories.items():
            if trajectory is not None:
                if droplet_id in combined_trajectories:
                    combined_trajectories[droplet_id].extend(trajectory[:])
                else:
                    combined_trajectories[droplet_id] = [trajectory[0] if trajectory else (0, 0)] * existing_plan.frame_count + trajectory[:]
            else:
                # If new_plan trajectory is None, extend with previous position or origin
                if droplet_id in combined_trajectories:
                    last_pos = combined_trajectories[droplet_id][-1] if combined_trajectories[droplet_id] else (0, 0)
                    combined_trajectories[droplet_id].extend([last_pos] * new_plan.frame_count)
                else:
                    droplet_obj = next((d for d in self.droplets if d.id == droplet_id), None)
                    origin_pos = droplet_obj.origin_corner if droplet_obj else (0, 0)
                    combined_trajectories[droplet_id] = [origin_pos] * combined_frame_count

        # Extend trajectories for kept-active droplets to cover the entire new plan duration
        for droplet_id in kept_active_droplets:
            if droplet_id in combined_trajectories:
                traj = combined_trajectories[droplet_id]
                last_pos = traj[-1] if traj else (0, 0)
                # Extend trajectory to match combined frame count
                while len(traj) < combined_frame_count:
                    traj.append(last_pos)

        # Add trajectories for droplets not in the combined plan (inactive or new inactive)
        for d in self.droplets:
            if d.id not in combined_trajectories:
                combined_trajectories[d.id] = [d.origin_corner] * combined_frame_count

        # Extend all trajectories to match combined frame count
        for droplet_id in combined_trajectories:
            traj = combined_trajectories[droplet_id]
            while len(traj) < combined_frame_count:
                traj.append(traj[-1] if traj else (0, 0))


        # ---------- combine actives ----------
        # This was already done above, no need to repeat

        # ---------- combine events with ID remap & frame shift ----------
        def _max_eid(plan) -> int:
            m = 0
            for _, _, data in plan.events:
                if isinstance(data, dict):
                    m = max(m, int(data.get("event_id", 0)))
            return m

        existing_max_eid = _max_eid(existing_plan)

        # 2) build remap from new_plan's event_ids -> new unique ids
        new_ids_in_newplan = []
        for _, _, data in new_plan.events:
            if isinstance(data, dict) and "event_id" in data:
                new_ids_in_newplan.append(int(data["event_id"]))
        new_ids_in_newplan = sorted(set(new_ids_in_newplan))

        remap = {}
        next_id = existing_max_eid + 1
        for old in new_ids_in_newplan:
            remap[old] = next_id
            next_id += 1

        # 3) combine event list, shifting frame indices and updating event_id and frame_span
        combined_events = list(existing_plan.events)
        shift = existing_plan.frame_count
        for frame_idx, etype, data in new_plan.events:
            data = dict(data) if isinstance(data, dict) else {}
            old_eid = int(data.get("event_id", 0))
            if old_eid in remap:
                data["event_id"] = remap[old_eid]
            # shift stored frame_span if present
            if "frame_span" in data and isinstance(data["frame_span"], tuple):
                a, b = data["frame_span"]
                data["frame_span"] = (a + shift, b + shift)
            combined_events.append((frame_idx + shift, etype, data))

        # ---------- combine conflicts & targets ----------
        combined_conflicts = (existing_plan.conflicts_resolved or []) + (new_plan.conflicts_resolved or [])
        combined_targets_reached = dict(existing_plan.targets_reached or {})
        combined_targets_reached.update(new_plan.targets_reached or {})

        # ---------- update droplet end positions ----------
        for d in self.droplets:
            if d.id in combined_trajectories and combined_trajectories[d.id]:
                # Find the last non-None position in the trajectory
                traj = combined_trajectories[d.id]
                for pos in reversed(traj):
                    if pos is not None:
                        d.origin_corner = pos
                        break
                else:
                    # If all positions are None, set to None (shouldn't happen normally)
                    d.origin_corner = None

        combined_planning_success = all(combined_targets_reached.values()) if combined_targets_reached else False

        # ---------- build combined plan ----------
        combined_plan = DropletPlan(
            frames=combined_frames,
            frame_count=combined_frame_count,
            droplet_trajectories=combined_trajectories,
            active_droplets_per_frame=combined_active,
            events=combined_events,
            planning_success=combined_planning_success,
            conflicts_resolved=combined_conflicts,
            targets_reached=combined_targets_reached,
            event_id_per_frame=[],
        )

        # ensure a shared counter lives on the plan
        combined_plan._next_event_id = getattr(existing_plan, "_next_event_id", 1)
        if combined_plan._next_event_id <= _max_eid(combined_plan):
            combined_plan._next_event_id = _max_eid(combined_plan) + 1

        # ---------- merge per-frame event IDs ----------
        # prepare length
        total = combined_plan.frame_count
        combined_plan.event_id_per_frame.extend([None] * (total - len(combined_plan.event_id_per_frame)))

        # copy existing per-frame tags
        if hasattr(existing_plan, "event_id_per_frame") and existing_plan.event_id_per_frame:
            combined_plan.event_id_per_frame[:existing_plan.frame_count] = existing_plan.event_id_per_frame[:existing_plan.frame_count]

        # copy new per-frame tags with remap and shift
        if hasattr(new_plan, "event_id_per_frame") and new_plan.event_id_per_frame:
            for i, eid in enumerate(new_plan.event_id_per_frame):
                if eid is None:
                    continue
                remapped = remap.get(int(eid), None)
                combined_plan.event_id_per_frame[shift + i] = remapped
        
        #for debug print events_id_per_frame of the combined plan
        # self.system.logger.info(f"[EXTEND_PLAN] Combined plan event_id_per_frame: {combined_plan.event_id_per_frame}")

        # Remove consecutive duplicate frames
        if remove_duplicate_frames:
            self._remove_duplicate_frames(combined_plan)

        return combined_plan

    # ===== SPLITTING GROUP (Depends on basic planning) =====

    def reservoir_extraction(self, reservoir_droplet_id: int, split_mode: str, steps: Optional[Tuple[int, int]] = None,
                            split_size: Optional[Union[Tuple[int, int], Set[Tuple[int, int]]]] = None, new_droplet_id: Optional[int] = None, halo_size: int = 0, separation_steps: int = 3,
                            # Optional linear sweep parameters (user can pass these directly instead of a LinearConfig)
                            linear_drops_number: Optional[int] = None,
                            linear_offset: Optional[int] = None,
                            linear_cfg: Optional[object] = None,
                            linear_space_per_col: Optional[int] = None,
                            linear_space_per_row: Optional[int] = None,
                            linear_drop_shape: Optional[Union[Tuple[int,int], Set[Tuple[int,int]]]] = None,
                            linear_direction: Optional[Tuple[int,int]] = None,
                            remove_duplicate_frames: bool = False,
                            **kwargs):
        """
        Extract a droplet from a reservoir.

        Args:
            reservoir_droplet_id: ID of the reservoir droplet to extract from
            split_mode: '1to2', '1to3', or 'linear'
            steps: (vertical_offset, horizontal_offset) from reservoir corner to place new droplet.
                    Required for '1to2' and '1to3' modes. Optional (and ignored) for 'linear' mode.
                    First value affects row (vertical): negative = up/north, positive = down/south
                    Second value affects column (horizontal): negative = left/west, positive = right/east
                    Final position = reservoir_corner + steps. Must not overlap with reservoir.

                    Examples:
                    - steps=(-5, 0): Move 5 steps north (up)
                    - steps=(0, 5): Move 5 steps east (right)
                    - steps=(3, -2): Move 3 steps south (down) and 2 steps west (left)
            split_size: Size of the central droplet as (height, width) for 1to3, or shape as set for 1to2.
                        For 1to3: (height, width) of central droplet to extract, centered in reservoir.
                        For 1to2: Set of relative coordinates from reservoir corner.
                        None = use default (1, 1) for 1to3 or {(0, 0)} for 1to2
            new_droplet_id: ID for the new droplet (None = auto-generate next available ID)
            halo_size: Size of unactivated electrode halo around extracted droplet (1to2 only)
            separation_steps: Number of steps for moving droplets to separate from each other (1to3 only)
            linear_drops_number: Number of droplets to create in linear mode
            linear_offset: Starting offset from reservoir corner in linear mode
            linear_cfg: LinearConfig object for linear mode (alternative to individual linear_* params)
            linear_space_per_col: Electrode spacing between columns in linear mode
            linear_space_per_row: Electrode spacing between rows in linear mode
            linear_drop_shape: Shape of droplets in linear mode
            linear_direction: Direction tuple (dr, dc) for linear sweep

        Returns:
            List of IDs of newly created droplets

        Raises:
            ValueError: If reservoir droplet not found, invalid parameters, or final position overlaps reservoir
            NotImplementedError: If extraction protocol not yet implemented
        """
        # Capture original IDs before updating
        original_ids = {d.id for d in self.droplets}

        # Execute the extraction - get new plan
        # Forward any extra keyword args (e.g. linear_* parameters) to the lower-level implementation
        updated_droplets, new_plan = reservoir_extraction(
            self.droplets, self.matrix, reservoir_droplet_id, split_mode, steps,
            split_size, new_droplet_id, halo_size, separation_steps, self.system.logger, self.plan,
            linear_drops_number=linear_drops_number,
            linear_offset=linear_offset,
            linear_cfg=linear_cfg,
            linear_space_per_col=linear_space_per_col,
            linear_space_per_row=linear_space_per_row,
            linear_drop_shape=linear_drop_shape,
            linear_direction=linear_direction,
            **kwargs
        )

        # Extend existing plan if one exists
        if self.plan and len(self.plan.frames) > 0:
            self.plan = self.extend_plan(self.plan, new_plan, remove_duplicate_frames=remove_duplicate_frames)      
        else:
            self.plan = new_plan

        

        # Update internal state - preserve DropletList type
        self.droplets.clear()
        self.droplets.extend(updated_droplets)

       
        # Return IDs of newly created droplets
        new_ids = [d.id for d in updated_droplets if d.id not in original_ids]
        self.system.logger.info(f"Extraction completed: created droplets {new_ids}")

        return new_ids

    def isometric_split(self, droplet_id: int, steps: List[Tuple[int, int]],
                        simultaneous: bool = True, new_droplet_id: Optional[int] = None,
                        event_id: Optional[str] = None, remove_duplicate_frames: bool = False):
        """
        Split a droplet into subdroplets of equal size with sequential symmetric displacement.

        Args:
            droplet_id: ID of the droplet to split
            steps: List of (dx, dy) displacement tuples applied sequentially.
                    Each step splits current droplets and moves them symmetrically.
                    Numbers are automatically converted to positive values for magnitude.
            simultaneous: If True, subdroplets within each step move simultaneously.
                           If False, subdroplets within each step move sequentially.
            new_droplet_id: ID for the first new subdroplet (subsequent IDs auto-generated)
            event_id: Optional custom event identifier (default: "split")

        Returns:
            List of IDs of newly created subdroplets

        Raises:
            ValueError: If droplet not found, invalid steps, or insufficient electrodes

        Example:
            # Split into 4 subdroplets with sequential steps
            new_ids = advanced_drop.isometric_split(
                droplet_id=1,
                steps=[(5, 0), (0, 3)],
                simultaneous=True
            )
            # Step 1: Split 1 droplet into 2 (2 electrodes each), move to (5,0) and (-5,0)
            # Step 2: Split each of those 2 into 2 more (1 electrode each), move (0,3) and (0,-3)
        """

        # Capture original IDs before updating
        original_ids = {d.id for d in self.droplets}

        # Execute the isometric split - get new plan
        updated_droplets, new_plan = isometric_split(
            self.droplets, self.matrix, droplet_id, steps, simultaneous, new_droplet_id, self.system.logger
        )

        # Extend existing plan if one exists
        if self.plan and len(self.plan.frames) > 0:
            self.plan = self.extend_plan(self.plan, new_plan, event_type=event_id or "split", remove_duplicate_frames=remove_duplicate_frames)
        else:
            self.plan = new_plan

        # Update internal state - preserve DropletList type
        self.droplets.clear()
        self.droplets.extend(updated_droplets)

        # Return IDs of newly created subdroplets
        new_ids = [d.id for d in updated_droplets if d.id not in original_ids]

        self.system.logger.info(f"Isometric split completed: created subdroplets {new_ids}")
        return new_ids

    # ===== MIXING GROUP (Depends on basic planning) =====

    def mix(self, droplet_id: int, mode: str = "split_recombine",
            split_area: Optional[Set[Tuple[int, int]]] = None,
            mixing_area_size: Optional[int] = None, cycles: int = 5,
            event_id: Optional[str] = None, remove_duplicate_frames: bool = False):
        """
        Mix a droplet using split-recombine cycles or 2D looped motion.

        Args:
            droplet_id: ID of the droplet to mix
            mode: Mixing mode ("split_recombine" or "2d_loop")
            split_area: Electrode area available for mixing (for symmetry extension in split mode)
            mixing_area_size: Size of mixing area for 2D loop mode (default: 10)
            cycles: Number of mixing cycles
            event_id: Optional custom event identifier (default: "mix")

        Returns:
            List of IDs of any new droplets created during mixing

        Raises:
            ValueError: If droplet not found or invalid parameters
        """

        # Capture original IDs before updating
        original_ids = {d.id for d in self.droplets}

        # Use last frame from existing plan as current matrix state
        current_matrix = (self.plan.frames[-1] if self.plan and self.plan.frames
                         else self.matrix)

        # Execute mixing - get new plan
        # Use a completely clean base matrix for area definition (all electrodes free)
        clean_base_matrix = np.zeros_like(self.matrix)


        updated_droplets, new_plan = mix(
            self.droplets, current_matrix, droplet_id, mode, split_area, mixing_area_size, cycles,
            self.system.logger, self.plan, clean_base_matrix
        )

        # Extend existing plan if one exists
        if self.plan and len(self.plan.frames) > 0:
            self.plan = self.extend_plan(self.plan, new_plan, event_type=event_id or "mix", remove_duplicate_frames=remove_duplicate_frames)
        else:
            self.plan = new_plan

        # Update internal state - preserve DropletList type
        self.droplets.clear()
        self.droplets.extend(updated_droplets)

        # Return IDs of newly created droplets
        new_ids = [d.id for d in updated_droplets if d.id not in original_ids]

        self.system.logger.info(f"Mixing completed: {cycles} cycles, created droplets {new_ids}")
        return new_ids

    # ===== MERGING GROUP (Depends on basic planning) =====

    def merge(self, droplet_ids: Union[int, List[int]], target: Union[int, Tuple[int, int]], 
              forced_width: Optional[int] = None, forced_height: Optional[int] = None,
              hold_final_position: bool = False, event_id: Optional[str] = None, remove_duplicate_frames: bool = False):
        """
        Merge multiple droplets into one at a target location.

        Args:
            droplet_ids: Droplet ID or list of droplet IDs to merge (arbitrarily long)
            target: Either a droplet ID (merge into existing droplet) or
                    a (row, col) position tuple (create new droplet at position)
            forced_width: If specified, the merged droplet shape will have exactly this width (columns)
            forced_height: If specified, the merged droplet shape will have exactly this height (rows)
            hold_final_position: If True, activate the merged footprint in all frames from the start
                                to prevent liquid escape during merge operations
            event_id: Optional custom event identifier (default: "merge")

        Returns:
            ID of the merged droplet (or None if merge could not be completed)

        Raises:
            ValueError: If droplet_ids is empty, contains invalid IDs, or target is invalid
        """

        if isinstance(droplet_ids, int):
            droplet_ids = [droplet_ids]
        if isinstance(target, int) and target in droplet_ids:
            droplet_ids.remove(target)

        if not droplet_ids:
            raise ValueError("droplet_ids cannot be empty")

        # Snapshot pre-merge IDs to identify a newly created droplet
        pre_ids = {d.id for d in self.droplets}

        # Total electrodes from inputs (for diagnostics)
        total_individual_electrodes = 0
        for d in self.droplets:
            if d.id in droplet_ids:
                total_individual_electrodes += len(d.shape)


        # === DEBUG: check active droplets before merge ===
        if hasattr(self.plan, "active_droplets_per_frame") and self.plan.active_droplets_per_frame:
            active_now = set(self.plan.active_droplets_per_frame[-1])
            all_ids = [d.id for d in self.droplets]
            self.system.logger.debug(f"[MERGE DEBUG] Active in last frame: {sorted(active_now)}")
            self.system.logger.debug(f"[MERGE DEBUG] All current droplets: {sorted(all_ids)}")

            inactive = [d for d in droplet_ids if d not in active_now]
            if inactive:
                self.system.logger.warning(
                    f"[MERGE DEBUG] The following droplets are not active in the current plan: {inactive}"
                )
        else:
            self.system.logger.warning("[MERGE DEBUG] No active_droplets_per_frame found in plan.")

        # Remove the droplets that will be planned from the matrix
        # They'll be handled by SIPP's reservation system instead
        planning_matrix = self.plan.frames[-1].copy() if self.plan and self.plan.frames else self.matrix.copy()
        #if the reservoir is part of the merge, we need to free its space as well
        total_droplets = []
        if isinstance(target, int):
            total_droplets = droplet_ids + [target]
        else:
            total_droplets = droplet_ids

        for droplet in self.droplets:
            if droplet.id in total_droplets:
                # Clear this droplet's bounding box from the matrix

                positions = get_droplet_positions(droplet, droplet.origin_corner)
                if positions:
                    # Calculate bounding box
                    x_coords = [x for x, y in positions]
                    y_coords = [y for x, y in positions]
                    min_x, max_x = min(x_coords), max(x_coords)
                    min_y, max_y = min(y_coords), max(y_coords)
                    
                    # Clear the bounding box
                    for x in range(min_x, max_x + 1):
                        for y in range(min_y, max_y + 1):
                            if 0 <= x < planning_matrix.shape[0] and 0 <= y < planning_matrix.shape[1]:
                                if planning_matrix[x, y] == 1:  # Only clear if it's a droplet (not forbidden)
                                    planning_matrix[x, y] = 0
        
        # # Debug: Save matrix to file
        # debug_filename = f"debug_matrix_droplet.txt"
        # np.savetxt(debug_filename, planning_matrix, fmt='%d')
        # # Also save as numpy binary for programmatic access
        # np.save(f"debug_matrix_droplet.npy", planning_matrix)
        
        
        # Execute merge (passes existing plan so routing starts from current end-state)
        updated_droplets, new_plan = merge(
            self.droplets,
            planning_matrix,
            droplet_ids,
            target,
            self.system.logger,
            self.plan,
            forced_width=forced_width,
            forced_height=forced_height,
            hold_final_position=hold_final_position
        )

        # Splice plan
        if self.plan and self.plan.frames:
            self.plan = self.extend_plan(self.plan, new_plan, event_type=event_id or "merge", event_data={"droplet_ids": droplet_ids, "target": target}, remove_duplicate_frames=remove_duplicate_frames)
        else:
            self.plan = new_plan

        # Replace internal droplet list with the updated one (preserve type). 
        # This is needed in case of merge at a target (x,y) where a new droplet is created.
        self.droplets.clear()
        self.droplets.extend(updated_droplets)

        # Determine merged droplet id robustly
        merged_id = None
        merged_droplet = None
        if isinstance(target, int):
            merged_id = target
            merged_droplet = next((d for d in self.droplets if d.id == merged_id), None)
            if merged_droplet is None:
                # Merge may have failed to commit (e.g., not all arrivals); no merged object produced
                self.system.logger.warning(
                    f"Merge into existing droplet {target} did not produce a merged object; returning None"
                )
                return None
        else:
            # Merge-into-new at hub position
            hub = target
            # Prefer a droplet at the hub with an id not in pre-merge set
            candidate = next(
                (d for d in self.droplets if d.origin_corner == hub and d.id not in pre_ids),
                None
            )
            if candidate is None:
                # Fallback: pick the droplet not in pre_ids with the largest electrode_count/shape
                new_only = [d for d in self.droplets if d.id not in pre_ids]
                if new_only:
                    candidate = max(new_only, key=lambda d: getattr(d, "electrode_count", len(d.shape)))
            if candidate is None:
                self.system.logger.warning(
                    "Merge did not create a new droplet at the requested hub; returning None"
                )
                return None
            merged_droplet = candidate
            merged_id = candidate.id


        self.system.logger.debug(f"Merge completed: merged droplets {droplet_ids} into droplet {merged_id}")
        return merged_id

    # ===== VALIDATION GROUP (Independent - uses computer vision) =====

    def verify_droplets(self, frame_idx, droplet_ids=None, save_frames_path=None, debug=False):
        """
        Verify current droplet positions for the stored plan using computer vision or debug mode.

        Args:
            frame_idx (int): Index of the frame in the plan to verify droplet positions for.
            droplet_ids (list or None): List of droplet IDs to verify. If None, verifies all droplets in the plan.
            save_frames_path (str or None): Optional path to save captured or debug frames. If provided, saves images for each droplet.
            debug (bool): If True, runs in debug mode and returns random validation results with mock images.

        Returns:
            tuple:
                - validation_results (dict): Mapping of droplet_id to boolean indicating if the droplet is valid (True) or invalid (False).
                - frame_files (dict): Mapping of droplet_id to the path of the saved frame image (if save_frames_path is provided), otherwise empty dict.

        Raises:
            ValueError: If no plan frames are available or if position validation is not available (missing modules).
        """
        if not self.plan.frames:
            raise ValueError("No plan frames available. Use move() or reservoir_extraction() first.")

        if debug:
            self.system.logger.info(f"[DEBUG] Verifying droplets for frame {frame_idx} with droplet_ids={droplet_ids} in debug mode.")
            # Debug mode: simulate realistic failure rates (50% chance of being wrong) to test protocol recovery logic
            import random
            if droplet_ids is None:
                droplet_ids = list(self.plan.droplet_trajectories.keys())
            
            # Each droplet has chance of being marked as invalid
            validation_results = {did: random.random() < 0.5 for did in droplet_ids}
            frame_files = {}
            
            if save_frames_path:
                import os
                import cv2
                os.makedirs(save_frames_path, exist_ok=True)
                # Create a black image (640x480 default size)
                import numpy as np
                black_image = np.zeros((480, 640, 3), dtype=np.uint8)
                for did in droplet_ids:
                    frame_file = os.path.join(save_frames_path, f"debug_droplet_{did}_frame_{frame_idx}.jpg")
                    cv2.imwrite(frame_file, black_image)
                    frame_files[did] = frame_file
            
            return validation_results, frame_files

        if self.validator is None:
            raise ValueError("Position validation not available - system lacks required modules (XY stage and camera/microscope)")

        # The validator is bound to this AdvancedDrop instance's plan; call it directly.
        # validate_sipp_frame uses the parent advanced_drop.plan internally.
        return self.validator.validate_sipp_frame(frame_idx=frame_idx, droplet_ids=droplet_ids, move_stage=True, save_frames_path=save_frames_path)

    def detect_condensates(self, frame: Optional[np.ndarray] = None,
                          crop_droplet: bool = True,
                          crop_padding: int = 50,
                          confidence_threshold: float = 0.25,
                          return_annotated: bool = False,
                          save_image_path: Optional[str] = None,
                          save_debug_images: bool = False,
                          debug_output_dir: Optional[str] = None,
                          debug_prefix: Optional[str] = None,
                          debug: bool = False,
                          fluo_exposure: int = 2000000,
                          fluo_light: int = 99,
                          brightfield_exposure: int = 3000,
                          brightfield_light: int = 30) -> Tuple[Dict[Tuple[float, float], List], Optional[np.ndarray]]:
        """
        Detect condensates in droplets using computer vision.

        Args:
            frame: Optional pre-captured frame. If None, captures new frame from camera/microscope
            crop_droplet: Whether to crop around droplets before condensate detection
            crop_padding: Padding in pixels around droplet bounding boxes for cropping
            confidence_threshold: Confidence threshold for condensate detection (0.0-1.0)
            return_annotated: Whether to return frame with bounding boxes drawn
            save_image_path: Optional path to save the captured/annotated image
            save_debug_images: If True, save raw + labeled debug images for droplet and condensate detection
            debug_output_dir: Directory to store debug images (defaults to drop_vision/test_images/debug)
            debug_prefix: Optional prefix for debug filenames
            debug: If True, return random mock results instead of using actual detection
            fluo_exposure: Exposure time for fluorescence imaging (microseconds)
            fluo_light: Coaxial light intensity for fluorescence imaging (0-99)
            brightfield_exposure: Exposure time for brightfield imaging (microseconds)
            brightfield_light: Coaxial light intensity for brightfield imaging (0-99)

        Returns:
            Tuple of (condensate_results, annotated_frame)
            condensate_results: Dict[Tuple[float, float], List[Dict]]
                Keys: Normalized droplet center coordinates (x, y) where:
                    - (0.0, 0.0) = image center
                    - (-1.0, 1.0) = top-left corner
                    - (1.0, -1.0) = bottom-right corner
                Values: List of condensate detections for that droplet, each as dict with:
                    'bbox': [x1, y1, x2, y2] coordinates
                    'confidence': float confidence score
                    'class_id': int class identifier
                    'class_name': str human-readable class name
            annotated_frame: Optional[np.ndarray] annotated image if return_annotated=True
        """
        # Debug mode: return random mock results
        if debug:
            import random
            
            # Generate random detections for 4 droplets with random centers
            condensate_results = {}
            for i in range(4):
                # Random normalized center (-1 to 1)
                center_x = random.uniform(-0.8, 0.8)
                center_y = random.uniform(-0.8, 0.8)
                center = (center_x, center_y)
                
                # Random number of detections (0-5)
                num_detections = random.randint(0, 5)
                detections = []
                
                for _ in range(num_detections):
                    # Random bounding box (x1, y1, x2, y2) within reasonable image bounds
                    x1 = random.randint(0, 500)
                    y1 = random.randint(0, 400)
                    x2 = x1 + random.randint(10, 100)
                    y2 = y1 + random.randint(10, 100)
                    
                    detection = {
                        'bbox': [x1, y1, x2, y2],
                        'confidence': random.uniform(0.1, 0.9),
                        'class_id': random.randint(0, 2),  # Assuming 3 classes
                        'class_name': random.choice(['condensate', 'droplet', 'artifact'])
                    }
                    detections.append(detection)
                
                condensate_results[center] = detections
            
            # Create fake annotated frame if requested
            annotated_frame = None
            if return_annotated:
                # Create a black image with random colored rectangles
                import cv2
                fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                for center, detections in condensate_results.items():
                    for detection in detections:
                        x1, y1, x2, y2 = detection['bbox']
                        # Random color
                        color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                        cv2.rectangle(fake_frame, (x1, y1), (x2, y2), color, 2)
                        # Add label
                        label = f"{detection['class_name']}:{detection['confidence']:.2f}"
                        cv2.putText(fake_frame, label, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                annotated_frame = fake_frame
            
            # Save image if requested
            if save_image_path:
                try:
                    import cv2
                    cv2.imwrite(save_image_path, annotated_frame if annotated_frame is not None else np.zeros((480, 640, 3), dtype=np.uint8))
                    self.system.logger.info(f"Saved debug condensate detection image to {save_image_path}")
                except Exception as e:
                    self.system.logger.warning(f"Failed to save debug image to {save_image_path}: {e}")
            
            total_detections = sum(len(dets) for dets in condensate_results.values())
            self.system.logger.info(f"Debug mode: Generated {total_detections} random condensates across {len(condensate_results)} droplets")
            return condensate_results, annotated_frame

        #NORMAL MODE BELOW - actual detection logic (no debug)
        # Check if camera/microscope is available
        has_camera = (hasattr(self.system, 'camera') and self.system.camera is not None) or \
                     (hasattr(self.system, 'microscope') and self.system.microscope is not None)

        if not has_camera:
            raise ValueError("Condensate detection not available - system lacks camera/microscope")

        # Check if detector is available
        if self._condensate_detector is None:
            raise RuntimeError("Condensate detector not available - failed to initialize or load models")

        frame_wait = 0.2

        def _snapshot_capture_settings() -> Dict[str, Any]:
            microscope_settings = self.system.state.get("microscope_settings", {})
            light_settings = self.system.state.get("light_settings", {})
            return {
                "microscope_current_channel": microscope_settings.get("current_channel"),
                "microscope_auto_exposure": microscope_settings.get("auto_exposure"),
                "microscope_exposure_time": microscope_settings.get("exposure_time"),
                "microscope_gain": microscope_settings.get("gain"),
                "light_coaxial_intensity": light_settings.get("coaxial_intensity"),
                "light_ring_intensity": light_settings.get("ring_intensity"),
            }

        def _restore_capture_settings(settings: Dict[str, Any]) -> None:
            try:
                # Restore microscope settings with staged waits between updates
                if settings.get("microscope_current_channel") is not None:
                    self.system.update_state("microscope_settings.current_channel", settings["microscope_current_channel"])
                    time.sleep(frame_wait)

                if settings.get("microscope_auto_exposure") is not None:
                    self.system.update_state("microscope_settings.auto_exposure", settings["microscope_auto_exposure"])
                    time.sleep(frame_wait)

                if settings.get("microscope_exposure_time") is not None:
                    self.system.update_state("microscope_settings.exposure_time", settings["microscope_exposure_time"])
                    time.sleep(frame_wait)

                if settings.get("microscope_gain") is not None:
                    self.system.update_state("microscope_settings.gain", settings["microscope_gain"])
                    time.sleep(frame_wait)

                # Restore light settings with staged waits between updates
                if settings.get("light_coaxial_intensity") is not None:
                    self.system.update_state("light_settings.coaxial_intensity", settings["light_coaxial_intensity"])
                    time.sleep(frame_wait)

                if settings.get("light_ring_intensity") is not None:
                    self.system.update_state("light_settings.ring_intensity", settings["light_ring_intensity"])
                    time.sleep(frame_wait)
            except Exception as restore_error:
                self.system.logger.warning(f"Failed to restore capture settings: {restore_error}")

        # Capture frame if not provided
        original_capture_settings = _snapshot_capture_settings()
        if frame is None:
            try:
                frame = capture_channel_frame(
                    self.system,
                    channel="FAM",
                    exposure_time=fluo_exposure,
                    gain=12,
                    coaxial_intensity=fluo_light,
                    ring_intensity=0,
                    frame_wait=0.2,
                    timeout_per_frame=10.0,
                    mode="fluorescence",
                )
                if frame is None:
                    raise ValueError("No camera or microscope frame available for capture")
            except Exception as e:
                raise RuntimeError(f"Failed to capture frame: {e}")

        if frame is None or frame.size == 0:
            raise ValueError("Captured frame is empty or invalid")

        # Prepare separate droplet image for cropping if needed
        droplet_image = None
        if crop_droplet:
            # Capture brightfield frame for droplet cropping
            try:
                droplet_image = capture_channel_frame(
                    self.system,
                    channel="Brightfield",
                    exposure_time=brightfield_exposure,
                    gain=12,
                    coaxial_intensity=brightfield_light,
                    ring_intensity=0,
                    frame_wait=0.2,
                    timeout_per_frame=10.0,
                    mode="brightfield",
                )
                    
            except Exception as e:
                self.system.logger.warning(f"Failed to capture brightfield frame for cropping: {e}")
                droplet_image = frame  # Fall back to using the fluorescence frame

        # Restore microscope/light settings after all capture operations
        _restore_capture_settings(original_capture_settings)

        # Detect condensates
        detector_returns_annotated = return_annotated or save_debug_images
        detection_result = self._condensate_detector.detect(
            frame=frame,
            droplet_image=droplet_image,
            crop_droplet=crop_droplet,
            crop_padding=crop_padding,
            confidence_threshold=confidence_threshold,
            return_annotated=detector_returns_annotated,
            draw_labels=True
        )

        # Organize results by droplet center
        condensate_results = {}

        all_detections = []
        for i, bbox in enumerate(detection_result.bounding_boxes):
            detection = {
                'bbox': bbox,
                'confidence': detection_result.confidences[i],
                'class_id': detection_result.class_ids[i],
                'class_name': detection_result.class_names[i]
            }
            all_detections.append(detection)

        # Group detections by droplet center
        if hasattr(detection_result, 'droplet_centers') and detection_result.droplet_centers:
            for i, detection in enumerate(all_detections):
                center = detection_result.droplet_centers[i] if i < len(detection_result.droplet_centers) else None
                if center is not None:
                    if center not in condensate_results:
                        condensate_results[center] = []
                    condensate_results[center].append(detection)
                else:
                    # Fallback: assign to 'unassigned' if no valid center
                    if 'unassigned' not in condensate_results:
                        condensate_results['unassigned'] = []
                    condensate_results['unassigned'].append(detection)
        else:
            # Fallback for when centers are not available
            condensate_results['all'] = all_detections

        # Save image if requested
        if save_image_path:
            try:
                import cv2
                cv2.imwrite(save_image_path, detection_result.annotated_frame if return_annotated and detection_result.annotated_frame is not None else frame)
                self.system.logger.info(f"Saved condensate detection image to {save_image_path}")
            except Exception as e:
                self.system.logger.warning(f"Failed to save image to {save_image_path}: {e}")

        if save_debug_images:
            try:
                import os
                import cv2

                if debug_output_dir is None:
                    debug_output_dir = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), '..', 'drop_vision', 'test_images', 'debug')
                    )
                os.makedirs(debug_output_dir, exist_ok=True)

                timestamp = time.strftime("%Y%m%d_%H%M%S")
                tag = debug_prefix or f"detect_{timestamp}_{int(time.time() * 1000) % 1000}"

                # Per-measurement directory layout (simplified)
                measurement_dir = os.path.join(debug_output_dir, tag)
                os.makedirs(measurement_dir, exist_ok=True)

                # Save original (uncropped) source images in measurement root only
                cv2.imwrite(os.path.join(measurement_dir, "fam.png"), frame)
                if droplet_image is not None:
                    cv2.imwrite(os.path.join(measurement_dir, "brightfield.png"), droplet_image)

                # Save brightfield with droplet labels in root
                if crop_droplet and droplet_image is not None and getattr(self._condensate_detector, 'droplet_model', None) is not None:
                    conf_threshold = confidence_threshold if confidence_threshold is not None else self._condensate_detector.confidence_threshold
                    droplet_results = self._condensate_detector.droplet_model.predict(
                        source=droplet_image,
                        conf=conf_threshold,
                        imgsz=self._condensate_detector.image_size,
                        save=False,
                        verbose=False
                    )
                    if droplet_results and len(droplet_results) > 0:
                        droplet_annotated = droplet_results[0].plot()
                        cv2.imwrite(os.path.join(measurement_dir, "brightfield_labeled.png"), droplet_annotated)

                # Save exact per-droplet crop windows passed to condensate model
                crop_entries = getattr(self._condensate_detector, 'last_condensate_crops', []) or []
                if crop_entries:
                    crops_dir = os.path.join(measurement_dir, "crops")
                    os.makedirs(crops_dir, exist_ok=True)

                    for idx, crop_entry in enumerate(crop_entries):
                        droplet_idx = crop_entry.get('droplet_index', idx)
                        droplet_dir = os.path.join(crops_dir, f"droplet_{int(droplet_idx):02d}")
                        os.makedirs(droplet_dir, exist_ok=True)

                        fam_crop = crop_entry.get('fam_crop')
                        brightfield_crop = crop_entry.get('brightfield_crop')
                        crop_bbox = crop_entry.get('crop_bbox')
                        condensate_detections = crop_entry.get('condensate_detections', []) or []

                        if fam_crop is not None:
                            cv2.imwrite(os.path.join(droplet_dir, "fam_crop.png"), fam_crop)
                            fam_labeled = fam_crop.copy()
                            for det in condensate_detections:
                                db = det.get('bbox')
                                if db is None or len(db) < 4:
                                    continue
                                x1, y1, x2, y2 = map(int, db)
                                cv2.rectangle(fam_labeled, (x1, y1), (x2, y2), (0, 255, 0), 1)
                                conf = det.get('confidence', 0.0)
                                label = f"{conf:.2f}"
                                cv2.putText(fam_labeled, label, (x1, max(0, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                            cv2.imwrite(os.path.join(droplet_dir, "fam_crop_labeled.png"), fam_labeled)
                        if brightfield_crop is not None:
                            cv2.imwrite(os.path.join(droplet_dir, "brightfield_crop.png"), brightfield_crop)

                        if crop_bbox is not None and len(crop_bbox) == 4:
                            with open(os.path.join(droplet_dir, "crop_bbox.txt"), "w", encoding="utf-8") as f:
                                f.write(f"x1={crop_bbox[0]}, y1={crop_bbox[1]}, x2={crop_bbox[2]}, y2={crop_bbox[3]}\n")

            except Exception as e:
                self.system.logger.warning(f"Failed to save detection debug images: {e}")

        annotated_frame = detection_result.annotated_frame if return_annotated else None

        self.system.logger.info(f"Detected {len(all_detections)} condensates in frame")
        return condensate_results, annotated_frame

    def correct_droplet_position(self, droplet_id: int, correct_pos: Tuple[int, int]):
        """
        Manually correct the logical position of a droplet in the current plan.
        This appends a new frame where the droplet is removed from its last logical
        position and painted at `correct_pos`. The droplet's internal `origin_corner`
        is also updated. Highly useful when repeating movements due to hardware physical
        failures where droplets fail to reach `target_corner`.

        Args:
            droplet_id: Id of the droplet
            correct_pos: The actual physical (row, col) position
        """
        droplet = self.droplets.get_droplet(droplet_id)
        if not droplet:
            return

        if not self.plan or not self.plan.frames:
            droplet.origin_corner = correct_pos
            return

        last_frame = self.plan.frames[-1].copy()
        
        # 1. Clear ghost pixels from previous logical position
        traj = self.plan.droplet_trajectories.get(droplet_id, [])
        logical_pos = traj[-1] if traj else droplet.origin_corner
        
        # we don't clear using get_droplet_positions since we just want to scrub the old footprint precisely
        ghost_positions = get_droplet_positions(droplet, logical_pos)
        for x, y in ghost_positions:
            if 0 <= x < last_frame.shape[0] and 0 <= y < last_frame.shape[1]:
                last_frame[x, y] = 0
                
        # 2. Draw actual pixels
        real_positions = get_droplet_positions(droplet, correct_pos)
        for x, y in real_positions:
            if 0 <= x < last_frame.shape[0] and 0 <= y < last_frame.shape[1]:
                last_frame[x, y] = 1

        # Push the frame
        self.plan.frames.append(last_frame)
        self.plan.frame_count += 1
        self.plan.active_droplets_per_frame.append(self.plan.active_droplets_per_frame[-1].copy())
        
        # Update trajectories
        for did, dtraj in self.plan.droplet_trajectories.items():
            if did == droplet_id:
                dtraj.append(correct_pos)
            else:
                if dtraj:
                    dtraj.append(dtraj[-1])

        # Update droplet object
        droplet.origin_corner = correct_pos
        
        # Create event
        eid = next_event_id(self.plan)
        self.plan.events.append((len(self.plan.frames) - 1, "correction", {"info": f"Physical correction for {droplet_id}"}))
        if hasattr(self.plan, 'event_id_per_frame'):
            self.plan.event_id_per_frame.append(eid)

    def move_to_droplet_center(self, droplet_id, wait_before_check=0.5, wait_after_check=0.5):
        """
        Move XY stage to the center of a specific droplet and wait for motion to complete.
        
        Args:
            droplet_id: ID of the droplet to move to
            wait_before_check: Time to wait before checking motion complete (seconds)
            wait_after_check: Time to wait after motion complete (seconds)
            
        Returns:
            bool: True if movement completed successfully, False otherwise
        """
        try:
            # Get the droplet
            droplet = self.droplets.get_droplet(droplet_id)
            if droplet is None:
                self.system.logger.error(f"Could not find droplet {droplet_id}")
                return False
                
            # Calculate the center position of the droplet
            stage_coords = calculate_droplet_center(droplet_id, droplet.origin_corner, self.droplets, self.system.logger)
            
            # Move stage to droplet center
            self.system.logger.debug(f"Moving stage to droplet {droplet_id} center: {stage_coords}")
            self.system.update_state("xy_stage.position", stage_coords)
            
            # Wait before checking motion complete
            time.sleep(wait_before_check)
            
            # Wait for motion to complete
            timeout = 30.0  # 30 second timeout
            start_time = time.time()
            while time.time() - start_time < timeout:
                # Check if motion is complete
                motion_complete = self.system.state.get("xy_stage", {}).get("is_motion_complete", True)
                if motion_complete:
                    self.system.logger.debug(f"Stage motion completed for droplet {droplet_id}")
                    break
                time.sleep(0.1)
            else:
                self.system.logger.warning(f"Stage motion timeout after {timeout}s for droplet {droplet_id}")
                return False
            
            # Wait after motion complete
            time.sleep(wait_after_check)
            
            return True
            
        except Exception as e:
            self.system.logger.error(f"Error moving to droplet {droplet_id} center: {e}")
            return False

    # ===== ASYNCHRONOUS EXECUTOR =====
    # Direct access to the PlanExecutor instance
    # Usage: advanced_drop.executor.start_execution(...)
    #        advanced_drop.executor.stop_execution()
    #        advanced_drop.executor.get_execution_status()
    #        etc.

    # ===== UTILITY GROUP =====

    def clear(self):
        """Clear all droplets and reset plan to empty state."""
        self.droplets = DropletList(self.system, self)  # Recreate DropletList
        # Reset plan to empty state instead of None
        self.plan = DropletPlan(
            frames=[],
            frame_count=0,
            droplet_trajectories={},
            active_droplets_per_frame=[],
            events=[],
            planning_success=True,
            conflicts_resolved=[],
            targets_reached={},
            event_id_per_frame=[]
        )
        self.plan._next_event_id = 1

    def get_droplet_position(self, droplet_id: int):
        """
        Get the final position of a droplet according to the current plan.

        Args:
            droplet_id: ID of the droplet

        Returns:
            Final position as (row, col) tuple from the plan trajectory, or None if not found
        """
        # Return the last position from the plan trajectory
        if hasattr(self, 'plan') and self.plan and hasattr(self.plan, 'droplet_trajectories'):
            trajectories = self.plan.droplet_trajectories
            if droplet_id in trajectories and trajectories[droplet_id]:
                return trajectories[droplet_id][-1]  # Last position in trajectory

        return None

    def merge_sequential_events(self, event_id_1: int, event_id_2: int, force: bool = False):
        """
        Merge two sequential events in the plan, handling disappearing droplets.

        Assumes self.plan. Checks if events are sequential (event_id_2 starts right after event_id_1).
        For droplets that disappear during event_id_2, removes them from all frames of event_id_1.
        Then merges the frames simultaneously by overlaying electrode activations.

        Args:
            event_id_1: First event ID
            event_id_2: Second event ID (must be sequential after event_id_1)
            force: If True, override safety checks for conflicting electrode changes

        Returns:
            The event_id of the merged event if successful, None otherwise
        """
        from .merge_events import merge_sequential_events as merge_func
        return merge_func(self, self.plan, event_id_1, event_id_2, self.droplets, self.system.logger, force=force)

    def push_frame(self, event_type: str = "push", event_data: Optional[Dict[str, Any]] = None):
        """
        Push a new frame to the plan based on the current active droplets and their shapes.
        The new frame is created by painting all active droplets at their current positions.
        Trajectories are extended with the current positions.
        Automatically generates an event ID and tags the frame with the specified event type and data.

        Args:
            event_type: Type of event for this frame (default: "push")
            event_data: Optional metadata dictionary for the event
        """
        if not self.plan.frames:
            self.system.logger.warning("No existing frames in plan to push from")
            return

        # Get the last frame and active droplets
        last_frame = self.plan.frames[-1]
        last_active = self.plan.active_droplets_per_frame[-1] if self.plan.active_droplets_per_frame else []

        # Create new frame starting from zeros (or copy last frame and clear droplet positions)
        new_frame = np.zeros_like(last_frame)

        # Paint active droplets
        for droplet_id in last_active:
            droplet = self.droplets.get_droplet(droplet_id)
            if droplet:
                positions = get_droplet_positions(droplet, droplet.origin_corner)
                for x, y in positions:
                    if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                        new_frame[x, y] = 1

        # Append new frame
        self.plan.frames.append(new_frame)
        self.plan.frame_count += 1

        # Extend active_droplets_per_frame
        if self.plan.active_droplets_per_frame is None:
            self.plan.active_droplets_per_frame = []
        self.plan.active_droplets_per_frame.append(last_active.copy())

        # Extend trajectories
        for droplet_id in self.plan.droplet_trajectories:
            traj = self.plan.droplet_trajectories[droplet_id]
            if traj:
                last_pos = traj[-1]
                self.plan.droplet_trajectories[droplet_id].append(last_pos)

        # For droplets not in trajectories but active, add them
        for droplet_id in last_active:
            if droplet_id not in self.plan.droplet_trajectories:
                droplet = self.droplets.get_droplet(droplet_id)
                if droplet:
                    self.plan.droplet_trajectories[droplet_id] = [droplet.origin_corner] * self.plan.frame_count

        # Generate event ID and tag the frame
        eid = next_event_id(self.plan)
        self.plan.events.append((len(self.plan.frames) - 1, event_type, event_data))
        self.plan.event_id_per_frame.append(eid)

    # Add other advanced drop methods here as they are developed
    # def merge_droplets(self, ...): ...
    # etc.