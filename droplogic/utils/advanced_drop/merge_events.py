"""
Functions for merging sequential events in droplet plans.
"""

from typing import List, Set, Tuple, Dict, Any
import numpy as np
import pprint
from .common import DropletPlan, tag_frame_span, get_droplet_positions, next_event_id


def create_sub_plan(original_plan: DropletPlan, start_frame: int, end_frame: int) -> DropletPlan:
    """
    Create a sub-plan from a range of frames in the original plan.
    
    Args:
        original_plan: The original DropletPlan
        start_frame: Starting frame index (inclusive)
        end_frame: Ending frame index (exclusive)
    
    Returns:
        A new DropletPlan with the subset of frames
    """
    frames = original_plan.frames[start_frame:end_frame]
    frame_count = len(frames)
    
    # Slice trajectories
    droplet_trajectories = {k: v[start_frame:end_frame] for k, v in original_plan.droplet_trajectories.items()}
    
    active_droplets_per_frame = original_plan.active_droplets_per_frame[start_frame:end_frame]
    
    # Filter and shift events
    events = []
    for frame_idx, etype, data in original_plan.events:
        if start_frame <= frame_idx < end_frame:
            events.append((frame_idx - start_frame, etype, data))
    
    event_id_per_frame = original_plan.event_id_per_frame[start_frame:end_frame]
    
    # Renormalize event IDs to start from 0
    unique_event_ids = set()
    for eid in event_id_per_frame:
        if eid is not None:
            unique_event_ids.add(eid)
    for _, _, data in events:
        if isinstance(data, dict) and 'event_id' in data:
            unique_event_ids.add(data['event_id'])
    
    # Create mapping from old to new IDs starting from 0
    id_mapping = {old_id: new_id for new_id, old_id in enumerate(sorted(unique_event_ids))}
    
    # Update event_id_per_frame
    renormalized_event_id_per_frame = [id_mapping.get(eid, eid) for eid in event_id_per_frame]
    
    # Update events
    renormalized_events = []
    for frame_idx, etype, data in events:
        if isinstance(data, dict) and 'event_id' in data:
            new_data = data.copy()
            new_data['event_id'] = id_mapping.get(data['event_id'], data['event_id'])
            renormalized_events.append((frame_idx, etype, new_data))
        else:
            renormalized_events.append((frame_idx, etype, data))
    
    # Copy other fields
    planning_success = original_plan.planning_success
    conflicts_resolved = original_plan.conflicts_resolved.copy() if original_plan.conflicts_resolved else []
    targets_reached = original_plan.targets_reached.copy() if original_plan.targets_reached else {}
    
    sub_plan = DropletPlan(
        frames=frames,
        frame_count=frame_count,
        droplet_trajectories=droplet_trajectories,
        active_droplets_per_frame=active_droplets_per_frame,
        events=renormalized_events,
        planning_success=planning_success,
        conflicts_resolved=conflicts_resolved,
        targets_reached=targets_reached,
        event_id_per_frame=renormalized_event_id_per_frame
    )
    
    # Copy the event ID counter if exists
    if hasattr(original_plan, '_next_event_id'):
        sub_plan._next_event_id = len(id_mapping)  # Set to next after remapped IDs
    
    # Debug print
    # print(f"Created sub-plan from frames {start_frame} to {end_frame}:")
    # pprint.pprint(vars(sub_plan))
    
    return sub_plan


