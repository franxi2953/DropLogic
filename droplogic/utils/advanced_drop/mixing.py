"""
Droplet Mixing Module for Advanced Drop Manipulation

This module provides mixing functionality for droplets on DMF chips,
supporting split-recombine cycles and 2D looped motion patterns.
"""

from typing import List, Tuple, Optional, Set, Dict, Any
from .common import Droplet, DropletPlan, create_droplet, get_droplet_positions, relax_droplet_shape
from .splitting import isometric_split
from .move import move
import numpy as np


def mix(droplets: List[Droplet],
        matrix: np.ndarray,  # Last frame from existing plan (current chip state)
        droplet_id: int,
        mode: str = "split_recombine",
        split_area: Optional[Set[Tuple[int, int]]] = None,
        mixing_area_size: Optional[int] = None,
        cycles: int = 5,
        logger=None,
        existing_plan: Optional[DropletPlan] = None,
        base_matrix: Optional[np.ndarray] = None) -> Tuple[List[Droplet], DropletPlan]:
    """
    Mix a droplet using split-recombine cycles or 2D looped motion.

    Args:
        droplets: Current list of droplets
        matrix: Current chip state matrix (last frame from existing plan)
        droplet_id: ID of droplet to mix
        mode: "split_recombine" (default) or "2d_loop"
        split_area: Available electrode area for symmetry extension
        cycles: Number of mixing cycles
        logger: Logger instance
        existing_plan: Existing plan to extend

    Returns:
        Tuple of (updated_droplets, new_droplet_plan)
    """
    if logger is None:
        from ..logging_config import setup_droplogic_logger
        logger = setup_droplogic_logger('droplogic.advanced_drop.mixing')

    logger.info(f"Starting mixing for droplet {droplet_id}: mode={mode}, cycles={cycles}")

    # Store original droplet IDs to avoid adding split-generated subdroplets
    original_droplet_ids = {d.id for d in droplets}

    # Find the target droplet
    target_droplet = None
    for droplet in droplets:
        if droplet.id == droplet_id:
            target_droplet = droplet
            break

    if target_droplet is None:
        raise ValueError(f"Droplet with id {droplet_id} not found")

    # Create a new plan for the mixing operation
    new_plan = DropletPlan(
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

    # Add initial frame with current state
    initial_frame = matrix.copy()
    new_plan.frames.append(initial_frame)
    
    # Filter active droplets based on the last frame of existing_plan if available
    if existing_plan and existing_plan.active_droplets_per_frame:
        last_frame_active = set(existing_plan.active_droplets_per_frame[-1])
        active_droplets = [d for d in droplets if d.id in last_frame_active]
    else:
        active_droplets = droplets
    
    new_plan.active_droplets_per_frame.append([d.id for d in active_droplets])

    for droplet in active_droplets:
        new_plan.droplet_trajectories[droplet.id] = [droplet.origin_corner]

    # Execute mixing based on mode
    if mode == "split_recombine":
        logger.debug("Entering split mode")
        updated_droplets, new_plan = _mix_split_recombine(
            active_droplets, target_droplet, cycles, split_area, new_plan, logger, original_droplet_ids
        )
    elif mode == "2d_loop":
        logger.debug("Entering 2D loop")
        updated_droplets, new_plan = _mix_2d_loop(
            active_droplets, target_droplet, cycles, mixing_area_size, new_plan, logger, base_matrix
        )
    else:
        raise ValueError(f"Invalid mixing mode: {mode}. Must be 'split_recombine' or '2d_loop'")

    # Update frame count
    new_plan.frame_count = len(new_plan.frames)

    # Extend trajectories to match frame count
    for droplet_id, trajectory in new_plan.droplet_trajectories.items():
        while len(trajectory) < new_plan.frame_count:
            trajectory.append(trajectory[-1] if trajectory else (0, 0))

    logger.info(f"Mixing completed for droplet {droplet_id}: {new_plan.frame_count} frames generated")
    return updated_droplets, new_plan


def _mix_split_recombine(active_droplets: List[Droplet], target_droplet: Droplet, cycles: int,
                        split_area: Optional[Set[Tuple[int, int]]], plan: DropletPlan, logger, original_droplet_ids: Set[int]) -> Tuple[List[Droplet], DropletPlan]:
    """Execute split-recombine mixing cycles."""
    current_droplets = active_droplets.copy()
    current_droplet_id = target_droplet.id

    for cycle in range(cycles):
        logger.debug(f"Starting split-recombine cycle {cycle + 1}/{cycles}")

        # Pre-mix shuttle (brief back-and-forth movement)
        # current_droplets, plan = _add_pre_mix_shuttle(current_droplets, current_droplet_id, plan, logger)

        # Check if splitting is possible
        can_split = _can_split_droplet(current_droplets, current_droplet_id, logger)

        if can_split:
            # Handle odd electrode symmetry by extending footprint if needed
            adjusted_droplets = _handle_odd_electrode_symmetry(current_droplets, current_droplet_id, split_area, logger)

            # Execute isometric split with proper steps for mixing
            try:
                # Alternate splitting direction between cycles for better mixing
                if cycle % 2 == 0:
                    split_steps = [(2, 0), (0, 2)]  # Horizontal then vertical split
                else:
                    split_steps = [(0, 2), (2, 0)]  # Vertical then horizontal split
                updated_droplets, split_plan = isometric_split(
                    adjusted_droplets, np.zeros((128, 128), dtype=np.int32),  # Matrix not used for planning here
                    current_droplet_id, split_steps, simultaneous=True, logger=logger
                )

                # Extend plan with split frames (forward sequence)
                for i, frame in enumerate(split_plan.frames[1:], 1):  # i starts from 1
                    plan.frames.append(frame)
                    plan.active_droplets_per_frame.append(split_plan.active_droplets_per_frame[i])

                # Update trajectories (forward)
                for droplet_id, trajectory in split_plan.droplet_trajectories.items():
                    if droplet_id in plan.droplet_trajectories:
                        plan.droplet_trajectories[droplet_id].extend(trajectory[1:])  # Skip initial position
                    else:
                        plan.droplet_trajectories[droplet_id] = trajectory

                # Now add the reverse sequence to bring droplets back together
                reverse_frames = split_plan.frames[-2::-1]  # Reverse frames, skip the last frame (already added)
                reverse_active = split_plan.active_droplets_per_frame[-2::-1]
                for frame, active_ids in zip(reverse_frames, reverse_active):
                    plan.frames.append(frame)
                    plan.active_droplets_per_frame.append(list(active_ids))

                # Update trajectories with reverse sequence
                for droplet_id, trajectory in split_plan.droplet_trajectories.items():
                    if droplet_id in plan.droplet_trajectories:
                        # Add reverse trajectory (excluding the final position that's already there)
                        reverse_trajectory = trajectory[-2::-1]  # Reverse, skip last element
                        plan.droplet_trajectories[droplet_id].extend(reverse_trajectory)

                # Update droplet positions back to their recombined state
                # After recombination, we should only have the original droplet active
                # The subdroplets should be merged back into the original droplet
                recombined_droplets = []

                # Always recreate the original droplet at its recombined position
                # The final position of any subdroplet trajectory is the recombined position
                if split_plan.droplet_trajectories:
                    original_pos = list(split_plan.droplet_trajectories.values())[0][-1]  # Final position of any subdroplet
                    recombined_droplet = create_droplet(
                        droplet_id=target_droplet.id,
                        origin=original_pos,
                        target=original_pos,
                        shape=target_droplet.shape,  # Keep original shape
                        priority=target_droplet.priority,
                        vital_space=target_droplet.vital_space
                    )
                    recombined_droplets.append(recombined_droplet)
                    logger.debug(f"Recreated original droplet {target_droplet.id} at recombined position {original_pos}")
                else:
                    logger.error(f"No trajectories found in split_plan")
                    # Fallback: use the target droplet as-is
                    recombined_droplets.append(target_droplet)

                # Add back any other droplets that were originally in the list (not split-generated subdroplets)
                for droplet in active_droplets:
                    if droplet.id != target_droplet.id and droplet.id in original_droplet_ids and droplet.id not in [d.id for d in recombined_droplets]:
                        recombined_droplets.append(droplet)

                current_droplets = recombined_droplets
                # Keep the original droplet_id for the next cycle
                current_droplet_id = target_droplet.id

                # DEBUG: Log plan and droplet data at end of first cycle
                if cycle == 0:
                    logger.debug("=== END OF FIRST SPLIT-RECOMBINE CYCLE ===")
                    logger.debug(f"Plan frames: {len(plan.frames)}")
                    logger.debug(f"Active droplets per frame: {len(plan.active_droplets_per_frame)}")
                    if plan.active_droplets_per_frame:
                        logger.debug(f"  Last frame active droplets: {plan.active_droplets_per_frame[-1]}")
                    logger.debug(f"Current droplets: {len(current_droplets)}")
                    for d in current_droplets:
                        # Check if droplet is currently active (has electrodes activated in the last frame)
                        is_active = False
                        if plan.frames and len(plan.frames) > 0:
                            last_frame = plan.frames[-1]
                            droplet_positions = get_droplet_positions(d, d.origin_corner)
                            is_active = any(last_frame[x, y] == 1 for x, y in droplet_positions
                                          if 0 <= x < last_frame.shape[0] and 0 <= y < last_frame.shape[1])
                        logger.debug(f"  Droplet {d.id}: pos={d.origin_corner}, shape_size={len(d.shape)}, active={is_active}")
                    logger.debug(f"Trajectories: {list(plan.droplet_trajectories.keys())}")
                    for droplet_id, traj in plan.droplet_trajectories.items():
                        logger.debug(f"  Droplet {droplet_id}: trajectory length {len(traj)}, final_pos={traj[-1] if traj else 'None'}")
                    logger.debug("=== END DEBUG LOG ===")

                logger.debug(f"Split-recombine cycle completed, droplets recombined at original positions")

            except Exception as e:
                logger.warning(f"Split failed in cycle {cycle + 1}: {e}, switching to 2D loop")
                return _mix_2d_loop(current_droplets, target_droplet, cycles - cycle, plan, logger)
        else:
            logger.debug(f"Cannot split droplet {current_droplet_id}, switching to 2D loop for remaining cycles")
            return _mix_2d_loop(current_droplets, target_droplet, cycles - cycle, plan, logger)

    return current_droplets, plan


def _mix_2d_loop(active_droplets: List[Droplet], target_droplet: Droplet, cycles: int,
                mixing_area_size: Optional[int], plan: DropletPlan, logger, base_matrix: Optional[np.ndarray] = None) -> Tuple[List[Droplet], DropletPlan]:
    """Execute 2D looped motion mixing by moving between corner positions."""
    logger.debug(f"Starting 2D loop mixing for {cycles} cycles")
    logger.debug(f"Input plan has {len(plan.frames)} frames, {len(plan.droplet_trajectories)} trajectories")

    # Define mixing area as a rectangular region around the droplet
    # Use base_matrix if provided (shows permanent electrode state), otherwise use current frame
    area_matrix = base_matrix if base_matrix is not None else plan.frames[-1]
    mixing_area = _define_mixing_area(target_droplet, mixing_area_size, area_matrix, logger)
    logger.debug(f"Mixing area: {mixing_area}")

    # Calculate corner positions for the loop
    min_row, max_row, min_col, max_col = mixing_area
    corners = [
        (min_row, min_col),      # Top-left
        (min_row, max_col),      # Top-right
        (max_row, max_col),      # Bottom-right
        (max_row, min_col),      # Bottom-left
    ]
    logger.debug(f"Calculated corners: {corners}")

    # Store original position (center)
    original_position = target_droplet.origin_corner
    logger.debug(f"Starting from center position: {original_position}")

    # Step 1: Move from center to first corner
    first_corner = corners[0]  # Top-left corner
    logger.debug(f"Moving from center {original_position} to first corner {first_corner}")
    _move_droplet_direct(target_droplet, original_position, first_corner, plan, active_droplets)

    # Step 2: Repeat the 4-corner loop for the specified number of cycles
    # Each cycle: Corner1 -> Corner2 -> Corner3 -> Corner4 -> Corner1
    for cycle in range(cycles):
        logger.debug(f"Executing 4-corner loop cycle {cycle + 1}/{cycles}")

        # The 4-corner loop: Corner1 -> Corner2 -> Corner3 -> Corner4 -> Corner1
        corner_loop = corners + [corners[0]]
        logger.debug(f"Corner loop positions: {corner_loop}")

        # Move through the 4 corners
        for i in range(len(corner_loop) - 1):
            start_pos = corner_loop[i]
            end_pos = corner_loop[i + 1]
            logger.debug(f"Cycle {cycle + 1}: Moving from {start_pos} to {end_pos}")
            _move_droplet_direct(target_droplet, start_pos, end_pos, plan, active_droplets)

    # Step 3: Move back from first corner to center (reverse of step 1)
    final_position = target_droplet.origin_corner
    logger.debug(f"Moving back from {final_position} to center {original_position}")
    _move_droplet_direct(target_droplet, final_position, original_position, plan, active_droplets)

    # Verify we ended at the original position
    final_position = target_droplet.origin_corner
    if final_position != original_position:
        logger.error(f"ERROR: Droplet ended at {final_position} instead of original position {original_position}")
    else:
        logger.info(f"Successfully returned to original position: {original_position}")
        logger.info(f"   Final trajectory length: {len(plan.droplet_trajectories[target_droplet.id])}")
        logger.info(f"   Final frame count: {len(plan.frames)}")

    logger.debug(f"Final plan has {len(plan.frames)} frames")
    return active_droplets, plan


def _move_droplet_direct(droplet: Droplet, start_pos: Tuple[int, int], end_pos: Tuple[int, int],
                        plan: DropletPlan, active_droplets: List[Droplet]):
    """Move droplet directly from start to end position by creating intermediate frames."""
    current_pos = start_pos

    # Calculate the path (simple line movement)
    path = _calculate_direct_path(start_pos, end_pos)

    # Create frames for each step in the path
    for next_pos in path[1:]:  # Skip the starting position
        # Create new frame
        new_frame = plan.frames[-1].copy()

        # Clear old position
        old_positions = get_droplet_positions(droplet, current_pos)
        for x, y in old_positions:
            if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                new_frame[x, y] = 0

        # Set new position
        new_positions = get_droplet_positions(droplet, next_pos)
        for x, y in new_positions:
            if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                new_frame[x, y] = 1

        plan.frames.append(new_frame)
        plan.active_droplets_per_frame.append([d.id for d in active_droplets])
        plan.droplet_trajectories[droplet.id].append(next_pos)

        current_pos = next_pos

    # Update droplet position
    droplet.origin_corner = end_pos


def _calculate_direct_path(start_pos: Tuple[int, int], end_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
    """Calculate a direct path from start to end position."""
    sx, sy = start_pos
    ex, ey = end_pos

    # For corner movements, typically move horizontally or vertically
    path = [start_pos]

    if sx == ex:  # Same row, move horizontally
        step = 1 if ey > sy else -1
        for y in range(sy + step, ey + step, step):
            path.append((sx, y))
    elif sy == ey:  # Same column, move vertically
        step = 1 if ex > sx else -1
        for x in range(sx + step, ex + step, step):
            path.append((x, sy))
    else:
        # Move horizontally first, then vertically (no diagonal)
        if abs(ex - sx) > 0:
            # Horizontal move
            step = 1 if ex > sx else -1
            for x in range(sx + step, ex + step, step):
                path.append((x, sy))
        if abs(ey - sy) > 0:
            # Vertical move
            step = 1 if ey > sy else -1
            for y in range(sy + step, ey + step, step):
                path.append((ex, y))

    return path


def _add_pre_mix_shuttle(droplets: List[Droplet], droplet_id: int, plan: DropletPlan, logger) -> Tuple[List[Droplet], DropletPlan]:
    """Add brief pre-mix shuttle movement - small oscillations for initial mixing."""
    # Very small back-and-forth movement (1 electrode step)
    shuttle_distance = 1
    directions = [(0, shuttle_distance), (0, -shuttle_distance)]  # Right then left

    droplet = next((d for d in droplets if d.id == droplet_id), None)
    if not droplet:
        return droplets, plan

    start_pos = droplet.origin_corner

    for dx, dy in directions:
        new_pos = (start_pos[0] + dx, start_pos[1] + dy)

        # Check if position is valid
        if not _is_valid_position(droplet, new_pos, plan.frames[-1]):
            logger.debug(f"Pre-mix shuttle position {new_pos} invalid, skipping")
            continue

        # Create frame
        new_frame = plan.frames[-1].copy()

        # Clear old position
        old_positions = get_droplet_positions(droplet, droplet.origin_corner)
        for x, y in old_positions:
            if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                new_frame[x, y] = 0

        # Set new position
        new_positions = get_droplet_positions(droplet, new_pos)
        for x, y in new_positions:
            if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                new_frame[x, y] = 1

        plan.frames.append(new_frame)
        plan.active_droplets_per_frame.append([d.id for d in droplets])
        plan.droplet_trajectories[droplet.id].append(new_pos)
        droplet.origin_corner = new_pos

        logger.debug(f"Pre-mix shuttle: moved to {new_pos}")

    return droplets, plan


def _can_split_droplet(droplets: List[Droplet], droplet_id: int, logger) -> bool:
    """Check if droplet can be split (has even number of electrodes)."""
    droplet = next((d for d in droplets if d.id == droplet_id), None)
    if not droplet:
        return False

    electrode_count = len(droplet.shape)
    can_split = electrode_count >= 4 and electrode_count % 2 == 0  # Minimum 4 electrodes, even number

    logger.debug(f"Droplet {droplet_id} has {electrode_count} electrodes, can_split: {can_split}")
    return can_split


def _is_valid_position(droplet: Droplet, position: Tuple[int, int], matrix: np.ndarray) -> bool:
    """Check if position is valid for droplet."""
    from .common import is_valid_droplet_position
    return is_valid_droplet_position(droplet, position, matrix)


def _get_available_area_around_droplet(droplet: Droplet, matrix: np.ndarray) -> Set[Tuple[int, int]]:
    """Get available electrode area around droplet for mixing."""
    # Get positions within a reasonable radius
    radius = 5
    available = set()

    cx, cy = droplet.origin_corner
    rows, cols = matrix.shape

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < rows and 0 <= y < cols and matrix[x, y] == 0:  # Free electrode
                available.add((x, y))

    return available


def _select_loop_pattern(available_area: Set[Tuple[int, int]], logger) -> Optional[List[Tuple[int, int]]]:
    """Select appropriate loop pattern based on available area."""
    # Try 2x4 loop first
    pattern_2x4 = _create_2x4_loop_pattern(available_area)
    if pattern_2x4:
        logger.debug("Using 2x4 loop pattern")
        return pattern_2x4

    # Try 2x3 loop
    pattern_2x3 = _create_2x3_loop_pattern(available_area)
    if pattern_2x3:
        logger.debug("Using 2x3 loop pattern")
        return pattern_2x3

    # Try 2x2 loop
    pattern_2x2 = _create_2x2_loop_pattern(available_area)
    if pattern_2x2:
        logger.debug("Using 2x2 loop pattern")
        return pattern_2x2

    logger.debug("No loop pattern available")
    return None


def _create_2x4_loop_pattern(available_area: Set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
    """Create 2x4 loop pattern if possible."""
    # This is a simplified implementation - would need proper pattern generation
    # For now, return None to use fallback
    return None


def _create_2x3_loop_pattern(available_area: Set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
    """Create 2x3 loop pattern if possible."""
    return None


def _create_2x2_loop_pattern(available_area: Set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
    """Create 2x2 loop pattern if possible."""
    return None


def _create_linear_shuttle_pattern(center: Tuple[int, int], available_area: Set[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Create linear shuttling pattern as fallback."""
    # Simple back-and-forth on a line
    cx, cy = center
    pattern = []

    # Try horizontal shuttle
    left_pos = (cx, cy - 2)
    right_pos = (cx, cy + 2)

    if left_pos in available_area and right_pos in available_area:
        pattern = [left_pos, right_pos]
    else:
        # Try vertical shuttle
        up_pos = (cx - 2, cy)
        down_pos = (cx + 2, cy)
        if up_pos in available_area and down_pos in available_area:
            pattern = [up_pos, down_pos]

    return pattern if pattern else [center]  # Fallback to no movement


def _handle_odd_electrode_symmetry(droplets: List[Droplet], droplet_id: int,
                                 split_area: Optional[Set[Tuple[int, int]]], logger) -> List[Droplet]:
    """Handle odd electrode counts by temporarily extending footprint within split_area."""
    droplet = next((d for d in droplets if d.id == droplet_id), None)
    if not droplet:
        return droplets

    electrode_count = len(droplet.shape)
    if electrode_count % 2 == 0:
        return droplets  # No adjustment needed

    logger.debug(f"Droplet {droplet_id} has odd electrode count ({electrode_count}), extending footprint")

    # For now, return unchanged - full implementation would extend shape
    # This is a placeholder for the symmetry extension logic
    return droplets


def _create_2x4_loop_pattern(available_area: Set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
    """Create 2x4 loop pattern: top sweep → descend → bottom return → ascend."""
    # Find center of available area
    if not available_area:
        return None

    rows = {r for r, c in available_area}
    cols = {c for r, c in available_area}
    center_row = sum(rows) // len(rows)
    center_col = sum(cols) // len(cols)

    # Define 2x4 loop relative to center
    pattern = [
        (center_row - 1, center_col - 1),  # Top-left
        (center_row - 1, center_col),      # Top-center-left
        (center_row - 1, center_col + 1),  # Top-center-right
        (center_row - 1, center_col + 2),  # Top-right
        (center_row, center_col + 2),      # Middle-right
        (center_row + 1, center_col + 2),  # Bottom-right
        (center_row + 1, center_col + 1),  # Bottom-center-right
        (center_row + 1, center_col),      # Bottom-center-left
        (center_row + 1, center_col - 1),  # Bottom-left
        (center_row, center_col - 1),      # Middle-left
    ]

    # Check if all positions are available
    if all(pos in available_area for pos in pattern):
        return pattern
    return None


def _create_2x3_loop_pattern(available_area: Set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
    """Create 2x3 loop pattern with alternating pivot columns."""
    # Simplified implementation - alternate between two columns
    if not available_area:
        return None

    rows = {r for r, c in available_area}
    cols = {c for r, c in available_area}
    center_row = sum(rows) // len(rows)
    min_col, max_col = min(cols), max(cols)

    # Alternate between left and right columns
    pattern = [
        (center_row - 1, min_col),     # Top-left
        (center_row, min_col),         # Middle-left
        (center_row + 1, min_col),     # Bottom-left
        (center_row + 1, max_col),     # Bottom-right
        (center_row, max_col),         # Middle-right
        (center_row - 1, max_col),     # Top-right
    ]

    if all(pos in available_area for pos in pattern):
        return pattern
    return None


def _create_2x2_loop_pattern(available_area: Set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
    """Create 2x2 loop pattern with origin shift after each turn."""
    if not available_area:
        return None

    rows = {r for r, c in available_area}
    cols = {c for r, c in available_area}
    center_row = sum(rows) // len(rows)
    center_col = sum(cols) // len(cols)

    # Simple 2x2 square
    pattern = [
        (center_row - 1, center_col - 1),  # Top-left
        (center_row - 1, center_col),      # Top-right
        (center_row, center_col),          # Bottom-right
        (center_row, center_col - 1),      # Bottom-left
    ]

    if all(pos in available_area for pos in pattern):
        return pattern
    return None


def _generate_loop_trajectory(start_pos: Tuple[int, int], pattern: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Generate trajectory for loop pattern with translational shifts."""
    trajectory = [start_pos]

    # Execute the loop
    for pos in pattern:
        trajectory.append(pos)

    # Add translational shift for next lap (if 2x4 pattern)
    if len(pattern) >= 8:  # 2x4 pattern
        # Shift origin by one electrode for next lap
        shift_row, shift_col = 0, 1  # Shift right
        shifted_pattern = [(r + shift_row, c + shift_col) for r, c in pattern]
        for pos in shifted_pattern:
            trajectory.append(pos)

    # Return to start
    trajectory.append(start_pos)
    return trajectory


def _define_mixing_area(droplet: Droplet, mixing_area_size: Optional[int], matrix: np.ndarray, logger) -> Tuple[int, int, int, int]:
    """Define a rectangular mixing area around the droplet, ensuring all positions are free.

    Returns: (min_row, max_row, min_col, max_col)
    """
    cx, cy = droplet.origin_corner
    rows, cols = matrix.shape

    # Use provided size or default to 10
    area_size = mixing_area_size if mixing_area_size is not None else 10

    # Start with the desired area
    min_row = max(0, cx - area_size // 2)
    max_row = min(rows - 1, cx + area_size // 2)
    min_col = max(0, cy - area_size // 2)
    max_col = min(cols - 1, cy + area_size // 2)

    # Ensure all positions in the area are free (0) for the droplet to move
    # Allow positions currently occupied by the target droplet itself
    droplet_positions = get_droplet_positions(droplet, droplet.origin_corner)
    logger.debug(f"Droplet positions: {sorted(droplet_positions)}")

    original_min_row, original_max_row = min_row, max_row
    original_min_col, original_max_col = min_col, max_col

    # If not, shrink the area until all positions are free (except droplet's current positions)
    while min_row < max_row and min_col < max_col:
        area_valid = True
        problematic_positions = []
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                pos = (r, c)
                matrix_value = matrix[r, c]
                # Allow if free (0) or currently occupied by the target droplet
                if matrix_value != 0 and pos not in droplet_positions:
                    area_valid = False
                    problematic_positions.append((pos, matrix_value))
                    if len(problematic_positions) >= 5:  # Limit logging
                        break
            if not area_valid:
                break

        if len(problematic_positions) > 0:
            logger.debug(f"Found {len(problematic_positions)} problematic positions in area [{min_row}:{max_row+1}, {min_col}:{max_col+1}]: {problematic_positions[:5]}")

        if area_valid:
            break

        # Shrink the area by 1 in each direction
        min_row = max(0, min_row + 1)
        max_row = min(rows - 1, max_row - 1)
        min_col = max(0, min_col + 1)
        max_col = min(cols - 1, max_col - 1)

    # Warn if area was shrunk
    if (min_row != original_min_row or max_row != original_max_row or
        min_col != original_min_col or max_col != original_max_col):
        original_size = (original_max_row - original_min_row + 1) * (original_max_col - original_min_col + 1)
        final_size = (max_row - min_row + 1) * (max_col - min_col + 1)
        logger.warning(f"Mixing area shrunk from {original_size} to {final_size} electrodes due to occupied positions")

    logger.debug(f"Defined mixing area (size {area_size}, final {max_row-min_row+1}x{max_col-min_col+1}): rows [{min_row}, {max_row}], cols [{min_col}, {max_col}]")
    return (min_row, max_row, min_col, max_col)


def _move_to_area_border(droplet: Droplet, mixing_area: Tuple[int, int, int, int],
                        plan: DropletPlan, droplets: List[Droplet], logger) -> Tuple[int, int]:
    """Move droplet step by step to the border of the mixing area.

    Returns: Final border position
    """
    min_row, max_row, min_col, max_col = mixing_area
    current_pos = droplet.origin_corner

    # Find the closest border position
    target_row = min_row if current_pos[0] > (min_row + max_row) // 2 else max_row
    target_col = min_col if current_pos[1] > (min_col + max_col) // 2 else max_col
    border_pos = (target_row, target_col)

    logger.debug(f"Moving from {current_pos} to border position {border_pos}")

    # Move step by step to the border
    while current_pos != border_pos:
        # Calculate next step towards border
        dr = 1 if target_row > current_pos[0] else -1 if target_row < current_pos[0] else 0
        dc = 1 if target_col > current_pos[1] else -1 if target_col < current_pos[1] else 0

        next_pos = (current_pos[0] + dr, current_pos[1] + dc)

        # Check if next position is valid
        if not _is_valid_position(droplet, next_pos, plan.frames[-1]):
            # Try moving only in one direction
            if dr != 0 and _is_valid_position(droplet, (current_pos[0] + dr, current_pos[1]), plan.frames[-1]):
                next_pos = (current_pos[0] + dr, current_pos[1])
            elif dc != 0 and _is_valid_position(droplet, (current_pos[0], current_pos[1] + dc), plan.frames[-1]):
                next_pos = (current_pos[0], current_pos[1] + dc)
            else:
                logger.warning(f"Cannot move closer to border from {current_pos}")
                break

        # Create frame for this move
        new_frame = plan.frames[-1].copy()

        # Clear old position
        old_positions = get_droplet_positions(droplet, current_pos)
        for x, y in old_positions:
            if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                new_frame[x, y] = 0

        # Set new position
        new_positions = get_droplet_positions(droplet, next_pos)
        for x, y in new_positions:
            if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                new_frame[x, y] = 1

        plan.frames.append(new_frame)
        plan.active_droplets_per_frame.append([d.id for d in droplets])
        plan.droplet_trajectories[droplet.id].append(next_pos)
        current_pos = next_pos
        droplet.origin_corner = current_pos

    return current_pos


def _generate_loop_path(start_pos: Tuple[int, int], mixing_area: Tuple[int, int, int, int],
                       matrix: np.ndarray, logger) -> List[Tuple[int, int]]:
    """Generate a perimeter loop path that travels around the border of the mixing area.

    Creates a continuous loop around the rectangular area's perimeter, returning to start.
    """
    min_row, max_row, min_col, max_col = mixing_area
    path = []

    # Find the closest border position to start from
    current_pos = _find_closest_border_position(start_pos, mixing_area)

    # Create a rectangular perimeter loop: top → right → bottom → left → repeat
    # We'll do one full loop around the perimeter

    # Top row: left to right
    for col in range(min_col, max_col + 1):
        pos = (min_row, col)
        if _is_valid_position_for_loop(pos, matrix):
            if pos != current_pos:  # Don't duplicate start
                path.append(pos)

    # Right column: top to bottom (skip corners already visited)
    for row in range(min_row + 1, max_row + 1):
        pos = (row, max_col)
        if _is_valid_position_for_loop(pos, matrix):
            path.append(pos)

    # Bottom row: right to left (skip corners already visited)
    for col in range(max_col - 1, min_col - 1, -1):
        pos = (max_row, col)
        if _is_valid_position_for_loop(pos, matrix):
            path.append(pos)

    # Left column: bottom to top (skip corners already visited)
    for row in range(max_row - 1, min_row, -1):
        pos = (row, min_col)
        if _is_valid_position_for_loop(pos, matrix):
            path.append(pos)

    # Ensure we can return to start (the loop should be closed)
    if path and _is_adjacent_to_start(path[-1], current_pos):
        path.append(current_pos)

    logger.debug(f"Generated perimeter loop path with {len(path)} steps around area {mixing_area}")
    return path


def _find_closest_border_position(start_pos: Tuple[int, int], mixing_area: Tuple[int, int, int, int]) -> Tuple[int, int]:
    """Find the closest position on the border of the mixing area to start the loop."""
    min_row, max_row, min_col, max_col = mixing_area
    sx, sy = start_pos

    # If start_pos is already on border, use it
    if (sx == min_row or sx == max_row or sy == min_col or sy == max_col):
        return start_pos

    # Otherwise, find closest border position
    # Prefer top-left corner as default starting point
    return (min_row, min_col)


def _is_valid_position_for_loop(position: Tuple[int, int], matrix: np.ndarray) -> bool:
    """Check if position is valid for droplet movement (free electrode)."""
    x, y = position
    if 0 <= x < matrix.shape[0] and 0 <= y < matrix.shape[1]:
        return matrix[x, y] == 0  # Free electrode
    return False


def _is_adjacent_to_start(current_pos: Tuple[int, int], start_pos: Tuple[int, int]) -> bool:
    """Check if current position is adjacent to start position."""
    dr = abs(current_pos[0] - start_pos[0])
    dc = abs(current_pos[1] - start_pos[1])
    return (dr == 0 and dc == 1) or (dr == 1 and dc == 0)