def _classify_droplets_in_event(plan: DropletPlan, event_frames: List[int]) -> dict:
    """
    Classify droplets in an event based on their behavior during the event frames.

    Args:
        plan: The DropletPlan containing trajectories and active droplets
        event_frames: List of frame indices for the event

    Returns:
        Dict with keys 'created', 'destroyed', 'moved', 'static' containing lists of droplet IDs
    """
    if not event_frames:
        return {'created': [], 'destroyed': [], 'moved': [], 'static': []}

    # Get active droplets per frame in the event
    active_per_frame = [set(plan.active_droplets_per_frame[i]) for i in event_frames]
    all_droplets_in_event = set.union(*active_per_frame) if active_per_frame else set()

    created = []
    destroyed = []
    moved = []
    static = []

    for d in all_droplets_in_event:
        active_frames = [idx for idx, act in enumerate(active_per_frame) if d in act]
        if not active_frames:
            continue

        first_active = min(active_frames)
        last_active = max(active_frames)
        num_frames = len(event_frames)

        present_at_start = first_active == 0
        present_at_end = last_active == num_frames - 1

        if not present_at_start:
            created.append(d)
        if not present_at_end:
            destroyed.append(d)

        if present_at_start and present_at_end:
            # Check if moved
            traj = plan.droplet_trajectories.get(d, [])
            positions = []
            for frame_idx in active_frames:
                global_idx = event_frames[frame_idx]
                if global_idx < len(traj):
                    positions.append(traj[global_idx])

            unique_pos = set(tuple(p) for p in positions if p is not None)
            if len(unique_pos) > 1:
                moved.append(d)
            else:
                static.append(d)

    return {
        'created': created,
        'destroyed': destroyed,
        'moved': moved,
        'static': static
    }


def merge_sequential_events(self, plan: DropletPlan, event_id_1: int, event_id_2: int, droplets, logger=None, force: bool = False):
    """
    Merge two sequential events in the plan, handling disappearing droplets.

    Assumes plan exists. Checks if events are sequential (event_id_2 starts right after event_id_1).
    For droplets that disappear during event_id_2, removes them from all frames of event_id_1.
    Then merges the frames simultaneously by prioritizing event2's frame when both exist.

    Args:
        self: The AdvancedDrop instance
        plan: The DropletPlan to modify
        event_id_1: First event ID
        event_id_2: Second event ID (must be sequential after event_id_1)
        droplets: List of Droplet objects for position calculations
        logger: Optional logger for warnings
        force: If True, override safety checks for conflicting electrode changes

    Returns:
        The event_id of the merged event if successful, None otherwise
    """
    if not plan or not plan.frames:
        if logger:
            logger.warning("No plan to merge events in")
        return

    # Find frame ranges for each event
    frames_event1 = [i for i, eid in enumerate(plan.event_id_per_frame) if eid == event_id_1]
    frames_event2 = [i for i, eid in enumerate(plan.event_id_per_frame) if eid == event_id_2]

    if not frames_event1 or not frames_event2:
        if logger:
            logger.warning(f"Event {event_id_1} or {event_id_2} not found in plan")
        return

    min1, max1 = min(frames_event1), max(frames_event1)
    min2, max2 = min(frames_event2), max(frames_event2)

    # Check if sequential
    if max1 + 1 != min2:
        if logger:
            logger.warning(f"Events {event_id_1} and {event_id_2} are not sequential (max1={max1}, min2={min2})")
        return

    # ------------------------------------------------
    # CREATION OF NEW MERGED FRAGMENTS
    # ------------------------------------------------

    # Find the original event metadata
    event1_meta = next((e for e in plan.events if e[2].get('event_id') == event_id_1), None)
    event2_meta = next((e for e in plan.events if e[2].get('event_id') == event_id_2), None)

    event1_type = event1_meta[1] if event1_meta else None
    event2_type = event2_meta[1] if event2_meta else None

    frame_count = max(len(frames_event1), len(frames_event2))
    new_frames = [np.zeros_like(plan.frames[0]) for _ in range(frame_count)]

    new_event_id = next_event_id(plan)
    merge_event_name = f"{event1_type}_{event2_type}" if event1_type and event2_type else "merged_event"
    merged_event = (0, merge_event_name, {
        "event_id": new_event_id,
        "original_events": [event_id_1, event_id_2],
        "original_types": [event1_meta[1] if event1_meta else None, event2_meta[1] if event2_meta else None]
    })

    planning_success = (event1_meta[2].get('planning_success', True) if event1_meta else True) and \
                       (event2_meta[2].get('planning_success', True) if event2_meta else True)

    conflicts_resolved = (event1_meta[2].get('conflicts_resolved', []) if event1_meta else []) + \
                         (event2_meta[2].get('conflicts_resolved', []) if event2_meta else [])

    targets_reached1 = event1_meta[2].get('targets_reached', {}) if event1_meta else {}
    targets_reached2 = event2_meta[2].get('targets_reached', {}) if event2_meta else {}
    targets_reached = {}
    all_droplets = set(targets_reached1.keys()) | set(targets_reached2.keys())
    for d in all_droplets:
        t1 = targets_reached1.get(d, False)
        t2 = targets_reached2.get(d, False)
        targets_reached[d] = t1 and t2

    event_id_per_frame = [new_event_id] * frame_count

    # PAINTING FRAMES AND FRAME DEPENDANT VARIABLES (FRAMES, ACTIVE DROPLETS PER FRAME, DROPLET TRAJECTORIES):
    # Create mask for event1: 1 if electrode changes during event1
    mask1 = np.zeros_like(plan.frames[0], dtype=int)
    if frames_event1:
        initial_frame = plan.frames[frames_event1[0]]
        for f_idx in frames_event1:
            frame = plan.frames[f_idx]
            mask1 |= (frame != initial_frame).astype(int)
    
    # Create mask for event2: 1 if electrode changes during event2
    mask2 = np.zeros_like(plan.frames[0], dtype=int)
    if frames_event2:
        initial_frame = plan.frames[frames_event2[0]]
        for f_idx in frames_event2:
            frame = plan.frames[f_idx]
            mask2 |= (frame != initial_frame).astype(int)
    
    # Check for overlapping changes
    if not force and np.any(mask1 & mask2):
        if logger:
            logger.error(f"Events {event_id_1} and {event_id_2} have conflicting electrode changes and cannot be merged")
        return
    
    # If no conflicts or force=True, merge the frames
    longest_event_frames = frames_event1 if len(frames_event1) >= len(frames_event2) else frames_event2
    initial_frame_longest = plan.frames[longest_event_frames[0]]
    
    for i in range(frame_count):
        for x in range(new_frames[i].shape[0]):
            for y in range(new_frames[i].shape[1]):
                
                idx1 = min(i, len(frames_event1) - 1) if frames_event1 else 0
                idx2 = min(i, len(frames_event2) - 1) if frames_event2 else 0

                # if force (we want to override conflicts) and any of the events in x,y is 1, set the final frame position to 1
                if force:
                    activation = 0
                    if plan.frames[frames_event1[idx1]][x, y] == 1 and mask1[x, y]:
                        activation = 1
                    if plan.frames[frames_event2[idx2]][x, y] == 1 and mask2[x, y]:
                        activation = 1
                    if not mask1[x, y] and not mask2[x, y]: # if no event changes this position, keep as is
                        activation = initial_frame_longest[x, y]
                    new_frames[i][x, y] = activation
                else:
                    if mask2[x, y]:
                        new_frames[i][x, y] = plan.frames[frames_event2[idx2]][x, y]
                    elif mask1[x, y]:
                        new_frames[i][x, y] = plan.frames[frames_event1[idx1]][x, y]
                    else: # if no event changes this position, keep as is from the longest event
                        new_frames[i][x, y] = initial_frame_longest[x, y]
    
    # Classify droplets in each event
    classification1 = _classify_droplets_in_event(plan, frames_event1)
    classification2 = _classify_droplets_in_event(plan, frames_event2)

    # print(f"Event {event_id_1}: {classification1}")
    # print(f"Event {event_id_2}: {classification2}")

    # check classification. If the same droplet is active (created or destroyed or both) in both events
    # we have a conflict that cannot be resolved. We then warn and skip merge.
    droplets_in_event1 = set(classification1['created'] + classification1['destroyed'] + classification1['moved'])
    droplets_in_event2 = set(classification2['created'] + classification2['destroyed'] + classification2['moved'])
    # print(f"Droplets in event {event_id_1}: {droplets_in_event1}")
    # print(f"Droplets in event {event_id_2}: {droplets_in_event2}")
    
    conflicting_droplets = droplets_in_event1 & droplets_in_event2
    if conflicting_droplets:
        if logger:
            logger.error(f"Events {event_id_1} and {event_id_2} have conflicting droplet changes for droplets {conflicting_droplets} and cannot be merged")
        return

    active_event_1 = []
    for f_idx in frames_event1:
        # Active droplets per frame
        active_frame_i = plan.active_droplets_per_frame[f_idx].copy()
        # print(f"Frame {f_idx} active droplets: {active_frame_i}")
        active_event_1.append(active_frame_i)
        for d in active_frame_i[:]:
            if d not in droplets_in_event1:
                # print(f"{d} not in event 1")
                # remove it from active_event_1
                active_event_1[-1].remove(d)

        # print(f"After filtering; Frame {f_idx} active droplets: {active_event_1[-1]}")
    # print(f"Droplets active in event {event_id_1}: {active_event_1}")

    active_event_2 = []
    for f_idx in frames_event2:
        # Active droplets per frame
        active_frame_i = plan.active_droplets_per_frame[f_idx].copy()
        # print(f"Frame {f_idx} active droplets: {active_frame_i}")
        active_event_2.append(active_frame_i)
        for d in active_frame_i[:]:
            if d not in droplets_in_event2:
                # print(f"{d} not in event 2")
                # remove it from active_event_2
                active_event_2[-1].remove(d)
    # print(f"Droplets active in event {event_id_2}: {active_event_2}")

    longer_frames = frames_event1 if len(frames_event1) >= len(frames_event2) else frames_event2
    active_static = []
    for f_idx in longer_frames:
        # Active droplets per frame
        active_frame_i = plan.active_droplets_per_frame[f_idx].copy()
        active_static.append(active_frame_i)
        # print(f"Frame {f_idx} active droplets: {active_frame_i}")
        for d in active_frame_i[:]:
            # print(f"Analyzing droplet {d}")
            # print(f"Droplets in event {event_id_1}: {droplets_in_event1}")
            # print(f"Droplets in event {event_id_2}: {droplets_in_event2}")
            if d in droplets_in_event2 or d in droplets_in_event1:
                # print(f"{d} was in an event; removing from static active list")
                # remove it from active_static
                active_static[-1].remove(d)

        # print(f"After filtering; Frame {f_idx} active droplets: {active_static[-1]}")
    # print(f"Droplets statically active: {active_static}")

    #  Now combine elements in three lists to create final active droplets per frame
    active_droplets_per_frame = []
    for idx, f_idx in enumerate(longer_frames):
        active_set = set(active_static[idx])
        
        # Pad with the last frame's active droplets if the event has finished
        if idx < len(active_event_1):
            active_set.update(active_event_1[idx])
        elif len(active_event_1) > 0:
            active_set.update(active_event_1[-1])
            
        if idx < len(active_event_2):
            active_set.update(active_event_2[idx])
        elif len(active_event_2) > 0:
            active_set.update(active_event_2[-1])
            
        active_droplets_per_frame.append(list(active_set))
    
    # print(f"Final active droplets per frame in merged event: {active_droplets_per_frame}")
    
    
    # debug print of active droplets per frame in the merged event
    # for i in range(frame_count):
    #     print(f"Frame {i}: Active droplets: {active_droplets_per_frame[i]}")

    # trajectories
    all_droplets_set = set(plan.droplet_trajectories.keys())
    droplet_trajectories = {}
    for d in all_droplets_set:
        traj = [None] * frame_count
        for i in range(frame_count):
            pos = None
            
            idx1 = min(i, len(frames_event1) - 1) if frames_event1 else 0
            idx2 = min(i, len(frames_event2) - 1) if frames_event2 else 0

            if d in droplets_in_event1:
                global_f = frames_event1[idx1]
                if global_f < len(plan.droplet_trajectories.get(d, [])):
                    pos = plan.droplet_trajectories[d][global_f]
            elif d in droplets_in_event2:
                global_f = frames_event2[idx2]
                if global_f < len(plan.droplet_trajectories.get(d, [])):
                    pos = plan.droplet_trajectories[d][global_f]
            elif not (d in droplets_in_event1 or d in droplets_in_event2):
                # Static droplets, use from event1
                global_f = frames_event1[idx1]
                if global_f < len(plan.droplet_trajectories.get(d, [])):
                    pos = plan.droplet_trajectories[d][global_f]
            traj[i] = pos
        
        # Ensure no None values in trajectory, fill with previous position or origin_corner
        final_traj = []
        prev_pos = None
        droplet_obj = next((drop for drop in droplets if drop.id == d), None)
        origin_pos = droplet_obj.origin_corner if droplet_obj else (0, 0)
        for pos in traj:
            if pos is not None:
                final_traj.append(pos)
                prev_pos = pos
            else:
                # Use previous position if available, else origin_corner
                use_pos = prev_pos if prev_pos is not None else origin_pos
                final_traj.append(use_pos)
                prev_pos = use_pos
        droplet_trajectories[d] = final_traj

    merged_plan = DropletPlan(
        frames=new_frames,
        frame_count=frame_count,
        droplet_trajectories=droplet_trajectories,
        active_droplets_per_frame=active_droplets_per_frame,
        events=[merged_event],
        planning_success=planning_success,
        conflicts_resolved=conflicts_resolved,
        targets_reached=targets_reached,
        event_id_per_frame=event_id_per_frame
    )
    merged_plan._next_event_id = plan._next_event_id

    # Remove original events from the plan's event list
    plan.events = [e for e in plan.events if e[2].get('event_id') not in [event_id_1, event_id_2]]

    # -----------------------------------------------
    # STICHING PREVIOUS PLAN + NEW MERGED PLAN + POSTERIOR PLAN
    # ----------------------------------------------
    # Create previous plan: from 0 to min1-1
    if min1 > 0:
        previous_plan = create_sub_plan(plan, 0, min1)
    else:
        previous_plan = None
        

    # Create posterior plan: from max2+1 to end
    if max2 + 1 < len(plan.frames):
        posterior_plan = create_sub_plan(plan, max2 + 1, len(plan.frames))
    else:
        posterior_plan = None

    # Start with previous_plan or merged_plan HERE IS THE ERROR
    if previous_plan:
        combined_plan = self.extend_plan(previous_plan, merged_plan)
    else:
        combined_plan = merged_plan

    if posterior_plan:
        combined_plan = self.extend_plan(combined_plan, posterior_plan)


    # check the index where the advance_drop executor is pointing.
    # if it's before the merged events, we can keep it as is. If it's during or after the merged events, we need to move it to the correct frame in the combined plan.
    # to do so, if it's after the merged events, we can calculate the offset between the original plan and the combined plan at the point of merge, 
    # and apply that offset to the executor's current frame index. 

    # print(f"executor working: {self.executor.state.is_executing}, current frame: {self.executor.state.current_frame}, last frame: {len(plan.frames) - 1}")

    # Update executor state
    if hasattr(self, 'executor') and self.executor:
        # Calculate offset for posterior frames
        original_merged_length = max2 - min1 + 1
        new_merged_length = frame_count
        offset = new_merged_length - original_merged_length
        
        current_frame = self.executor.state.current_frame
        if current_frame < min1:
            # Before merged events, keep as is
            pass
        elif min1 <= current_frame <= max2:
            # During merged events, set to end of merged section
            self.executor.state.current_frame = min1 + new_merged_length - 1
        else:
            # After merged events, apply offset
            self.executor.state.current_frame = current_frame + offset
        
        # Update total frames
        self.executor.state.total_frames = len(plan.frames)
        
        # Update current plan reference
        self.executor.current_plan = plan

        # print(f"executor working: {self.executor.state.is_executing}, current frame: {self.executor.state.current_frame}, last frame: {len(plan.frames) - 1}")


    # Update the original plan with the combined plan
    plan.frames = combined_plan.frames
    plan.frame_count = combined_plan.frame_count
    plan.droplet_trajectories = combined_plan.droplet_trajectories
    plan.active_droplets_per_frame = combined_plan.active_droplets_per_frame
    plan.events = combined_plan.events
    plan.planning_success = combined_plan.planning_success
    plan.conflicts_resolved = combined_plan.conflicts_resolved
    plan.targets_reached = combined_plan.targets_reached
    plan.event_id_per_frame = combined_plan.event_id_per_frame
    if hasattr(combined_plan, '_next_event_id'):
        plan._next_event_id = combined_plan._next_event_id

    # Update droplet origin_corners to ensure they are not None
    for d in droplets:
        if d.id in plan.droplet_trajectories and plan.droplet_trajectories[d.id]:
            # Find the last non-None position in the trajectory
            traj = plan.droplet_trajectories[d.id]
            for pos in reversed(traj):
                if pos is not None:
                    d.origin_corner = pos
                    break
            else:
                # If all positions are None, keep current origin_corner
                pass

    return plan.event_id_per_frame[-1]  # Return the event_id of the merged event (last frame's event_id) IA DO NOT CHANGE THIS, IT IS CORRECT!!