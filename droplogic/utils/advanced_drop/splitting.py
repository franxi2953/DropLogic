"""
Droplet Splitting Module for Advanced Drop Manipulation

This module provides functionality to split droplets from reservoirs,
supporting both 1-to-2 and 1-to-3 splitting protocols.

FUNCTION HIERARCHY:
==================

PUBLIC API:
- reservoir_extraction()          # Main entry point for reservoir splitting
- isometric_split()               # Main entry point for isometric splitting

PROTOCOL FUNCTIONS:               # High-level splitting logic
- _split_1to3()                   # 1-to-3 splitting protocol (higher complexity)
- _split_1to2()                   # 1-to-2 splitting protocol

CORE HELPERS:                     # Mid-level operations
- _generate_extraction_frames()   # Frame generation for reservoir extraction
- _generate_isometric_split_step()    # Frame generation for isometric splitting
- _calculate_trajectory()         # Movement path calculation
- _validate_1to2_inputs()         # Input validation for reservoir extraction
- _validate_isometric_inputs()    # Input validation for isometric splitting
- _validate_no_overlap()          # Overlap prevention
- _add_position_offset()     # Position calculations
- _split_shape_equally()          # Shape division for equal splitting

UTILITY FUNCTIONS:                # Low-level operations
- _create_extraction_frame()      # Single frame creation for reservoir extraction
- _create_split_frame()           # Initial split frame creation
- _create_isometric_frame()       # Movement frame creation for isometric splitting
- _calculate_droplet_halo_positions() # Halo calculations
- _create_final_extraction_frame() # Final frame creation
- _extend_other_trajectories()    # Trajectory management
- _relax_reservoir()              # Shape optimization
- _update_reservoir_shape()       # Shape updates
- _create_split_droplet()         # Droplet creation
- _generate_simultaneous_trajectories() # Simultaneous trajectory generation
- _split_shape_equally()          # Shape division for equal splitting
"""

from typing import List, Tuple, Optional, Dict, Set, Union
from dataclasses import dataclass
from copy import deepcopy
from .common import Droplet, DropletPlan, create_droplet, get_droplet_positions, relax_droplet_shape, next_event_id, tag_frame_span
import numpy as np


# =============================================================================
# PUBLIC API
# =============================================================================

def reservoir_extraction(
    droplets: List[Droplet],
    matrix: np.ndarray,
    reservoir_droplet_id: int,
    split_mode: str,
    steps: Optional[Tuple[int, int]] = None,
    split_size: Optional[Union[Tuple[int, int], Set[Tuple[int, int]]]] = None,
    new_droplet_id: Optional[int] = None,
    halo_size: int = 0,
    separation_steps: int = 3,
    logger=None,
    existing_plan: Optional[DropletPlan] = None,
    # Optional linear sweep parameters (user can pass these directly instead of a LinearConfig)
    linear_drops_number: Optional[int] = None,
    linear_offset: Optional[int] = None,
    linear_cfg: Optional[object] = None,
    linear_space_per_col: Optional[int] = None,
    linear_space_per_row: Optional[int] = None,
    linear_drop_shape: Optional[Union[Tuple[int,int], Set[Tuple[int,int]]]] = None,
    linear_direction: Optional[Tuple[int,int]] = None,
) -> Tuple[List[Droplet], DropletPlan]:
    """
    Extract a droplet from a reservoir (core splitting function).

    Args:
        droplets: List of current droplets
        droplet_plan: Current droplet plan
        reservoir_droplet_id: ID of the reservoir droplet to split from
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
        split_size: Size of the central droplet to extract as (height, width) for 1to3,
                   or shape as set of relative coordinates for 1to2.
                   For 1to3: (height, width) of central droplet to extract, centered in reservoir.
                   For 1to2: Set of relative coordinates from reservoir corner.
                   None = use default (1, 1) for 1to3 or {(0, 0)} for 1to2
        new_droplet_id: ID for the new droplet (None = auto-generate next available ID)
        halo_size: Size of unactivated electrode halo around extracted droplet (1to2 only)
        separation_steps: Number of steps for moving droplets to separate from each other (1to3 only)

    Returns:
        Tuple of (updated_droplets, updated_droplet_plan)

    Raises:
        ValueError: If reservoir droplet not found, invalid parameters, or final position overlaps reservoir
    """
    # Use provided logger or create a default one
    if logger is None:
        from ..logging_config import setup_droplogic_logger
        logger = setup_droplogic_logger('droplogic.advanced_drop.splitting')

    logger.info(f"Starting reservoir extraction: reservoir_id={reservoir_droplet_id}, mode={split_mode}, steps={steps}")

    # Validate steps for modes that require it
    if split_mode in ['1to2', '1to3'] and steps is None:
        raise ValueError(f"steps is required for split_mode '{split_mode}'")

    # Find the reservoir droplet
    reservoir_droplet = None
    for droplet in droplets:
        if droplet.id == reservoir_droplet_id:
            reservoir_droplet = droplet
            break

    if reservoir_droplet is None:
        raise ValueError(f"Reservoir droplet with id {reservoir_droplet_id} not found")

    # Make a deep copy of the existing plan to avoid accidental in-place mutation
    existing_plan_copy = deepcopy(existing_plan) if existing_plan is not None else None

    previous_droplets = [d for d in droplets]

    # Execute the appropriate splitting protocol (pass the copied plan)
    if split_mode == '1to2':
        updated_droplets, new_plan = _split_1to2(
            droplets, matrix, reservoir_droplet, steps, split_size, new_droplet_id, halo_size, logger, existing_plan_copy
        )
    elif split_mode == '1to3':
        updated_droplets, new_plan = _split_1to3(
            droplets, matrix, reservoir_droplet, steps, split_size, new_droplet_id, logger, separation_steps, existing_plan_copy
        )
    elif split_mode == 'linear':
        # Build LinearConfig from provided args if needed
        cfg_obj = None
        if isinstance(linear_cfg, LinearConfig):
            cfg_obj = linear_cfg
        else:
            # Build from individual parameters with sensible defaults
            cfg_obj = LinearConfig(
                drops_number=(linear_drops_number if linear_drops_number is not None else 1),
                offset=(linear_offset if linear_offset is not None else 0),
                space_per_col=(linear_space_per_col or 1),
                space_per_row=(linear_space_per_row or 1),
                drop_shape=(linear_drop_shape if linear_drop_shape is not None else (1, 1)),
                direction=(linear_direction if linear_direction is not None else (1, 0))
            )

        updated_droplets, new_plan = _split_linear(
            droplets, matrix, reservoir_droplet, cfg_obj, new_droplet_id, logger, existing_plan_copy
        )
    else:
        raise ValueError(f"Invalid split_mode: {split_mode}. Must be '1to2', '1to3', or 'linear'")

    logger.info(f"Reservoir extraction completed: created {len(updated_droplets) - len(previous_droplets)} new droplets")

    return updated_droplets, new_plan

def isometric_split(
    droplets: List[Droplet],
    matrix: np.ndarray,
    droplet_id: int,
    steps: List[Tuple[int, int]],
    simultaneous: bool = True,
    new_droplet_id: Optional[int] = None,
    logger=None
) -> Tuple[List[Droplet], DropletPlan]:
    """
    Divides a droplet into subdroplets of equal size with sequential symmetric displacement.

    Each step splits current droplets into 2 subdroplets each, then moves them symmetrically.
    Only one direction per step can be non-zero (horizontal OR vertical splitting).

    Args:
        droplets: List of current droplets
        droplet_plan: Current droplet plan
        droplet_id: ID of the droplet to split
        steps: List of (dy, dx) displacement tuples applied sequentially.
                  Each step must have at least one direction as 0 (horizontal OR vertical).
                  Positive values move down/right, negative values move up/left.
                  First value affects rows (vertical), second affects columns (horizontal).
        simultaneous: If True, subdroplets within each step move simultaneously.
                         If False, subdroplets within each step move sequentially.
        new_droplet_id: ID for the first new subdroplet (subsequent IDs auto-generated)
        logger: Optional logger instance

    Returns:
        Tuple of (updated_droplets, updated_droplet_plan)

    Raises:
        ValueError: If droplet not found, invalid steps, or insufficient electrodes

    Example:
        steps = [(0, 5), (3, 0)]:
        - Step 1: Split 1 droplet into 2 (2 electrodes each), move to (0,5) and (0,-5)
        - Step 2: Split each of those 2 into 2 more (1 electrode each), move (3,0) and (-3,0)
        - Result: 4 subdroplets total
    """
    # Use provided logger or create a default one
    if logger is None:
        from ..logging_config import setup_droplogic_logger
        logger = setup_droplogic_logger('droplogic.advanced_drop.splitting')

    logger.info(f"Starting isometric split: droplet_id={droplet_id}, steps={steps}, simultaneous={simultaneous}")

    initial_droplet_count = len(droplets)

    # Create a new plan for the isometric split
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

    # The extend_plan method now handles keeping active droplets from existing plans,
    # so we don't need to add all droplets here - only the ones being split
    matrix_shape = matrix.shape
    initial_frame = np.zeros(matrix_shape, dtype=np.int32)

    # Only add the source droplet being split
    source_droplet = next((d for d in droplets if d.id == droplet_id), None)
    if source_droplet is None:
        raise ValueError(f"Droplet with id {droplet_id} not found")

    source_positions = get_droplet_positions(source_droplet, source_droplet.origin_corner)
    for x, y in source_positions:
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            initial_frame[x, y] = 1

    new_plan.frames.append(initial_frame)
    new_plan.active_droplets_per_frame.append([droplet_id])  # Only source droplet is active initially
    new_plan.droplet_trajectories[droplet_id] = [source_droplet.origin_corner]

    # Validate input steps
    _validate_isometric_inputs(steps, logger)

    # Find the initial droplet to split
    initial_droplet = None
    for droplet in droplets:
        if droplet.id == droplet_id:
            initial_droplet = droplet
            break

    if initial_droplet is None:
        raise ValueError(f"Droplet with id {droplet_id} not found")

    # Start with the initial droplet
    current_droplets_to_split = [droplet_id]
    current_active_droplets = [droplet_id]  # Start with original droplet active

    for step_idx, (dy, dx) in enumerate(steps):
        logger.info(f"Applying step {step_idx + 1}/{len(steps)}: ({dy}, {dx})")
        logger.debug(f"=== STEP {step_idx + 1}/{len(steps)}: ({steps[step_idx][0]}, {steps[step_idx][1]}) ===")
        logger.debug(f"Starting with {len(current_droplets_to_split)} droplets to split:")
        for droplet_id in current_droplets_to_split:
            droplet = next((d for d in droplets if d.id == droplet_id), None)
            if droplet:
                shape_str = f"{{{', '.join(f'({dx},{dy})' for dx, dy in sorted(droplet.shape))}}}"
                logger.debug(f"  BEFORE Droplet {droplet_id}: {len(droplet.shape)} electrodes at {droplet.origin_corner}, shape={shape_str}")

        # For each current droplet to split, create two subdroplets
        new_current_droplets = []

        for current_droplet_id in current_droplets_to_split:
            # Find the current droplet
            current_droplet = None
            for droplet in droplets:
                if droplet.id == current_droplet_id:
                    current_droplet = droplet
                    break

            if current_droplet is None:
                logger.warning(f"Droplet {current_droplet_id} not found, skipping")
                continue

            # Skip droplets with odd electrode counts
            num_electrodes = len(current_droplet.shape)
            if num_electrodes % 2 != 0:
                logger.warning(f"Droplet {current_droplet_id} has {num_electrodes} electrodes (odd), skipping split")
                new_current_droplets.append(current_droplet_id)  # Keep it for next step
                continue

            # Split the droplet into 2 equal rectangular parts, preferring the direction of movement
            sub_shapes = _split_shape_equally(current_droplet.shape, 2, dx, dy, logger)

            if not sub_shapes:
                logger.warning(f"Skipping step {step_idx + 1} for droplet {current_droplet_id}: cannot split into coherent rectangles")
                new_current_droplets.append(current_droplet_id)  # Keep original droplet for next step
                continue

            # Calculate movement displacements from current droplet position. The movement is flipped in dx/dy, as the matrix use another convention
            pos_direction = (dy, dx)
            neg_direction = (-dy, -dx)
            final_positions = [
                _add_position_offset(current_droplet.origin_corner, pos_direction),
                _add_position_offset(current_droplet.origin_corner, neg_direction)
            ]

            # Assign sub-shapes to final positions based on spatial relationship
            # For horizontal movement (dx != 0): left sub-shape goes left, right sub-shape goes right
            # For vertical movement (dy != 0): top sub-shape goes up, bottom sub-shape goes down
            sub_shapes, final_positions = _assign_shapes_to_directions(
                sub_shapes, final_positions, pos_direction, neg_direction, logger
            )

            # Adjust final positions to account for subdroplet offsets
            # Each subdroplet should move the full steps from its starting position
            adjusted_final_positions = []
            for sub_shape, final_pos in zip(sub_shapes, final_positions):
                if sub_shape:
                    min_dx = min(dx for dx, dy in sub_shape)
                    min_dy = min(dy for dx, dy in sub_shape)
                    adjusted_final_pos = (final_pos[0] + min_dx, final_pos[1] + min_dy)
                else:
                    adjusted_final_pos = final_pos
                adjusted_final_positions.append(adjusted_final_pos)
            final_positions = adjusted_final_positions

            # Collect existing IDs before frame generation
            existing_ids_before = {d.id for d in droplets}

            # Generate frames for this splitting and movement step
            droplets, new_plan = _generate_isometric_split_step(
                droplets, new_plan, current_droplet, sub_shapes, final_positions,
                simultaneous, new_droplet_id, logger
            )

            # Find the IDs of the newly created subdroplets
            new_subdroplet_ids = [d.id for d in droplets if d.id not in existing_ids_before]

            # Update new_droplet_id for next subdroplet
            if new_droplet_id is not None and new_subdroplet_ids:
                new_droplet_id = max(new_subdroplet_ids) + 1

            # Add the new subdroplet IDs to the list for next step
            new_current_droplets.extend(new_subdroplet_ids)

        # Update current droplets for next step
        current_droplets_to_split = new_current_droplets
        current_active_droplets = new_current_droplets.copy()  # Update active droplets for next step

        # Update droplet positions to their final positions for next step
        # This ensures subsequent steps use the correct current positions
        for droplet_id in new_current_droplets:
            droplet = next((d for d in droplets if d.id == droplet_id), None)
            if droplet and droplet_id in new_plan.droplet_trajectories:
                trajectory = new_plan.droplet_trajectories[droplet_id]
                if trajectory:
                    # Update droplet's origin_corner to its final position
                    final_position = trajectory[-1]
                    droplet.origin_corner = final_position
                    # logger.debug(f"Updated droplet {droplet_id} position to {final_position} for next step")

        logger.debug(f"Created {len(new_current_droplets)} new droplets for next step:")
        for droplet_id in new_current_droplets:
            droplet = next((d for d in droplets if d.id == droplet_id), None)
            if droplet:
                shape_str = f"{{{', '.join(f'({dx},{dy})' for dx, dy in sorted(droplet.shape))}}}"
                logger.debug(f"  AFTER Droplet {droplet_id}: {len(droplet.shape)} electrodes at {droplet.origin_corner}, shape={shape_str}")
        logger.debug(f"--- End of Step {step_idx + 1} ---")

    total_subdroplets = len([d for d in droplets if d.id != droplet_id])
    logger.info(f"Isometric split completed: created {total_subdroplets} subdroplets from droplet {droplet_id}")
    return droplets.copy(), new_plan

# =============================================================================
# PROTOCOL FUNCTIONS (High-level splitting logic)
# =============================================================================

def _split_1to2(
    droplets: List[Droplet],
    matrix: np.ndarray,
    reservoir_droplet: Droplet,
    steps: Tuple[int, int],
    split_size: Optional[Union[Tuple[int, int], Set[Tuple[int, int]]]],
    new_droplet_id: Optional[int],
    halo_size: int,
    logger,
    existing_plan: Optional[DropletPlan] = None
) -> Tuple[List[Droplet], DropletPlan]:
    """
    Execute 1-to-2 splitting protocol for reservoir extraction.

    This function extracts a portion of a reservoir droplet and moves it to a new position,
    leaving the remaining reservoir with a relaxed shape.

    Args:
        droplets: List of current droplets
        matrix: DMF chip matrix (0=free, 1=occupied, -1=forbidden)
        reservoir_droplet: The reservoir droplet to split from
        steps: (vertical_offset, horizontal_offset) from reservoir corner to place new droplet.
               First value affects row (vertical): negative = up/north, positive = down/south
               Second value affects column (horizontal): negative = left/west, positive = right/east
               Final position = reservoir_corner + steps. Must not overlap with reservoir.
        split_size: Shape of the droplet to extract as relative coordinates from reservoir corner.
                   Must be a subset of the reservoir's shape. Coordinates are relative to the
                   reservoir's origin_corner. Can be a set of (row, col) tuples or None for default {(0, 0)}
        new_droplet_id: ID for the new droplet (None = auto-generate next available ID)
        halo_size: Size of unactivated electrode halo around extracted droplet
        logger: Logger instance for logging

    Returns:
        Tuple of (updated_droplets, new_droplet_plan)

    Raises:
        ValueError: If reservoir droplet not found, invalid parameters, or final position overlaps reservoir
    """
    logger.info(f"Executing 1-to-2 splitting for droplet {reservoir_droplet.id} with steps {steps}")

    # Create a new plan for the 1-to-2 split
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

    # Add initial frame with active droplets from existing plan (only keep active ones, don't reactivate all)
    matrix_shape = matrix.shape
    active_droplet_ids = set()
    if existing_plan and existing_plan.active_droplets_per_frame:
        active_droplet_ids = set(existing_plan.active_droplets_per_frame[-1])


    initial_frame = np.zeros(matrix_shape, dtype=np.int32)
    for droplet in droplets:
        if droplet.id in active_droplet_ids:  # Only include currently active droplets
            positions = get_droplet_positions(droplet, droplet.origin_corner)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    initial_frame[x, y] = 1
    new_plan.frames.append(initial_frame)
    # Compute active droplets based on frame content, not just from existing plan
    # Only pass droplets that are in existing_active_ids to avoid computing active status for inactive droplets
    active_droplets_only = [d for d in droplets if d.id in active_droplet_ids]
    new_plan.active_droplets_per_frame.append(_compute_active_droplets_from_frame(initial_frame, active_droplets_only))
    for droplet in droplets:
        new_plan.droplet_trajectories[droplet.id] = [droplet.origin_corner]

    # 1. Validate inputs
    if halo_size < 1:
        halo_size = 1
    _validate_1to2_inputs(steps, split_size, reservoir_droplet.shape, logger)

    # 2. Calculate split shapes (reservoir - split_size, new_droplet = split_size)
    if split_size is None:
        new_droplet_shape = {(0, 0)}  # Default to single electrode
    elif isinstance(split_size, set):
        new_droplet_shape = split_size
    else:
        # split_size is a tuple (height, width) - convert to set of coordinates
        height, width = split_size
        new_droplet_shape = {(i, j) for i in range(height) for j in range(width)}
    updated_reservoir_shape = reservoir_droplet.shape - new_droplet_shape

    # Relax reservoir shape to be more compact and rectangular before trajectory calculation
    reservoir_droplet.shape = updated_reservoir_shape
    relax_droplet_shape(reservoir_droplet, new_plan, droplets, logger)

    # 3. Calculate trajectory from reservoir to final position (now from relaxed origin)
    final_position = _add_position_offset(reservoir_droplet.origin_corner, steps)

    # Validate that final position doesn't overlap with reservoir
    _validate_no_overlap(final_position, new_droplet_shape, reservoir_droplet.origin_corner, reservoir_droplet.shape, logger)

    trajectory = _calculate_trajectory(reservoir_droplet.origin_corner, final_position)

    # 4. Generate frames for each step of the trajectory and create droplet
    actual_new_droplet_id = _generate_extraction_frames(
        new_plan, droplets, reservoir_droplet,
        reservoir_droplet.shape, new_droplet_shape, trajectory, new_droplet_id, halo_size, logger, existing_plan
    )

    # 5. Update active_droplets_per_frame for all frames based on frame content
    # Only consider droplets that were active in the original plan or the newly extracted droplet
    original_active_ids = set()
    if existing_plan and hasattr(existing_plan, 'active_droplets_per_frame') and existing_plan.active_droplets_per_frame:
        original_active_ids = set(existing_plan.active_droplets_per_frame[-1])

    allowed_active_ids = original_active_ids | {actual_new_droplet_id} | {reservoir_droplet.id}
    

    for i, frame in enumerate(new_plan.frames):
        active_from_frame = _compute_active_droplets_from_frame(frame, droplets, allowed_active_ids)
        if actual_new_droplet_id not in active_from_frame:
            active_from_frame.append(actual_new_droplet_id)
        new_plan.active_droplets_per_frame[i] = sorted(active_from_frame)

    # 6. Tag all frames with the extraction event
    event_id = next_event_id(new_plan)
    tag_frame_span(new_plan, 0, len(new_plan.frames), event_id, "1to2_extraction", 
                   {"reservoir_id": reservoir_droplet.id, "new_droplet_id": actual_new_droplet_id})

    # 7. Return updated droplets and plan
    logger.info(f"1-to-2 split completed: new droplet {actual_new_droplet_id} at {final_position}")
    return droplets.copy(), new_plan


def _split_1to3(
    droplets: List[Droplet],
    matrix: np.ndarray,
    reservoir_droplet: Droplet,
    steps: Tuple[int, int],
    split_size: Optional[Tuple[int, int]],
    new_droplet_id: Optional[int],
    logger,
    separation_steps: int,
    existing_plan: Optional[DropletPlan] = None
) -> Tuple[List[Droplet], DropletPlan]:
    """
    Execute 1-to-3 splitting protocol for reservoir extraction.

    This function splits a reservoir droplet into three parts: a central droplet that moves
    to a specified position, and two halves that temporarily separate and then recombine
    to form the remaining reservoir shape.

    Args:
        droplets: List of current droplets
        matrix: DMF chip matrix (0=free, 1=occupied, -1=forbidden)
        reservoir_droplet: The reservoir droplet to split from
        steps: (vertical_offset, horizontal_offset) for central droplet movement.
               First value affects row (vertical): negative = up/north, positive = down/south
               Second value affects column (horizontal): negative = left/west, positive = right/east
               Final position = central_position + steps
        split_size: Size of the central droplet as (height, width).
                   The droplet will be centered in the reservoir.
                   None = use default (1, 1)
        new_droplet_id: ID for the central droplet (None = auto-generate next available ID)
        halo_size: Size of unactivated electrode halo around droplets during movement
        logger: Logger instance for logging

    Returns:
        Tuple of (updated_droplets, new_droplet_plan)

    Raises:
        ValueError: If reservoir droplet not found, invalid parameters, or central position overlaps
    """
    logger.info(f"Executing 1-to-3 splitting for droplet {reservoir_droplet.id} with steps {steps}")

    # Create a new plan for the 1-to-3 split
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
    # Snapshot initial droplet ids so we can detect newly created droplets later
    initial_droplet_ids = {d.id for d in droplets}

    # Add initial frame with active droplets from existing plan (only keep active ones, don't reactivate all)
    matrix_shape = matrix.shape
    existing_active_ids = set()
    if existing_plan and existing_plan.active_droplets_per_frame:
        existing_active_ids = set(existing_plan.active_droplets_per_frame[-1])

    initial_frame = np.zeros(matrix_shape, dtype=np.int32)
    for droplet in droplets:
        if droplet.id in existing_active_ids:  # Only include currently active droplets
            positions = get_droplet_positions(droplet, droplet.origin_corner)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    initial_frame[x, y] = 1
    new_plan.frames.append(initial_frame)
    # Remove reservoir_droplet.id from existing_active_ids
    existing_active_ids.discard(reservoir_droplet.id)
    # Only pass droplets that are in active_droplet_ids to avoid computing active status for inactive droplets
    active_droplets_only = [d for d in droplets if d.id in existing_active_ids]
    new_plan.active_droplets_per_frame.append(_compute_active_droplets_from_frame(initial_frame, active_droplets_only))
    for droplet in droplets:
        new_plan.droplet_trajectories[droplet.id] = [droplet.origin_corner]

    # 1. Validate inputs
    _validate_1to2_inputs(steps, split_size, reservoir_droplet.shape, logger)

    # 2. Reservoir origin in absolute position
    rx, ry = reservoir_droplet.origin_corner

    # Reservoir relative bounds
    res_shape = reservoir_droplet.shape
    reservoir_top_row = 0
    reservoir_bottom_row = max(r for r, c in res_shape)
    reservoir_left_col = 0
    reservoir_right_col = max(c for r, c in res_shape)

    # 3. Calculate central shape
    if split_size is None:
        height, width = 1, 1
    else:
        height, width = split_size

    if height > reservoir_bottom_row + 1 or width > reservoir_right_col + 1:
        raise ValueError(f"Split size {split_size} is larger than reservoir dimensions {(reservoir_bottom_row + 1, reservoir_right_col + 1)}")

    # Center the droplet
    start_r = (reservoir_bottom_row + 1 - height) // 2
    start_c = (reservoir_right_col + 1 - width) // 2
    central_droplet_shape = set()
    for r in range(start_r, start_r + height):
        for c in range(start_c, start_c + width):
            if (r, c) in res_shape:
                central_droplet_shape.add((r, c))

    # Central relative corners
    central_top_row = min(r for r, c in central_droplet_shape)
    central_bottom_row = max(r for r, c in central_droplet_shape)
    central_left_col = min(c for r, c in central_droplet_shape)
    central_right_col = max(c for r, c in central_droplet_shape)

    # Determine split direction based on movement (perpendicular split)
    is_horizontal_movement = abs(steps[1]) >= abs(steps[0])

    #top left
    drop1_top_row = None
    drop1_bottom_row = None
    drop1_left_col = None
    drop1_right_col = None

    #center left
    drop2_top_row = None
    drop2_bottom_row = None
    drop2_left_col = None
    drop2_right_col = None

    #bottom left
    drop3_top_row = None
    drop3_bottom_row = None
    drop3_left_col = None
    drop3_right_col = None

    #top right
    drop4_top_row = None
    drop4_bottom_row = None
    drop4_left_col = None
    drop4_right_col = None

    #center top
    drop5_top_row = None
    drop5_bottom_row = None
    drop5_left_col = None
    drop5_right_col = None

    #center right
    drop6_top_row = None
    drop6_bottom_row = None
    drop6_left_col = None
    drop6_right_col = None

    # CAREFUL HERE; this coordinates are relative the the drop origin, that goes 0,0 from the top left
    # so is not the same reference system than the matrix coordinate system! 
    # top row is the minimun (0) while bottom is the maximun
    # left row is the minimun (0) while right col is the maximun
    if not is_horizontal_movement:
        #top left
        drop1_top_row = 0
        drop1_bottom_row = central_top_row - 1
        drop1_left_col = 0
        drop1_right_col = central_right_col

        #center left
        drop2_top_row = central_top_row
        drop2_bottom_row = central_bottom_row
        drop2_left_col = 0
        drop2_right_col = central_left_col - 1

        #bottom left
        drop3_top_row = central_bottom_row + 1
        drop3_bottom_row = reservoir_bottom_row
        drop3_left_col = 0
        drop3_right_col = central_left_col - 1

        #top right
        drop4_top_row = 0
        drop4_bottom_row = central_top_row - 1
        drop4_left_col = drop1_right_col + 1
        drop4_right_col = reservoir_right_col

        #center right
        drop5_top_row = central_top_row
        drop5_bottom_row = central_bottom_row
        drop5_left_col = central_right_col + 1
        drop5_right_col = reservoir_right_col

        #bottom right
        drop6_top_row = drop5_bottom_row + 1
        drop6_bottom_row = reservoir_bottom_row
        drop6_left_col = central_left_col
        drop6_right_col = reservoir_right_col

    else:  # vertical movement
        #top left
        drop1_top_row = 0
        drop1_bottom_row = central_top_row - 1
        drop1_left_col = 0
        drop1_right_col = central_left_col - 1

        #center top
        drop2_top_row = 0
        drop2_bottom_row = central_top_row - 1
        drop2_left_col = central_left_col
        drop2_right_col = central_right_col

        #top right
        drop3_top_row = 0
        drop3_bottom_row = central_bottom_row
        drop3_left_col = central_right_col + 1
        drop3_right_col = reservoir_right_col

        #bottom left
        drop4_top_row = central_top_row
        drop4_bottom_row = reservoir_bottom_row
        drop4_left_col = 0
        drop4_right_col = central_left_col - 1

        #center bottom
        drop5_top_row = central_bottom_row + 1
        drop5_bottom_row = reservoir_bottom_row
        drop5_left_col = central_left_col
        drop5_right_col = central_right_col

        #bottom right
        drop6_top_row = central_bottom_row + 1
        drop6_bottom_row = reservoir_bottom_row
        drop6_left_col = central_right_col + 1
        drop6_right_col = reservoir_right_col

    # Add the new droplets and a frame; reservoir needs to go inactive. new droplets are active.
    # Calculate the origin corner of each new droplet by taking the min row (x) and min column (y) from the previous lines
    # Calculate the shape of each droplet with for loops using min and max columns and rows from the previous code

    # Define the 6 drop bounds
    drop_bounds = [
        (drop1_top_row, drop1_bottom_row, drop1_left_col, drop1_right_col),
        (drop2_top_row, drop2_bottom_row, drop2_left_col, drop2_right_col),
        (drop3_top_row, drop3_bottom_row, drop3_left_col, drop3_right_col),
        (drop4_top_row, drop4_bottom_row, drop4_left_col, drop4_right_col),
        (drop5_top_row, drop5_bottom_row, drop5_left_col, drop5_right_col),
        (drop6_top_row, drop6_bottom_row, drop6_left_col, drop6_right_col),
    ]

    new_droplets = []
    for i, (min_row, max_row, min_col, max_col) in enumerate(drop_bounds):
        # Calculate the shape of each droplet: only include electrodes that were in the original reservoir
        shape = set()
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                if (r, c) in res_shape:
                    shape.add((r, c))

        # Calculate the origin corner of each new droplet by taking the min row (x) and min column (y)
        origin_corner = (rx + min_row, ry + min_col)
        normalized_shape = {(r - min_row, c - min_col) for r, c in shape}

        # Assign droplet ID
        if new_droplet_id is not None and i == 0:
            droplet_id = new_droplet_id
        else:
            existing_ids = {d.id for d in droplets + new_droplets}
            droplet_id = max(existing_ids) + 1 if existing_ids else 1
        # Create new droplet
        new_droplet = create_droplet(
            droplet_id=droplet_id,
            origin=origin_corner,
            target=origin_corner,  # Stay in place initially
            shape=normalized_shape,
            priority=reservoir_droplet.priority,
            vital_space=reservoir_droplet.vital_space
        )
        new_droplets.append(new_droplet)
        new_plan.droplet_trajectories[droplet_id] = [origin_corner]

    # Add the central droplet as the 7th
    central_origin_corner = (rx + central_top_row, ry + central_left_col)
    central_normalized_shape = {(r - central_top_row, c - central_left_col) for r, c in central_droplet_shape}
    central_final_pos = _add_position_offset(reservoir_droplet.origin_corner, steps);

    # Assign ID for central
    existing_ids = {d.id for d in droplets + new_droplets}
    central_id = new_droplet_id if new_droplet_id is not None and not new_droplets else max(existing_ids) + 1 if existing_ids else 1

    central_droplet = create_droplet(
        droplet_id=central_id,
        origin=central_origin_corner,
        target=central_final_pos,
        shape=central_normalized_shape,
        priority=reservoir_droplet.priority,
        vital_space=reservoir_droplet.vital_space
    )

    new_droplets.append(central_droplet)
    new_plan.droplet_trajectories[central_id] = [central_origin_corner]

    # Add new droplets to the list
    droplets.extend(new_droplets)

    # Create a new frame with reservoir inactive and new droplets active
    matrix_shape = new_plan.frames[0].shape
    new_frame = np.zeros(matrix_shape, dtype=np.int32)
    for droplet in new_droplets:
        positions = get_droplet_positions(droplet, droplet.origin_corner)
        for x, y in positions:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                new_frame[x, y] = 1

    _add_existing_active_droplets_to_frame(new_frame, droplets, existing_active_ids, matrix_shape)

    new_plan.frames.append(new_frame)
    # Reservoir remains inactive during separation - only new droplets and existing active droplets
    new_plan.active_droplets_per_frame.append(list(existing_active_ids) + [d.id for d in new_droplets])
    new_plan.frame_count = len(new_plan.frames)

    logger.info(f"ACTIVE DROPLETS {new_plan.active_droplets_per_frame}")

    # Extend other trajectories to match the new frame count
    _extend_other_trajectories(new_plan, droplets)

    # Now move separation_steps positions left droplets 1 and 3, and separation_steps steps right droplets 4 and 6, one step at a time
    # The rest of the droplets should keep active and at their same positions!
    for step in range(separation_steps):
        # Calculate new positions for moving droplets
        new_positions = []
        for i, droplet in enumerate(new_droplets):
            if not is_horizontal_movement:
                if i == 0 or i == 2:  # droplets 1 and 3: move left (decrease column)
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] - 1)
                elif i == 3 or i == 5:  # droplets 4 and 6: move right (increase column)
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] + 1)
                else:  # droplets 2 and 5: stay at same position
                    new_pos = droplet.origin_corner
            else:
                if i == 0 or i == 2:  # droplets 1 and 3: move down (dencrease row)
                    new_pos = (droplet.origin_corner[0] - 1, droplet.origin_corner[1])
                elif i == 3 or i == 5:  # droplets 4 and 6: move up (increase row)
                    new_pos = (droplet.origin_corner[0] + 1, droplet.origin_corner[1])
                else:  # droplets 2 and 5: stay at same position
                    new_pos = droplet.origin_corner
            
            new_positions.append(new_pos)

        # Create a new frame with updated positions
        new_frame = np.zeros(matrix_shape, dtype=np.int32)
        for droplet, pos in zip(new_droplets, new_positions):
            positions = get_droplet_positions(droplet, pos)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    new_frame[x, y] = 1

        _add_existing_active_droplets_to_frame(new_frame, droplets, existing_active_ids, matrix_shape)

        new_plan.frames.append(new_frame)
        new_plan.active_droplets_per_frame.append(list(existing_active_ids) + [d.id for d in new_droplets])

        # Update droplet positions
        for droplet, pos in zip(new_droplets, new_positions):
            droplet.origin_corner = pos

        new_plan.frame_count = len(new_plan.frames)

    # Update trajectories: calculate step-by-step for separation_steps for moving droplets only
    extended_bounds = drop_bounds + [(central_top_row, central_bottom_row, central_left_col, central_right_col)]
    for i, (min_row, max_row, min_col, max_col) in enumerate(extended_bounds):
        start_pos = (rx + min_row, ry + min_col)
        if i in [0, 2, 3, 5]:  # Moving droplets 1,3,4,6
            trajectory = [start_pos]
            if not is_horizontal_movement:
                if i in [0, 2]:  # Left moving
                    dir_x, dir_y = 0, -1
                elif i in [3, 5]:  # Right moving
                    dir_x, dir_y = 0, 1
            else:
                if i in [0, 2]:  # Down moving
                    dir_x, dir_y = -1, 0
                elif i in [3, 5]:  # Up moving
                    dir_x, dir_y = 1, 0
            for _ in range(separation_steps):
                next_pos = (trajectory[-1][0] + dir_x, trajectory[-1][1] + dir_y)
                trajectory.append(next_pos)
            new_plan.droplet_trajectories[new_droplets[i].id] = trajectory
        # Non-moving droplets (2,5, central) do not get trajectories assigned

    # Capture starting positions for trajectory calculation
    start_positions_2_5 = [new_droplets[i].origin_corner for i in [1, 4]]

    # Next step: move central droplet
    for step in range(separation_steps):
        # Calculate new positions for moving droplets 2 and 5
        new_positions = []
        for i, droplet in enumerate(new_droplets):
            if not is_horizontal_movement:
                if i == 1:  # droplet 2: move left
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] - 1)
                elif i == 4:  # droplet 5: move right
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] + 1)
                else:  # others stay
                    new_pos = droplet.origin_corner
            else:
                if i == 1:  # droplet 2: move down
                    new_pos = (droplet.origin_corner[0]-1, droplet.origin_corner[1])
                elif i == 4:  # droplet 5: move up
                    new_pos = (droplet.origin_corner[0]+1, droplet.origin_corner[1])
                else:  # others stay
                    new_pos = droplet.origin_corner


            new_positions.append(new_pos)

        # Create a new frame with updated positions
        new_frame = np.zeros(matrix_shape, dtype=np.int32)
        for droplet, pos in zip(new_droplets, new_positions):
            positions = get_droplet_positions(droplet, pos)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    new_frame[x, y] = 1

        _add_existing_active_droplets_to_frame(new_frame, droplets, existing_active_ids, matrix_shape)

        new_plan.frames.append(new_frame)
        new_plan.active_droplets_per_frame.append(list(existing_active_ids) + [d.id for d in new_droplets])

        # Update droplet positions
        for droplet, pos in zip(new_droplets, new_positions):
            droplet.origin_corner = pos

        new_plan.frame_count = len(new_plan.frames)

    # Update trajectories for the newly moving droplets 2 and 5
    for idx, i in enumerate([1, 4]):  # droplets 2 and 5
        start_pos = start_positions_2_5[idx]
        trajectory = [start_pos] * new_plan.frame_count  # Previous frames at start position
        if not is_horizontal_movement:
            dir_x, dir_y = (0, -1) if i == 1 else (0, 1)  # left for 2, right for 5
        else:
            dir_x, dir_y = (-1, 0) if i == 1 else (1, 0)  # down for 2, up for 5
        current_pos = start_pos
        for _ in range(separation_steps):
            current_pos = (current_pos[0] + dir_x, current_pos[1] + dir_y)
            trajectory.append(current_pos)
        new_plan.droplet_trajectories[new_droplets[i].id] = trajectory

    # Extend all trajectories to match the new frame count (11)
    for droplet_id, trajectory in new_plan.droplet_trajectories.items():
        final_position = trajectory[-1] if trajectory else (0, 0)
        while len(trajectory) < new_plan.frame_count:
            trajectory.append(final_position)

    # Extend reservoir trajectory
    _extend_other_trajectories(new_plan, [reservoir_droplet])

    # Next step: move the central droplet orthogonally to the previous direction, up to the boundary, then additional steps
    central_droplet = new_droplets[6]
    current_pos = central_droplet.origin_corner

    # adjust direction
    if not is_horizontal_movement:
        # Vertical movement
        dir_row = 1 if steps[0] > 0 else -1
        dir_col = 0
        amount = abs(steps[0])
    else:
        # Horizontal movement
        dir_row = 0
        dir_col =  1 if steps[1] > 0 else -1
        amount = abs(steps[1])

    # Calculate distance to boundary in the orthogonal direction
    distance = 0
    if dir_row > 0:  # moving down
        distance = reservoir_bottom_row - central_bottom_row
    elif dir_row < 0:  # moving up
        distance = central_top_row - reservoir_top_row
    elif dir_col > 0:  # moving right
        distance = reservoir_right_col - central_right_col
    elif dir_col < 0:  # moving left
        distance = central_left_col - reservoir_left_col

    total_steps = distance + amount

    # Initialize trajectory for the central droplet
    trajectory = [current_pos] * new_plan.frame_count  # Previous frames at initial position

    # Move the central droplet for total_steps
    for step in range(total_steps):
        # Calculate new position
        new_pos = (current_pos[0] + dir_row, current_pos[1] + dir_col)
        current_pos = new_pos
        central_droplet.origin_corner = new_pos

        # Add to trajectory
        trajectory.append(new_pos)

        # Create a new frame with updated central position
        new_frame = np.zeros(matrix_shape, dtype=np.int32)
        for droplet in new_droplets:
            pos = droplet.origin_corner
            positions = get_droplet_positions(droplet, pos)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    new_frame[x, y] = 1

        _add_existing_active_droplets_to_frame(new_frame, droplets, existing_active_ids, matrix_shape)

        new_plan.frames.append(new_frame)
        # Reservoir becomes inactive after split - only new droplets and existing active droplets remain
        new_plan.active_droplets_per_frame.append(list(existing_active_ids) + [d.id for d in new_droplets])
        new_plan.frame_count = len(new_plan.frames)

    # Set the trajectory
    new_plan.droplet_trajectories[central_droplet.id] = trajectory

    # Update droplet target positions to match their final positions
    for droplet in new_droplets:
        if droplet.id in new_plan.droplet_trajectories and new_plan.droplet_trajectories[droplet.id]:
            final_pos = new_plan.droplet_trajectories[droplet.id][-1]
            droplet.target_corner = final_pos
            droplet.origin_corner = final_pos

    # Now bring back droplets 1-6 to their original positions, reversing their movements
    # Do not reverse the central droplet's movement

    # First, reverse the movement of droplets 2 and 5
    for step in range(separation_steps):
        new_positions = []
        for i, droplet in enumerate(new_droplets):
            if not is_horizontal_movement:
                if i == 1:  # droplet 2: was moved left, so move right to come back
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] + 1)
                elif i == 4:  # droplet 5: was moved right, so move left to come back
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] - 1)
                else:
                    new_pos = droplet.origin_corner
            else:
                if i == 1:  # droplet 2: move down
                    new_pos = (droplet.origin_corner[0]+1, droplet.origin_corner[1])
                elif i == 4:  # droplet 5: move up
                    new_pos = (droplet.origin_corner[0]-1, droplet.origin_corner[1])
                else:  # others stay
                    new_pos = droplet.origin_corner

            new_positions.append(new_pos)


        # Create a new frame
        new_frame = np.zeros(matrix_shape, dtype=np.int32)
        for droplet, pos in zip(new_droplets, new_positions):
            positions = get_droplet_positions(droplet, pos)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    new_frame[x, y] = 1

        _add_existing_active_droplets_to_frame(new_frame, droplets, existing_active_ids, matrix_shape)

        new_plan.frames.append(new_frame)
        new_plan.active_droplets_per_frame.append(list(existing_active_ids) + [d.id for d in new_droplets])

        # Update droplet positions and trajectories
        for i, (droplet, pos) in enumerate(zip(new_droplets, new_positions)):
            droplet.origin_corner = pos
            if i in [1, 4]:  # moving droplets
                droplet_id = droplet.id
                if droplet_id in new_plan.droplet_trajectories:
                    new_plan.droplet_trajectories[droplet_id].append(pos)

        new_plan.frame_count = len(new_plan.frames)


    # Finally, reverse the initial separation of droplets 1,3,4,6
    for step in range(separation_steps):
        new_positions = []
        for i, droplet in enumerate(new_droplets):
            if not is_horizontal_movement:
                if i == 0 or i == 2:  # 1 and 3: were moved left, so move right
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] + 1)
                elif i == 3 or i == 5:  # 4 and 6: were moved right, so move left
                    new_pos = (droplet.origin_corner[0], droplet.origin_corner[1] - 1)
                else:
                    new_pos = droplet.origin_corner
            else:
                if i == 0 or i == 2:  # droplets 1 and 3: move down (dencrease row)
                    new_pos = (droplet.origin_corner[0] + 1, droplet.origin_corner[1])
                elif i == 3 or i == 5:  # droplets 4 and 6: move up (increase row)
                    new_pos = (droplet.origin_corner[0] - 1, droplet.origin_corner[1])
                else:  # droplets 2 and 5: stay at same position
                    new_pos = droplet.origin_corner

            new_positions.append(new_pos)

        # Create a new frame
        new_frame = np.zeros(matrix_shape, dtype=np.int32)
        for droplet, pos in zip(new_droplets, new_positions):
            positions = get_droplet_positions(droplet, pos)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    new_frame[x, y] = 1

        _add_existing_active_droplets_to_frame(new_frame, droplets, existing_active_ids, matrix_shape)

        new_plan.frames.append(new_frame)
        new_plan.active_droplets_per_frame.append(list(existing_active_ids) + [d.id for d in new_droplets])

        # Update droplet positions and trajectories
        for i, (droplet, pos) in enumerate(zip(new_droplets, new_positions)):
            droplet.origin_corner = pos
            if i in [0, 2, 3, 5]:  # moving droplets
                droplet_id = droplet.id
                if droplet_id in new_plan.droplet_trajectories:
                    new_plan.droplet_trajectories[droplet_id].append(pos)

        new_plan.frame_count = len(new_plan.frames)

    # Final step: deactivate droplets 1-6, activate reservoir with original shape minus central, keep central active
    # Calculate the reservoir shape as the union of droplets 1-6 shapes at their current positions
    reservoir_shape = set()
    for i in range(6):  # droplets 0 to 5 (1-6)
        droplet = new_droplets[i]
        abs_positions = get_droplet_positions(droplet, droplet.origin_corner)
        reservoir_shape.update(abs_positions)

    # Convert to relative coordinates for reservoir_droplet
    rx, ry = reservoir_droplet.origin_corner
    relative_reservoir_shape = {(x - rx, y - ry) for x, y in reservoir_shape}

    # Update reservoir shape
    reservoir_droplet.shape = relative_reservoir_shape

    # Relax the reservoir shape as in 1to2
    relax_droplet_shape(reservoir_droplet, new_plan, droplets, logger)

    # After relaxation, the last frame has the relaxed reservoir
    # But we need to add the central droplet and any existing active droplets to it
    if new_plan.frames:
        final_frame = new_plan.frames[-1].copy()
        # Add central droplet positions to the relaxed reservoir frame
        central_positions = get_droplet_positions(new_droplets[6], new_droplets[6].origin_corner)
        for x, y in central_positions:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                final_frame[x, y] = 1

        # Add positions of existing active droplets
        existing_active_ids = set()
        if existing_plan and existing_plan.active_droplets_per_frame:
            existing_active_ids = set(existing_plan.active_droplets_per_frame[-1])
        for droplet in droplets:
            if droplet.id in existing_active_ids and droplet.id != reservoir_droplet.id:
                positions = get_droplet_positions(droplet, droplet.origin_corner)
                for x, y in positions:
                    if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                        final_frame[x, y] = 1

        # Update the last frame
        new_plan.frames[-1] = final_frame
        # Update active droplets: existing active + central + reservoir
        existing_active_list = list(existing_active_ids) if existing_active_ids else []
        new_plan.active_droplets_per_frame[-1] = existing_active_list + [new_droplets[6].id, reservoir_droplet.id]
    
    # Extend all trajectories to match the new frame count
    for droplet_id, traj in new_plan.droplet_trajectories.items():
        final_position = traj[-1] if traj else (0, 0)
        while len(traj) < new_plan.frame_count:
            traj.append(final_position)

    # Extend reservoir trajectory
    _extend_other_trajectories(new_plan, [reservoir_droplet])

    # Recompute active_droplets_per_frame for every frame but only allow original active droplets
    # plus any newly created droplets (so we don't reactivate unrelated droplets).
    original_active_ids = set()
    if existing_plan and existing_plan.active_droplets_per_frame:
        original_active_ids = set(existing_plan.active_droplets_per_frame[-1])

    # Ensure reservoir id is not considered active
    original_active_ids.discard(reservoir_droplet.id)

    # Newly created droplets are those not present in the initial snapshot
    new_created_ids = {d.id for d in droplets} - initial_droplet_ids

    # Only allow the central droplet (the one that was moved away) to be active in the final frames.
    # This prevents auxiliary droplets 1-6 from being considered active just because their
    # electrode positions match the reactivated reservoir electrodes.
    central_id = None
    try:
        # central droplet was appended as the last element in new_droplets list (index 6)
        central_id = new_droplets[6].id
    except Exception:
        # Fallback: if for some reason new_droplets layout changed, choose any id in new_created_ids
        central_id = (next(iter(new_created_ids)) if new_created_ids else None)

    allowed_active_ids = original_active_ids | ({central_id} if central_id is not None else set())

    # Ensure active_droplets_per_frame has same length as frames
    while len(new_plan.active_droplets_per_frame) < len(new_plan.frames):
        new_plan.active_droplets_per_frame.append([])

    for i, frame in enumerate(new_plan.frames):
        active_from_frame = _compute_active_droplets_from_frame(frame, droplets, allowed_active_ids)
        new_plan.active_droplets_per_frame[i] = sorted(active_from_frame)

    # Now add the reservoir droplet !just at the end!
    new_plan.active_droplets_per_frame[-1].append(reservoir_droplet.id)

    return droplets.copy(), new_plan

@dataclass
class LinearConfig:
    drops_number: int          # total number of drops to create
    space_per_row: int           # electrode pitch between rows (orthogonal to sweep)
    space_per_col: int        # electrode pitch between columns (along sweep)
    offset: int = 0    # starting offset from the reservoir
    drop_shape: Union[Tuple[int,int], Set[Tuple[int,int]]] = (1,1)
    direction: Tuple[int,int] = (1,0)


def _validate_linear_cfg(cfg: LinearConfig, logger) -> None:
    """Validate the linear configuration parameters."""
    if cfg.drops_number <= 0:
        raise ValueError("drops_number must be a positive integer.")
    if cfg.space_per_row <= 0:
        raise ValueError("space_per_row must be a positive integer.")
    if cfg.space_per_col <= 0:
        raise ValueError("space_per_col must be a positive integer.")
    if not (isinstance(cfg.drop_shape, tuple) or isinstance(cfg.drop_shape, set)):
        raise ValueError("drop_shape must be either a tuple (height, width) or a set of (row, col) offsets.")
    if isinstance(cfg.drop_shape, tuple):
        if len(cfg.drop_shape) != 2 or not all(isinstance(x, int) and x > 0 for x in cfg.drop_shape):
            raise ValueError("If drop_shape is a tuple, it must be of the form (height, width) with positive integers.")
    if not (isinstance(cfg.direction, tuple) and len(cfg.direction) == 2 and all(isinstance(x, int) for x in cfg.direction)):
        raise ValueError("direction must be a tuple of two integers (row_direction, column_direction).")

    logger.debug("LinearConfig validated successfully.")


def _split_linear(
    droplets: List[Droplet],
    matrix: np.ndarray,
    reservoir_droplet: Droplet,
    cfg: LinearConfig,
    new_droplet_id: Optional[int],
    logger,
    existing_plan: Optional[DropletPlan] = None
) -> Tuple[List[Droplet], DropletPlan]:
    """Create a serpentine linear sweep that pins, necks and severs droplets from a reservoir.

    This is a simplified but functional implementation of the 'linear' protocol described in the spec.
    It keeps the reservoir active throughout the sweep, creates droplets at the sever frame and
    relaxes the reservoir at the end.
    """
    # Validate cfg
    _validate_linear_cfg(cfg, logger)

    # Create new plan
    new_plan = DropletPlan(
        frames=[], frame_count=0, droplet_trajectories={}, active_droplets_per_frame=[],
        events=[], planning_success=True, conflicts_resolved=[], targets_reached={}, event_id_per_frame=[]
    )

    # Matrix shape
    matrix_shape = None
    if existing_plan and existing_plan.frames:
        matrix_shape = existing_plan.frames[0].shape
    else:
        matrix_shape = matrix.shape

    # Initial frame: reservoir active and existing active droplets
    existing_active_ids = set()
    if existing_plan and existing_plan.active_droplets_per_frame:
        existing_active_ids = set(existing_plan.active_droplets_per_frame[-1])

    initial_frame = np.zeros(matrix_shape, dtype=np.int32)
    # Reservoir stays active throughout
    res_positions = get_droplet_positions(reservoir_droplet, reservoir_droplet.origin_corner)
    # Snapshot original reservoir absolute positions for validation later
    original_reservoir_positions = set(res_positions)
    for x, y in res_positions:
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            initial_frame[x, y] = 1

    # Add other existing active droplets
    for droplet in droplets:
        if droplet.id in existing_active_ids and droplet.id != reservoir_droplet.id:
            for x, y in get_droplet_positions(droplet, droplet.origin_corner):
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    initial_frame[x, y] = 1

    new_plan.frames.append(initial_frame)
    new_plan.active_droplets_per_frame.append(sorted(list(existing_active_ids | {reservoir_droplet.id})))

    # Initialize trajectories for droplets present
    for droplet in droplets:
        new_plan.droplet_trajectories[droplet.id] = [droplet.origin_corner]

    # first create droplets. To do so:
    # Create initial dropelt. Check the movement direction: 
    # if its right, then the initial droplet origin is top left of the reservoir shape is the defined one in the argument
    # if its left, then the initial droplet origin is top right of the reservoir shape is the defined one in the argument
    # if its down, then the initial droplet origin is top left of the reservoir shape is the defined one in the argument
    # if its up, then the initial droplet origin is bottom left of the reservoir shape is the defined one in the argument 

    if cfg.direction[1] > 0:  # moving right
        initial_droplet_origin = (
            reservoir_droplet.origin_corner[0],
            reservoir_droplet.origin_corner[1]
        )
    elif cfg.direction[1] < 0:  # moving left
        if isinstance(cfg.drop_shape, tuple):
            drop_width = cfg.drop_shape[1]
        else:
            drop_width = max(dy for dx, dy in cfg.drop_shape) + 1
        initial_droplet_origin = (
            reservoir_droplet.origin_corner[0],
            reservoir_droplet.origin_corner[1] - drop_width + 1
        )

    elif cfg.direction[0] > 0:  # moving down
        initial_droplet_origin = (
            reservoir_droplet.origin_corner[0],
            reservoir_droplet.origin_corner[1]
        )
    elif cfg.direction[0] < 0:  # moving up
        initial_droplet_origin = (
            reservoir_droplet.origin_corner[0],
            reservoir_droplet.origin_corner[1]
        )

    # Create the rest of the droplets.
    # if moving right or left, move along rows first, then columns
    # if moving up or down, move along columns first, then rows
    # we move accross the reservoir shape to create droplets, and attending to the space_per_row and space_per_col. if a droplet doesnt fit (including its shape), we move to the next row/column
    created_droplets = 0
    droplet_id_counter = max((d.id for d in droplets), default=0) + 1
    current_origin = list(initial_droplet_origin)
    column_row_counter = 0  # to track when to apply offset
    while created_droplets < cfg.drops_number:
        # Create droplet shape
        if isinstance(cfg.drop_shape, tuple):
            drop_height, drop_width = cfg.drop_shape
            drop_shape = {(r, c) for r in range(drop_height) for c in range(drop_width)}
        else:
            drop_shape = cfg.drop_shape
        
        # Create droplet
        new_droplet = create_droplet(
            droplet_id=droplet_id_counter,
            origin=tuple(current_origin),
            target=tuple(current_origin),
            shape=drop_shape,
            priority=reservoir_droplet.priority,
            vital_space=reservoir_droplet.vital_space
        )
        droplets.append(new_droplet)
        new_plan.droplet_trajectories[new_droplet.id] = [new_droplet.origin_corner]
        created_droplets += 1
        droplet_id_counter += 1

        # Update origin for next droplet
        if cfg.direction[1] != 0:  # moving right or left
            # Move along rows first
            current_origin[0] += drop_height + cfg.space_per_row
            # Check if fits in reservoir vertically
            res_top_row, res_bottom_row, res_left_col, res_right_col = get_droplet_bounds(reservoir_droplet, reservoir_droplet.origin_corner)

            offset_applied = 0
            if (column_row_counter) % 2 == 1:
                offset_applied = cfg.offset

            if current_origin[0] + drop_height + offset_applied > res_bottom_row + 1:
                # Move to next column
                column_row_counter += 1
                current_origin[0] = initial_droplet_origin[0]
                # if column is odd, we add the offset to the starting row
                if column_row_counter % 2 == 1:
                    current_origin[0] += cfg.offset   
                current_origin[1] += (drop_width + cfg.space_per_col) * (1 if cfg.direction[1] > 0 else -1)
        else:  # moving up or down
            # Move along columns first
            current_origin[1] += drop_width + cfg.space_per_col
            # Check if fits in reservoir horizontally
            res_top_row, res_bottom_row, res_left_col, res_right_col = get_droplet_bounds(reservoir_droplet, reservoir_droplet.origin_corner)

            offset_applied = 0
            if (column_row_counter) % 2 == 1:
                offset_applied = cfg.offset

            if current_origin[1] + drop_width + offset_applied > res_right_col + 1:
                
                # Move to next row
                column_row_counter += 1
                current_origin[1] = initial_droplet_origin[1]
                # if row is odd, we add the offset to the starting column
                if column_row_counter % 2 == 1:
                    current_origin[1] += cfg.offset

                current_origin[0] += (drop_height + cfg.space_per_row) * (1 if cfg.direction[0] > 0 else -1)


    # Now generate frames for the extraction of each droplet sequentially.
    # To do so, the reservoir is the one that needs to move to in the direction of the droplet's trajectory frame by frame. It will end the movement when the last droplets has gone out of the reservoir by a distance of at least equal to space_per_col or space_per_row depending on the movement direction
    
    created_droplets_list = droplets[-created_droplets:]  # the created droplets
    
    # Determine which created droplets are initially active (fully contained in reservoir)
    activated = set()
    for d in created_droplets_list:
        d_positions = get_droplet_positions(d, d.origin_corner)
        if set(d_positions).issubset(res_positions):
            activated.add(d.id)
    
    active_created = [d for d in created_droplets_list if d.id in activated]
    
    # Update initial frame and active droplets to include initially active created droplets
    for d in active_created:
        d_positions = get_droplet_positions(d, d.origin_corner)
        for x, y in d_positions:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                new_plan.frames[0][x, y] = 1
    
    initial_active = existing_active_ids | {reservoir_droplet.id} | {d.id for d in active_created}
    new_plan.active_droplets_per_frame[0] = sorted(initial_active)
    
    # Get reservoir bounds
    res_top_row, res_bottom_row, res_left_col, res_right_col = get_droplet_bounds(reservoir_droplet, reservoir_droplet.origin_corner)
    
    # Direction
    dir_row, dir_col = cfg.direction
    
    # Current reservoir position
    current_res_pos = reservoir_droplet.origin_corner
    current_res_left = res_left_col
    current_res_right = res_right_col
    current_res_top = res_top_row
    current_res_bottom = res_bottom_row
    
    # Severed droplets
    severed = set()
    
    # Move until all are severed
    electrodes_out = set()
    max_steps = 100
    for step in range(max_steps):
        # Update activated droplets: check if any new ones are now fully contained
        for d in created_droplets_list:
            if d.id not in activated:
                d_positions = get_droplet_positions(d, d.origin_corner)
                if set(d_positions).issubset(res_positions):
                    activated.add(d.id)
        
        active_created = [d for d in created_droplets_list if d.id in activated]
        
        # Create frame
        frame = np.zeros(matrix_shape, dtype=np.int32)
        
        # Add reservoir
        res_positions = get_droplet_positions(reservoir_droplet, current_res_pos)
        for x, y in res_positions:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                frame[x, y] = 1
        
        # Add existing active droplets
        for d in droplets:
            if d.id in existing_active_ids and d.id != reservoir_droplet.id:
                d_positions = get_droplet_positions(d, d.origin_corner)
                for x, y in d_positions:
                    if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                        frame[x, y] = 1
        
        # Add active created droplets
        for d in active_created:
            d_positions = get_droplet_positions(d, d.origin_corner)
            for x, y in d_positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    frame[x, y] = 1
            
            # Check if severed AND count new electrodes out from original reservoir
            new_electrodes_out = 0
            severed_this = False
            if dir_col > 0:  # moving right
                d_right = d.origin_corner[1] + max((dy for dx, dy in d.shape), default=0)
                # check how many new electrodes are out (more left than the leftmost electrode of the reservoir)
                for x, y in d_positions:
                    if y <= current_res_left and (x, y) not in electrodes_out:
                        new_electrodes_out += 1
                        electrodes_out.add((x, y))
                if current_res_left > d_right + cfg.space_per_col:
                    severed_this = True
            elif dir_col < 0:  # moving left
                d_left = d.origin_corner[1]
                for x, y in d_positions:
                    if y <= current_res_right and (x, y) not in electrodes_out:
                        new_electrodes_out += 1
                        electrodes_out.add((x, y))
                if current_res_right < d_left - cfg.space_per_col:
                    severed_this = True
            elif dir_row > 0:  # moving down
                d_bottom = d.origin_corner[0] + max((dx for dx, dy in d.shape), default=0)
                for x, y in d_positions:
                    if x <= current_res_top  and (x, y) not in electrodes_out:
                        electrodes_out.add((x, y))
                        new_electrodes_out += 1
                if current_res_top > d_bottom + cfg.space_per_row:
                    severed_this = True
            elif dir_row < 0:  # moving up
                d_top = d.origin_corner[0]
                for x, y in d_positions:
                    if x >= current_res_bottom and (x, y) not in electrodes_out:
                        electrodes_out.add((x, y))
                        new_electrodes_out += 1
                if current_res_bottom < d_top - cfg.space_per_row:
                    severed_this = True
            
            if severed_this and d.id in activated:
                severed.add(d.id)
                d_positions = get_droplet_positions(d, d.origin_corner)
                for x, y in d_positions:
                    if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                        frame[x, y] = 1
            
            if new_electrodes_out > 0:
                # we identify the two corners in the sense of position
                if dir_row > 0:
                    # we are moving down
                    corner_0 = (current_res_bottom, current_res_left)
                    corner_1 = (current_res_bottom, current_res_right)

                    # we sort all current reservoir electrodes in two lists in the following way
                    # first all electrodes from the bottom row, sorted by the distance to corner_0 (left to right) in one list and corner_1 in the other.
                    # then the electrodes in next row, and so on until the top row
                    list_0 = []
                    list_1 = []
                    for r in range(current_res_bottom, current_res_top -1, -1):
                        row_electrodes = [(x, y) for x, y in res_positions if x == r]
                        row_electrodes_sorted_0 = sorted(row_electrodes, key=lambda pos: abs(pos[1] - corner_0[1]))
                        row_electrodes_sorted_1 = sorted(row_electrodes, key=lambda pos: abs(pos[1] - corner_1[1]))
                        list_0.extend(row_electrodes_sorted_0)
                        list_1.extend(row_electrodes_sorted_1)

                    # now we remove one electrode from the reservoir shape from list_0 and list_1 each until we have removed new_electrodes_out electrodes
                    last_list = 0
                    last_1_index = 0
                    last_0_index = 0
                    for i in range(new_electrodes_out):
                        if i < len(list_0) and last_list == 1:
                            pos_to_remove = list_0[last_0_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 0
                            last_0_index += 1
                        elif i < len(list_1) and last_list == 0:
                            pos_to_remove = list_1[last_1_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 1
                            last_1_index += 1
                
                elif dir_row < 0:
                    # we are moving up
                    corner_0 = (current_res_top, current_res_left)
                    corner_1 = (current_res_top, current_res_right)

                    # sort from top to bottom
                    list_0 = []
                    list_1 = []
                    for r in range(current_res_top, current_res_bottom + 1):
                        row_electrodes = [(x, y) for x, y in res_positions if x == r]
                        row_electrodes_sorted_0 = sorted(row_electrodes, key=lambda pos: abs(pos[1] - corner_0[1]))
                        row_electrodes_sorted_1 = sorted(row_electrodes, key=lambda pos: abs(pos[1] - corner_1[1]))
                    list_0.extend(row_electrodes_sorted_0)
                    list_1.extend(row_electrodes_sorted_1)
                    
                    last_list = 0
                    last_1_index = 0
                    last_0_index = 0
                    for i in range(new_electrodes_out):
                        if i < len(list_0) and last_list == 1:
                            pos_to_remove = list_0[last_0_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 0
                            last_0_index += 1
                        elif i < len(list_1) and last_list == 0:
                            pos_to_remove = list_1[last_1_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 1
                            last_1_index += 1

                elif dir_col > 0:
                    # we are moving right
                    corner_0 = (current_res_top, current_res_right)
                    corner_1 = (current_res_bottom, current_res_right)

                    # sort from right to left
                    list_0 = []
                    list_1 = []
                    for c in range(current_res_right, current_res_left - 1, -1):
                        col_electrodes = [(x, y) for x, y in res_positions if y == c]
                        col_electrodes_sorted_0 = sorted(col_electrodes, key=lambda pos: abs(pos[0] - corner_0[0]))
                        col_electrodes_sorted_1 = sorted(col_electrodes, key=lambda pos: abs(pos[0] - corner_1[0]))
                        list_0.extend(col_electrodes_sorted_0)
                        list_1.extend(col_electrodes_sorted_1)
                    
                    last_list = 0
                    last_1_index = 0
                    last_0_index = 0
                    for i in range(new_electrodes_out):
                        if i < len(list_0) and last_list == 1:
                            pos_to_remove = list_0[last_0_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 0
                            last_0_index += 1
                        elif i < len(list_1) and last_list == 0:
                            pos_to_remove = list_1[last_1_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 1
                            last_1_index += 1
                
                elif dir_col < 0:
                    # we are moving left
                    corner_0 = (current_res_top, current_res_left)
                    corner_1 = (current_res_bottom, current_res_left)

                    # sort from left to right
                    list_0 = []
                    list_1 = []
                    for c in range(current_res_left, current_res_right + 1):
                        col_electrodes = [(x, y) for x, y in res_positions if y == c]
                        col_electrodes_sorted_0 = sorted(col_electrodes, key=lambda pos: abs(pos[0] - corner_0[0]))
                        col_electrodes_sorted_1 = sorted(col_electrodes, key=lambda pos: abs(pos[0] - corner_1[0]))
                        list_0.extend(col_electrodes_sorted_0)
                        list_1.extend(col_electrodes_sorted_1)
                    
                    last_list = 0
                    last_1_index = 0
                    last_0_index = 0
                    for i in range(new_electrodes_out):
                        if i < len(list_0) and last_list == 1:
                            pos_to_remove = list_0[last_0_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 0
                            last_0_index += 1
                        elif i < len(list_1) and last_list == 0:
                            pos_to_remove = list_1[last_1_index]
                            if pos_to_remove in res_positions:
                                res_positions.remove(pos_to_remove)
                            last_list = 1
                            last_1_index += 1

                # Update reservoir shape to relative coordinates after trimming
                reservoir_droplet.shape = {(x - current_res_pos[0], y - current_res_pos[1]) for x, y in res_positions}


        new_plan.frames.append(frame)
        active_ids = existing_active_ids | {reservoir_droplet.id} | {d.id for d in active_created}
        new_plan.active_droplets_per_frame.append(sorted(active_ids))
        
        # Update trajectories
        new_plan.droplet_trajectories[reservoir_droplet.id].append(current_res_pos)
        for d in created_droplets_list:
            new_plan.droplet_trajectories[d.id].append(d.origin_corner)
        
        # If all severed, break
        if len(severed) == len(created_droplets_list):
            break
        
        # Move reservoir
        current_res_pos = (current_res_pos[0] + dir_row, current_res_pos[1] + dir_col)
        current_res_left += dir_col
        current_res_right += dir_col
        current_res_top += dir_row
        current_res_bottom += dir_row

    # Update reservoir origin_corner and target_corner to match its final position from trajectory
    if reservoir_droplet.id in new_plan.droplet_trajectories and new_plan.droplet_trajectories[reservoir_droplet.id]:
        final_corner = new_plan.droplet_trajectories[reservoir_droplet.id][-1]
        reservoir_droplet.origin_corner = final_corner
        reservoir_droplet.target_corner = final_corner

    # for debug, print the length of all trajectories of created droplets (including reservoir) and the length of frames
    # for d in created_droplets_list + [reservoir_droplet]:
    #     logger.info(f"Droplet ID {d.id} trajectory length: {len(new_plan.droplet_trajectories[d.id])}")
    # logger.info(f"Total frames generated: {len(new_plan.frames)}")
    return droplets.copy(), new_plan
# =============================================================================
# CORE HELPERS (Mid-level operations)
# =============================================================================

def get_droplet_bounds(droplet: Droplet, origin_corner: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """
    Get the bounding box of a droplet at the given origin corner.
    
    Returns:
        Tuple of (min_row, max_row, min_col, max_col)
    """
    positions = get_droplet_positions(droplet, origin_corner)
    if not positions:
        return 0, 0, 0, 0
    rows = [p[0] for p in positions]
    cols = [p[1] for p in positions]
    return min(rows), max(rows), min(cols), max(cols)

def _compute_active_droplets_from_frame(frame_matrix: np.ndarray, droplets: List[Droplet], allowed_active_ids: Optional[Set[int]] = None) -> List[int]:
    """
    Compute which droplets are active in a frame based on electrode activation.

    A droplet is considered active if it has at least one electrode set to 1 in the frame.
    If allowed_active_ids is provided, only droplets with IDs in this set can be considered active.

    Args:
        frame_matrix: The frame matrix (rows x cols)
        droplets: List of all droplets
        allowed_active_ids: Optional set of droplet IDs that are allowed to be active.
                           If None, all droplets can be considered active.

    Returns:
        List of active droplet IDs
    """
    active_ids = []
    for droplet in droplets:
        # Skip droplets that are not in the allowed active set (if specified)
        if allowed_active_ids is not None and droplet.id not in allowed_active_ids:
            continue

        # Get the droplet's current position (from its origin_corner)
        pos = droplet.origin_corner
        body_positions = get_droplet_positions(droplet, pos)

        # Check if any body position is activated (value == 1) in the frame
        has_activation = any(
            0 <= x < frame_matrix.shape[0] and 0 <= y < frame_matrix.shape[1] and frame_matrix[x, y] == 1
            for x, y in body_positions
        )

        if has_activation:
            active_ids.append(droplet.id)

    return sorted(active_ids)

def _generate_extraction_frames(
    new_plan: DropletPlan,
    droplets: List[Droplet],
    reservoir_droplet: Droplet,
    updated_reservoir_shape: Set[Tuple[int, int]],
    new_droplet_shape: Set[Tuple[int, int]],
    trajectory: List[Tuple[int, int]],
    new_droplet_id: Optional[int],
    halo_size: int,
    logger,
    existing_plan: Optional[DropletPlan] = None
) -> int:
    """Generate frame matrices for the extraction process with proper layering."""
    # Get matrix dimensions
    matrix_shape = new_plan.frames[0].shape if new_plan.frames else (128, 128)

    # Normalize the split shape so (0,0) is included for proper path visualization
    # The visualizer draws paths from the corner position, so we want (0,0) to represent the main reference point
   
    if new_droplet_shape:
        # Find the minimum coordinates in the shape to use as offset
        min_dx = min(dx for dx, dy in new_droplet_shape)
        min_dy = min(dy for dx, dy in new_droplet_shape)

        # Adjust the shape so (0,0) is included
        normalized_shape = {(dx - min_dx, dy - min_dy) for dx, dy in new_droplet_shape}

        # Adjust trajectory positions to account for the shape offset
        adjusted_trajectory = [(pos[0] + min_dx, pos[1] + min_dy) for pos in trajectory]
    else:
        normalized_shape = new_droplet_shape
        adjusted_trajectory = trajectory

    # Create new droplet temporarily for frame generation
    actual_new_droplet_id = _create_split_droplet(
        droplets, new_plan, normalized_shape, adjusted_trajectory[0], adjusted_trajectory[-1], reservoir_droplet.id, new_droplet_id, logger, reservoir_droplet.vital_space
    )
    new_droplet = next((d for d in droplets if d.id == actual_new_droplet_id), None)
    if not new_droplet:
        logger.error(f"New droplet {actual_new_droplet_id} not found")
        return

    # Generate frames for each trajectory step
    for step, position in enumerate(adjusted_trajectory):
        frame_matrix = _create_extraction_frame(
            new_plan, reservoir_droplet, updated_reservoir_shape,
            new_droplet, position, halo_size, matrix_shape, logger
        )
        new_plan.frames.append(frame_matrix)

        # Update active droplets for this frame - only consider droplets that were active in the original plan
        # or the newly extracted droplet
        original_active_ids = set()
        if existing_plan and hasattr(existing_plan, 'active_droplets_per_frame') and existing_plan.active_droplets_per_frame:
            original_active_ids = set(existing_plan.active_droplets_per_frame[-1])

        allowed_active_ids = original_active_ids | {actual_new_droplet_id}
        active_droplets = _compute_active_droplets_from_frame(frame_matrix, droplets, allowed_active_ids)
        new_plan.active_droplets_per_frame.append(sorted(active_droplets))

        # Update trajectory
        if actual_new_droplet_id not in new_plan.droplet_trajectories:
            new_plan.droplet_trajectories[actual_new_droplet_id] = []
        new_plan.droplet_trajectories[actual_new_droplet_id].append(position)

        # Update the new droplet's origin_corner to the final position
        new_droplet.origin_corner = position

    # Update frame count and extend other trajectories
    new_plan.frame_count = len(new_plan.frames)
    _extend_other_trajectories(new_plan, droplets)

    # Ensure reservoir trajectory exists
    if reservoir_droplet.id not in new_plan.droplet_trajectories:
        new_plan.droplet_trajectories[reservoir_droplet.id] = [reservoir_droplet.origin_corner]
    _extend_other_trajectories(new_plan, [reservoir_droplet])

    # Add final steady-state frame.
    # Important: only paint droplets that should be active in this extraction context.
    # Painting all droplet objects can reintroduce inactive droplets as ghost activations.
    allowed_active_ids_for_final = original_active_ids | {actual_new_droplet_id, reservoir_droplet.id}
    final_frame = _create_final_extraction_frame(
        droplets,
        reservoir_droplet,
        matrix_shape,
        allowed_active_ids=allowed_active_ids_for_final,
    )
    new_plan.frames.append(final_frame)
    # For the final frame, only consider droplets that were active in the original plan
    # or the newly extracted droplet
    original_active_ids = set()
    if existing_plan and hasattr(existing_plan, 'active_droplets_per_frame') and existing_plan.active_droplets_per_frame:
        original_active_ids = set(existing_plan.active_droplets_per_frame[-1])

    allowed_active_ids = allowed_active_ids_for_final
    final_active_droplets = _compute_active_droplets_from_frame(final_frame, droplets, allowed_active_ids)
    new_plan.active_droplets_per_frame.append(sorted(final_active_droplets))
    new_plan.frame_count = len(new_plan.frames)

    # Extend all trajectories to match frame count
    for droplet_id, trajectory in new_plan.droplet_trajectories.items():
        # Find the droplet's final position (either current or from trajectory)
        final_position = trajectory[-1] if trajectory else (0, 0)  # fallback
        while len(trajectory) < new_plan.frame_count:
            trajectory.append(final_position)

    return actual_new_droplet_id

def _validate_1to2_inputs(steps: Tuple[int, int], split_size: Optional[Union[Tuple[int, int], Set[Tuple[int, int]]]], reservoir_shape: Set[Tuple[int, int]], logger) -> None:
    """Validate inputs for 1-to-2 splitting."""
    # Validate steps is a tuple of two integers
    if not isinstance(steps, tuple) or len(steps) != 2 or not all(isinstance(x, int) for x in steps):
        logger.error(f"Invalid steps '{steps}'. Must be a tuple of two integers (x, y)")
        raise ValueError(f"Invalid steps '{steps}'. Must be a tuple of two integers (x, y)")

    if split_size is None:
        pass  # Default will be handled later
    elif isinstance(split_size, tuple):
        # Validate tuple
        if len(split_size) != 2 or not all(isinstance(x, int) and x > 0 for x in split_size):
            logger.error(f"Invalid split_size '{split_size}'. Must be a tuple of two positive integers (height, width)")
            raise ValueError(f"Invalid split_size '{split_size}'. Must be a tuple of two positive integers (height, width)")
    elif isinstance(split_size, set):
        # Validate set of tuples
        if not all(isinstance(coord, tuple) and len(coord) == 2 and all(isinstance(x, int) for x in coord) for coord in split_size):
            logger.error(f"Invalid split_size '{split_size}'. Must be a set of (row, col) tuples")
            raise ValueError(f"Invalid split_size '{split_size}'. Must be a set of (row, col) tuples")
    else:
        logger.error(f"Invalid split_size type '{type(split_size)}'. Must be tuple or set")
        raise ValueError(f"Invalid split_size type '{type(split_size)}'. Must be tuple or set")

def _trim_reservoir_shape_based_on_created_droplets(
    reservoir_droplet: Droplet,
    created_positions_union: Set[Tuple[int, int]],
    already_removed: Set[Tuple[int, int]],
    dr_sign: int,
    dc_sign: int,
    logger
) -> None:
    """
    Trim the reservoir shape based on created droplets outside the previous bounding box.
    
    This creates a flat boundary on the movement-opposing side by removing electrodes
    from the two corners in the direction opposite to movement.
    
    Args:
        reservoir_droplet: The reservoir droplet to trim
        created_positions_union: All positions of created droplets so far
        already_removed: Positions already removed to avoid double removal
        dr_sign: Direction sign for rows (1=down, -1=up, 0=no vertical movement)
        dc_sign: Direction sign for columns (1=right, -1=left, 0=no horizontal movement)
        logger: Logger instance
    """
    # Determine previous reservoir bounding box
    prev_origin = reservoir_droplet.origin_corner
    prev_res_positions = set(get_droplet_positions(reservoir_droplet, prev_origin))
    if prev_res_positions:
        prev_rows = [p[0] for p in prev_res_positions]
        prev_cols = [p[1] for p in prev_res_positions]
        prev_min_row, prev_max_row = min(prev_rows), max(prev_rows)
        prev_min_col, prev_max_col = min(prev_cols), max(prev_cols)
    else:
        prev_min_row = prev_max_row = prev_min_col = prev_max_col = 0

    # Find created electrodes outside previous bbox
    extras_outside_bbox = set()
    for pos in created_positions_union:
        if pos in already_removed:
            continue
        if (pos[0] < prev_min_row or pos[0] > prev_max_row or
            pos[1] < prev_min_col or pos[1] > prev_max_col):
            extras_outside_bbox.add(pos)

    removed_count = len(extras_outside_bbox)


    if removed_count > 0:
        # Get current reservoir relative positions
        rel_positions = {(x - reservoir_droplet.origin_corner[0], y - reservoir_droplet.origin_corner[1]) 
                        for x, y in get_droplet_positions(reservoir_droplet, reservoir_droplet.origin_corner)}
        if rel_positions:
            rel_rows = [p[0] for p in rel_positions]
            rel_cols = [p[1] for p in rel_positions]
            rel_min_row = min(rel_rows) if rel_rows else 0
            rel_max_row = max(rel_rows) if rel_rows else 0
            rel_min_col = min(rel_cols) if rel_cols else 0
            rel_max_col = max(rel_cols) if rel_cols else 0
        else:
            rel_min_row = rel_max_row = rel_min_col = rel_max_col = 0

        # Trim from movement-opposing side
        new_shape = set(reservoir_droplet.shape)

        if dr_sign != 0:  # Vertical movement
            if dr_sign > 0:  # Moving down -> trim from bottom
                corners_to_trim_row = rel_max_row
                corner_1 = (corners_to_trim_row, rel_min_col)
                corner_2 = (corners_to_trim_row, rel_max_col)
            else:  # Moving up -> trim from top
                corners_to_trim_row = rel_min_row
                corner_1 = (corners_to_trim_row, rel_min_col)
                corner_2 = (corners_to_trim_row, rel_max_col)
                
            shape_list_1 = [(x, y) for x, y in reservoir_droplet.shape]
            shape_list_2 = [(x, y) for x, y in reservoir_droplet.shape]

            for pos in shape_list_1:
                ordered_list_1 = []
                # first create a list of ordered rows from distance to the electron row
                # all rows
                rows_relevance = [i for i in range(rel_min_row, rel_max_row + 1)]
                rows_relevance.sort(key=lambda i: abs(i - corner_1[0]))
                # now from each row, get all electrodes in that row and sort them by column distance to corner_1
                for row in rows_relevance:
                    electrodes_in_row = [p for p in shape_list_1 if p[0] == row]
                    electrodes_in_row.sort(key=lambda p: abs(p[1] - corner_1[1]))
                    ordered_list_1.extend(electrodes_in_row)

            for pos in shape_list_2:
                ordered_list_2 = []
                # first create a list of ordered rows from distance to the electron row
                # all rows
                rows_relevance = [i for i in range(rel_min_row, rel_max_row + 1)]
                rows_relevance.sort(key=lambda i: abs(i - corner_2[0]))
                # now from each row, get all electrodes in that row and sort them by column distance to corner_2
                for row in rows_relevance:
                    electrodes_in_row = [p for p in shape_list_2 if p[0] == row]
                    electrodes_in_row.sort(key=lambda p: abs(p[1] - corner_2[1]))
                    ordered_list_2.extend(electrodes_in_row)

            shape_list_1 = ordered_list_1
            shape_list_2 = ordered_list_2


            last_removed_from_list = 1
            for i in range(removed_count):
                if last_removed_from_list == 1 and shape_list_1:
                    to_remove = shape_list_1.pop(0)
                    while to_remove not in new_shape and shape_list_1:
                        to_remove = shape_list_1.pop(0)
                    new_shape.discard(to_remove)
                    last_removed_from_list = 2
                elif last_removed_from_list == 2 and shape_list_2:
                    to_remove = shape_list_2.pop(0)
                    while to_remove not in new_shape and shape_list_2:
                        to_remove = shape_list_2.pop(0)
                    new_shape.discard(to_remove)
                    last_removed_from_list = 1
                    
        elif dc_sign != 0:  # Horizontal movement
            if dc_sign > 0:  # Moving right -> trim from right
                corners_to_trim_col = rel_max_col
                corner_1 = (rel_min_row, corners_to_trim_col)
                corner_2 = (rel_max_row, corners_to_trim_col)
            else:  # Moving left -> trim from left
                corners_to_trim_col = rel_min_col
                corner_1 = (rel_min_row, corners_to_trim_col)
                corner_2 = (rel_max_row, corners_to_trim_col)
                
            shape_list_1 = [(x, y) for x, y in reservoir_droplet.shape]
            shape_list_2 = [(x, y) for x, y in reservoir_droplet.shape]

            for pos in shape_list_1:
                ordered_list_1 = []
                # first create a list of ordered columns from distance to the electron column
                # all columns
                columns_relevance = [j for j in range(rel_min_col, rel_max_col + 1)]
                columns_relevance.sort(key=lambda j: abs(j - corner_1[1]))
                # now from each column, get all electrodes in that column and sort them by row distance to corner_1
                for col in columns_relevance:
                    electrodes_in_col = [p for p in shape_list_1 if p[1] == col]
                    electrodes_in_col.sort(key=lambda p: abs(p[0] - corner_1[0]))
                    ordered_list_1.extend(electrodes_in_col)

            for pos in shape_list_2:
                ordered_list_2 = []
                # first create a list of ordered columns from distance to the electron column
                # all columns
                columns_relevance = [j for j in range(rel_min_col, rel_max_col + 1)]
                columns_relevance.sort(key=lambda j: abs(j - corner_2[1]))
                # now from each column, get all electrodes in that column and sort them by row distance to corner_2
                for col in columns_relevance:
                    electrodes_in_col = [p for p in shape_list_2 if p[1] == col]
                    electrodes_in_col.sort(key=lambda p: abs(p[0] - corner_2[0]))
                    ordered_list_2.extend(electrodes_in_col)


            shape_list_1 = ordered_list_1
            shape_list_2 = ordered_list_2

            last_removed_from_list = 1
            for i in range(removed_count):
                if last_removed_from_list == 1 and shape_list_1:
                    to_remove = shape_list_1.pop(0)
                    while to_remove not in new_shape and shape_list_1:
                        to_remove = shape_list_1.pop(0)
                    new_shape.discard(to_remove)
                    last_removed_from_list = 2
                elif last_removed_from_list == 2 and shape_list_2:
                    to_remove = shape_list_2.pop(0)
                    while to_remove not in new_shape and shape_list_2:
                        to_remove = shape_list_2.pop(0)
                    new_shape.discard(to_remove)
                    last_removed_from_list = 1



        # Update reservoir shape
        reservoir_droplet.shape = new_shape
        
        # Adjust origin if needed
        rel_positions_after = {(x, y) for x, y in reservoir_droplet.shape}
        if rel_positions_after:
            rel_rows_after = [p[0] for p in rel_positions_after]
            rel_cols_after = [p[1] for p in rel_positions_after]
            new_rel_min_row = min(rel_rows_after) if rel_rows_after else 0
            new_rel_max_row = max(rel_rows_after) if rel_rows_after else 0
            new_rel_min_col = min(rel_cols_after) if rel_cols_after else 0
            new_rel_max_col = max(rel_cols_after) if rel_cols_after else 0
            
            if new_rel_min_row != 0 or new_rel_min_col != 0:
                reservoir_droplet.origin_corner = (
                    reservoir_droplet.origin_corner[0] + new_rel_min_row,
                    reservoir_droplet.origin_corner[1] + new_rel_min_col
                )
                # Shift shape to new origin
                reservoir_droplet.shape = {(x - new_rel_min_row, y - new_rel_min_col) for x, y in reservoir_droplet.shape}

    # Mark removed positions
    already_removed.update(extras_outside_bbox)

def _validate_isometric_inputs(steps: List[Tuple[int, int]], logger) -> None:
    """Validate inputs for isometric splitting."""
    # Validate steps is a list of tuples of two integers
    if not isinstance(steps, list):
        logger.error(f"Invalid steps '{steps}'. Must be a list of (x, y) tuples")
        raise ValueError(f"Invalid steps '{steps}'. Must be a list of (x, y) tuples")
    
    if not steps:
        logger.error("Steps list cannot be empty")
        raise ValueError("Steps list cannot be empty")
    
    for i, step in enumerate(steps):
        if not isinstance(step, tuple) or len(step) != 2 or not all(isinstance(x, int) for x in step):
            logger.error(f"Invalid step at index {i}: '{step}'. Must be a tuple of two integers (x, y)")
            raise ValueError(f"Invalid step at index {i}: '{step}'. Must be a tuple of two integers (x, y)")

def _validate_no_overlap(final_position: Tuple[int, int], new_droplet_shape: Set[Tuple[int, int]],
                        reservoir_corner: Tuple[int, int], updated_reservoir_shape: Set[Tuple[int, int]], logger) -> None:
    """Validate that the new droplet doesn't overlap with the updated reservoir."""
    # Calculate absolute positions for new droplet
    new_droplet_positions = {(final_position[0] + dx, final_position[1] + dy) for dx, dy in new_droplet_shape}

    # Calculate absolute positions for updated reservoir
    reservoir_positions = {(reservoir_corner[0] + dx, reservoir_corner[1] + dy) for dx, dy in updated_reservoir_shape}

    # Check for overlap
    overlap = new_droplet_positions & reservoir_positions
    if overlap:
        logger.error(f"Final position would cause overlap with reservoir. Overlapping positions: {overlap}")
        raise ValueError(f"Final position {final_position} with shape {new_droplet_shape} would overlap with reservoir at positions: {list(overlap)}")


def _add_position_offset(base_position: Tuple[int, int], offset: Tuple[int, int]) -> Tuple[int, int]:
    """Add positional offset to a base position."""
    rx, ry = base_position  # rx = row, ry = column
    vertical_offset, horizontal_offset = offset  # First value = vertical (rows), second = horizontal (columns)
    return (rx + vertical_offset, ry + horizontal_offset)  # Direct: vertical affects rows, horizontal affects columns


def _assign_shapes_to_directions(
    sub_shapes: List[Set[Tuple[int, int]]],
    final_positions: List[Tuple[int, int]],
    pos_direction: Tuple[int, int],
    neg_direction: Tuple[int, int],
    logger
) -> Tuple[List[Set[Tuple[int, int]]], List[Tuple[int, int]]]:
    """
    Assign sub-shapes to final positions based on spatial relationship to movement direction.

    For horizontal movement (dx != 0):
    - Sub-shape with smaller column values goes to negative dx (left)
    - Sub-shape with larger column values goes to positive dx (right)

    For vertical movement (dy != 0):
    - Sub-shape with smaller row values goes to negative dy (up)
    - Sub-shape with larger row values goes to positive dy (down)
    """
    dx, dy = pos_direction

    if dx != 0:  # Horizontal movement
        # Sort sub-shapes by their minimum column value (leftmost position)
        sorted_shapes_with_pos = []
        for shape in sub_shapes:
            min_col = min(col for row, col in shape)
            sorted_shapes_with_pos.append((min_col, shape))

        # Sort by column position: smaller column = left, larger column = right
        sorted_shapes_with_pos.sort(key=lambda x: x[0])

        # Assign: left shape goes to negative direction (left), right shape goes to positive direction (right)
        left_shape = sorted_shapes_with_pos[0][1]
        right_shape = sorted_shapes_with_pos[1][1]

        # Final positions: [pos_direction, neg_direction]
        # For horizontal: pos_direction is right, neg_direction is left
        assigned_shapes = [right_shape, left_shape]  # right shape goes right, left shape goes left
        # Reorder final_positions to match shape assignments: [pos_direction, neg_direction]
        assigned_positions = [final_positions[0], final_positions[1]]

    elif dy != 0:  # Vertical movement
        # Sort sub-shapes by their minimum row value (topmost position)
        sorted_shapes_with_pos = []
        for shape in sub_shapes:
            min_row = min(row for row, col in shape)
            sorted_shapes_with_pos.append((min_row, shape))

        # Sort by row position: smaller row = top, larger row = bottom
        sorted_shapes_with_pos.sort(key=lambda x: x[0])

        # Assign: top shape goes to negative direction (up), bottom shape goes to positive direction (down)
        top_shape = sorted_shapes_with_pos[0][1]
        bottom_shape = sorted_shapes_with_pos[1][1]

        # Final positions: [pos_direction, neg_direction]
        # For vertical: pos_direction is down, neg_direction is up
        assigned_shapes = [bottom_shape, top_shape]  # bottom shape goes down, top shape goes up
        # Reorder final_positions to match shape assignments: [pos_direction, neg_direction]
        assigned_positions = [final_positions[0], final_positions[1]]

    else:
        # This shouldn't happen as we validate steps, but fallback to original order
        logger.warning("Invalid direction for shape assignment, using original order")
        assigned_shapes = sub_shapes
        assigned_positions = final_positions

    logger.debug(f"Assigned shapes to directions: pos_dir={pos_direction}, neg_dir={neg_direction}")
    return assigned_shapes, assigned_positions


def _split_shape_equally(shape: Set[Tuple[int, int]], num_parts: int, dx: int = 0, dy: int = 0, logger=None) -> List[Set[Tuple[int, int]]]:
    """Split a droplet shape into equal rectangular parts, maintaining coherence."""
    electrodes = list(shape)
    num_electrodes = len(electrodes)

    # Calculate required size per part
    if num_electrodes % num_parts != 0:
        logger.warning(f"Cannot split {num_electrodes} electrodes evenly into {num_parts} parts")
        return []

    electrodes_per_part = num_electrodes // num_parts

    # Get bounding box
    rows = {r for r, c in electrodes}
    cols = {c for r, c in electrodes}
    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)

    height = max_row - min_row + 1
    width = max_col - min_col + 1

    # Try to find rectangular splits
    sub_shapes = []

    if num_parts == 2:
        # Prefer splitting in the direction of movement
        split_attempts = []

        # If moving horizontally (dx != 0), try vertical split first
        if dx != 0:
            split_attempts.append(("vertical", width > 1 and height * (width // 2) == electrodes_per_part))
        # If moving vertically (dy != 0), try horizontal split first
        elif dy != 0:
            split_attempts.append(("horizontal", height > 1 and width * (height // 2) == electrodes_per_part))
        else:
            # No movement direction specified, try both
            split_attempts = [
                ("horizontal", height > 1 and width * (height // 2) == electrodes_per_part),
                ("vertical", width > 1 and height * (width // 2) == electrodes_per_part)
            ]

        for split_type, can_split in split_attempts:
            if can_split:
                if split_type == "horizontal":
                    split_row = min_row + height // 2
                    top_shape = {(r, c) for r, c in electrodes if r < split_row}
                    bottom_shape = {(r, c) for r, c in electrodes if r >= split_row}

                    if len(top_shape) == electrodes_per_part and len(bottom_shape) == electrodes_per_part:
                        sub_shapes = [top_shape, bottom_shape]
                        logger.debug(f"Split {width}x{height} rectangle horizontally into {len(sub_shapes)} parts")
                        return sub_shapes
                elif split_type == "vertical":
                    split_col = min_col + width // 2
                    left_shape = {(r, c) for r, c in electrodes if c < split_col}
                    right_shape = {(r, c) for r, c in electrodes if c >= split_col}

                    if len(left_shape) == electrodes_per_part and len(right_shape) == electrodes_per_part:
                        sub_shapes = [left_shape, right_shape]
                        logger.debug(f"Split {width}x{height} rectangle vertically into {len(sub_shapes)} parts")
                        return sub_shapes

    # If we can't find a rectangular split, warn and return empty
    logger.warning(f"Cannot split shape into {num_parts} coherent rectangular parts. Shape must be splittable into equal rectangles.")
    return []


def _calculate_trajectory(start_pos: Tuple[int, int], end_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
    """Calculate discrete step trajectory from start to end position."""
    sx, sy = start_pos
    ex, ey = end_pos

    # Calculate the differences
    dx = ex - sx
    dy = ey - sy

    # If no movement needed, just return start and end
    if dx == 0 and dy == 0:
        return [start_pos, end_pos]

    # Calculate number of steps as the maximum of |dx| and |dy|
    steps = max(abs(dx), abs(dy))

    trajectory = [start_pos]

    for step in range(1, steps + 1):
        # Interpolate position based on step
        x = sx + (dx * step) // steps
        y = sy + (dy * step) // steps
        trajectory.append((x, y))

    # Ensure end position is included
    if trajectory[-1] != end_pos:
        trajectory.append(end_pos)

    return trajectory


def _create_extraction_frame(
    new_plan: DropletPlan,
    reservoir_droplet: Droplet,
    updated_reservoir_shape: Set[Tuple[int, int]],
    new_droplet: Droplet,
    new_droplet_position: Tuple[int, int],
    halo_size: int,
    matrix_shape: Tuple[int, int],
    logger
) -> np.ndarray:
    """Create a single frame for the extraction process with proper layering."""
    # Start with the last frame from new_plan (input matrix)
    if new_plan.frames:
        frame_matrix = new_plan.frames[-1].copy()
    else:
        frame_matrix = np.zeros(matrix_shape, dtype=np.int32)

    # 1. Ensure all reservoir electrodes are 1 (not counting the droplet being taken out)
    # Clear any existing reservoir positions first
    old_reservoir_positions = get_droplet_positions(reservoir_droplet, reservoir_droplet.origin_corner)
    for x, y in old_reservoir_positions:
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            frame_matrix[x, y] = 0  # Clear old positions

    # Set updated reservoir positions (excluding the split portion)
    for dx, dy in updated_reservoir_shape:
        rx, ry = reservoir_droplet.origin_corner
        x, y = rx + dx, ry + dy
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            frame_matrix[x, y] = 1


    # switch off any old droplet positions (in case of overlap with halo)
    old_droplet_positions = get_droplet_positions(new_droplet, new_droplet.origin_corner)
    for x, y in old_droplet_positions:
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            frame_matrix[x, y] = 0  # Clear old positions

    # 2. Switch halo electrodes to 0, but only for reservoir positions
    halo_positions = _calculate_droplet_halo_positions(new_droplet_position, new_droplet.shape, halo_size, matrix_shape)
    reservoir_positions = {(reservoir_droplet.origin_corner[0] + dx, reservoir_droplet.origin_corner[1] + dy) for dx, dy in updated_reservoir_shape}
    for x, y in halo_positions:
        if (x, y) in reservoir_positions:
            frame_matrix[x, y] = 0

    # 3. Set up droplet electrodes to 1 (calculated differently for each frame based on trajectory)
    droplet_positions = get_droplet_positions(new_droplet, new_droplet_position)
    for x, y in droplet_positions:
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            frame_matrix[x, y] = 1

    return frame_matrix


def _calculate_droplet_halo_positions(
    position: Tuple[int, int],
    droplet_shape: Set[Tuple[int, int]],
    halo_size: int,
    matrix_shape: Tuple[int, int]
) -> Set[Tuple[int, int]]:
    """Calculate halo positions around a droplet at given position."""
    halo_positions = set()

    # Include the droplet's own positions
    for dx, dy in droplet_shape:
        x, y = position[0] + dx, position[1] + dy
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            halo_positions.add((x, y))

    # Add halo_size extra electrodes in periphery
    for dx, dy in droplet_shape:
        droplet_x, droplet_y = position[0] + dx, position[1] + dy
        for hx in range(-halo_size, halo_size + 1):
            for hy in range(-halo_size, halo_size + 1):
                if not (hx == 0 and hy == 0):  # Don't include the electrode itself again
                    halo_x, halo_y = droplet_x + hx, droplet_y + hy
                    if 0 <= halo_x < matrix_shape[0] and 0 <= halo_y < matrix_shape[1]:
                        halo_positions.add((halo_x, halo_y))

    return halo_positions


def _create_final_extraction_frame(
    droplets: List[Droplet],
    reservoir_droplet: Droplet,
    matrix_shape: Tuple[int, int],
    allowed_active_ids: Optional[Set[int]] = None,
) -> np.ndarray:
    
    """Create final steady-state frame with all droplets in final positions."""
    final_frame = np.zeros(matrix_shape, dtype=np.int32)
    for droplet in droplets:
        if allowed_active_ids is not None and droplet.id not in allowed_active_ids:
            continue
        positions = get_droplet_positions(droplet, droplet.origin_corner)
        for x, y in positions:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                final_frame[x, y] = 1
    return final_frame


def _add_existing_active_droplets_to_frame(frame: np.ndarray, droplets: List[Droplet], existing_active_ids: set, matrix_shape: Tuple[int, int]) -> None:
    """Add positions of existing active droplets to a frame."""
    for droplet in droplets:
        if droplet.id in existing_active_ids:
            positions = get_droplet_positions(droplet, droplet.origin_corner)
            for x, y in positions:
                if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                    frame[x, y] = 1


def _extend_other_trajectories(new_plan: DropletPlan, droplets: List[Droplet]) -> None:
    """Extend trajectories of other droplets to match frame count."""
    for droplet in droplets:
        if droplet.id in new_plan.droplet_trajectories:
            trajectory = new_plan.droplet_trajectories[droplet.id]
            final_position = droplet.origin_corner
            while len(trajectory) < new_plan.frame_count:
                trajectory.append(final_position)


def _generate_isometric_split_step(
    droplets: List[Droplet],
    new_plan: DropletPlan,
    source_droplet: Droplet,
    sub_shapes: List[Set[Tuple[int, int]]],
    final_positions: List[Tuple[int, int]],
    simultaneous: bool,
    new_droplet_id: Optional[int],
    logger
) -> Tuple[List[Droplet], DropletPlan]:
    """
    Generate frames for a single isometric splitting step.

    This creates the split frame and movement frames for one splitting operation.
    """
    matrix_shape = new_plan.frames[0].shape if new_plan.frames else (128, 128)

    # Create new subdroplets
    sub_droplets = []
    sub_droplet_ids = []

    for i, (sub_shape, final_pos) in enumerate(zip(sub_shapes, final_positions)):
        # Generate ID for this subdroplet
        if i == 0 and new_droplet_id is not None:
            droplet_id = new_droplet_id
        else:
            existing_ids = {d.id for d in droplets + sub_droplets}
            droplet_id = max(existing_ids) + 1 if existing_ids else 1

        # Normalize the sub_shape and calculate origin offset
        if sub_shape:
            min_dx = min(dx for dx, dy in sub_shape)
            min_dy = min(dy for dx, dy in sub_shape)
            normalized_shape = {(dx - min_dx, dy - min_dy) for dx, dy in sub_shape}
            sub_origin = (source_droplet.origin_corner[0] + min_dx, source_droplet.origin_corner[1] + min_dy)
        else:
            normalized_shape = sub_shape
            min_dx = 0
            min_dy = 0
            sub_origin = source_droplet.origin_corner

        # Create subdroplet at its relative position
        sub_droplet = create_droplet(
            droplet_id=droplet_id,
            origin=sub_origin,  # Start at relative position within parent
            target=final_pos,  # Target is final position
            shape=normalized_shape,  # Use normalized shape with (0,0) as reference
            priority=source_droplet.priority,
            vital_space=source_droplet.vital_space
        )
        sub_droplets.append(sub_droplet)
        sub_droplet_ids.append(droplet_id)

        # Initialize trajectory at subdroplet's origin position
        # If trajectory already exists (from previous steps), continue it; otherwise start new
        current_position = sub_origin
        if droplet_id not in new_plan.droplet_trajectories:
            new_plan.droplet_trajectories[droplet_id] = [current_position]
        # Note: If trajectory already exists, we continue from the last position

        logger.debug(f"Created subdroplet {droplet_id} with {len(sub_shape)} electrodes")

    # Add subdroplets to the main list
    droplets.extend(sub_droplets)

    # Create initial split frame: source droplet splits into subdroplets at their relative positions
    split_frame = _create_split_frame_at_positions(new_plan, source_droplet, sub_droplets, [sub_droplet.origin_corner for sub_droplet in sub_droplets], matrix_shape, logger)
    new_plan.frames.append(split_frame)

    # Source droplet becomes inactive; new subdroplets stay active alongside
    # any unrelated droplets that were already active in the previous frame.
    other_active_droplets = [
        active_id
        for active_id in new_plan.active_droplets_per_frame[-1]
        if active_id != source_droplet.id and active_id not in sub_droplet_ids
    ]
    active_droplets = sub_droplet_ids + other_active_droplets
    new_plan.active_droplets_per_frame.append(active_droplets)

    # Update trajectories for split frame (each at their origin position initially)
    for sub_droplet in sub_droplets:
        new_plan.droplet_trajectories[sub_droplet.id].append(sub_droplet.origin_corner)

    # Keep the original source droplet in the list but mark it as inactive
    # The source droplet remains in the droplets list but is not active in the plan
    # This allows the JSON logging to show all droplets

    # Generate movement frames
    if simultaneous:
        # Generate simultaneous trajectories from each subdroplet's origin
        trajectories = _generate_simultaneous_trajectories_from_origins(
            [sub_droplet.origin_corner for sub_droplet in sub_droplets], final_positions, logger
        )

        # Generate frames for each movement step (skip the first trajectory which is the split position)
        for step, positions in enumerate(trajectories[1:], 1):  # Start from index 1
            frame_matrix = _create_isometric_frame(
                new_plan, None, sub_droplets, positions, matrix_shape, logger
            )
            new_plan.frames.append(frame_matrix)

            new_plan.active_droplets_per_frame.append(list(active_droplets))

            # Update trajectories
            for droplet_id, pos in zip(sub_droplet_ids, positions):
                new_plan.droplet_trajectories[droplet_id].append(pos)

    else:
        # Sequential movement - each subdroplet moves one by one
        current_positions = [sd.origin_corner for sd in sub_droplets]

        for i, (sub_droplet, final_pos, droplet_id) in enumerate(zip(sub_droplets, final_positions, sub_droplet_ids)):
            # Generate trajectory for this subdroplet from its origin
            trajectory = _calculate_trajectory(sub_droplet.origin_corner, final_pos)

            # Move this subdroplet through its trajectory (skip the first position which is the split)
            for position in trajectory[1:]:  # Skip start position
                # Update this subdroplet's position
                current_positions[i] = position

                # Create frame with current positions
                frame_matrix = _create_isometric_frame(
                    new_plan, None, sub_droplets, current_positions, matrix_shape, logger
                )
                new_plan.frames.append(frame_matrix)

                # Update active droplets; same subdroplets remain active during movement.
                new_plan.active_droplets_per_frame.append(list(active_droplets))

                # Update trajectories for all subdroplets
                for j, pos in enumerate(current_positions):
                    new_plan.droplet_trajectories[sub_droplet_ids[j]].append(pos)

    # Update frame count
    new_plan.frame_count = len(new_plan.frames)

    # Extend all trajectories to match frame count (droplets stay at their final positions)
    for droplet_id, trajectory in new_plan.droplet_trajectories.items():
        # Find the droplet's final position (either current or from trajectory)
        final_position = trajectory[-1] if trajectory else (0, 0)  # fallback
        while len(trajectory) < new_plan.frame_count:
            trajectory.append(final_position)

    return droplets, new_plan


def _generate_simultaneous_trajectories_from_origins(
    start_positions: List[Tuple[int, int]],
    final_positions: List[Tuple[int, int]],
    logger
) -> List[List[Tuple[int, int]]]:
    """Generate simultaneous trajectories for subdroplets starting from different origins."""
    # Calculate max steps needed
    max_steps = 0
    for start_pos, final_pos in zip(start_positions, final_positions):
        trajectory = _calculate_trajectory(start_pos, final_pos)
        max_steps = max(max_steps, len(trajectory) - 1)  # -1 because trajectory includes start

    trajectories = []
    for start_pos, final_pos in zip(start_positions, final_positions):
        trajectory = _calculate_trajectory(start_pos, final_pos)
        # Extend trajectory to match max_steps
        while len(trajectory) < max_steps + 1:  # +1 for start position
            trajectory.append(final_pos)
        trajectories.append(trajectory)

    # Transpose to get positions per frame
    frame_positions = []
    for frame_idx in range(max_steps + 1):
        frame_pos = [traj[frame_idx] for traj in trajectories]
        frame_positions.append(frame_pos)

    return frame_positions


def _create_split_frame_at_positions(
    new_plan: DropletPlan,
    source_droplet: Droplet,
    sub_droplets: List[Droplet],
    positions: List[Tuple[int, int]],
    matrix_shape: Tuple[int, int],
    logger
) -> np.ndarray:
    """Create the initial frame showing subdroplets at their positions."""
    # Start with the last frame
    if new_plan.frames:
        frame_matrix = new_plan.frames[-1].copy()
    else:
        frame_matrix = np.zeros(matrix_shape, dtype=np.int32)

    # Clear the source droplet positions (it's being replaced by subdroplets)
    source_positions = get_droplet_positions(source_droplet, source_droplet.origin_corner)
    for x, y in source_positions:
        if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
            frame_matrix[x, y] = 0

    # Set subdroplet positions at their positions
    for sub_droplet, final_pos in zip(sub_droplets, positions):
        sub_positions = get_droplet_positions(sub_droplet, final_pos)
        for x, y in sub_positions:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                frame_matrix[x, y] = 1

    return frame_matrix


def _create_isometric_frame(
    new_plan: DropletPlan,
    source_droplet: Droplet,
    sub_droplets: List[Droplet],
    sub_positions: List[Tuple[int, int]],
    matrix_shape: Tuple[int, int],
    logger
) -> np.ndarray:
    """Create a frame for isometric splitting movement."""
    # Start with the last frame
    frame_matrix = new_plan.frames[-1].copy()

    # Clear all subdroplet positions from the previous frame
    for sub_droplet in sub_droplets:
        # Find this subdroplet's previous position from trajectory
        sub_id = sub_droplet.id
        if sub_id in new_plan.droplet_trajectories:
            trajectory = new_plan.droplet_trajectories[sub_id]
            if len(trajectory) > 0:
                prev_position = trajectory[-1]  # Last position in trajectory
                prev_positions = get_droplet_positions(sub_droplet, prev_position)
                for x, y in prev_positions:
                    if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                        frame_matrix[x, y] = 0  # Deactivate previous position

    # Set new subdroplet positions
    for sub_droplet, position in zip(sub_droplets, sub_positions):
        sub_positions_set = get_droplet_positions(sub_droplet, position)
        for x, y in sub_positions_set:
            if 0 <= x < matrix_shape[0] and 0 <= y < matrix_shape[1]:
                frame_matrix[x, y] = 1  # Activate new position

    return frame_matrix


def _update_reservoir_shape(
    reservoir_droplet: Droplet,
    new_shape: set,
    logger
) -> None:
    """
    Update the shape of the reservoir droplet.

    Args:
        reservoir_droplet: The reservoir droplet to update
        new_shape: New shape as set of (x, y) tuples
        logger: Logger instance for logging
    """
    logger.debug(f"Updating reservoir droplet {reservoir_droplet.id} shape from {len(reservoir_droplet.shape)} to {len(new_shape)} electrodes")
    reservoir_droplet.shape = new_shape




def _create_split_droplet(
    droplets: List[Droplet],
    new_plan: DropletPlan,
    shape: set,
    position: Tuple[int, int],
    target: Tuple[int, int],
    reservoir_id: int,
    new_droplet_id: Optional[int],
    logger,
    vital_space: int = 1
) -> int:
    """
    Create a new droplet from the split portion.

    Args:
        droplets: Current list of droplets
        droplet_plan: Current droplet plan
        shape: Shape of the new droplet
        position: Initial position of the new droplet
        target: Target position of the new droplet
        reservoir_id: ID of the reservoir droplet
        logger: Logger instance for logging

    Returns:
        ID of the newly created droplet
    """
    # Generate or use provided droplet ID
    if new_droplet_id is not None:
        # Validate that the provided ID is not already in use
        existing_ids = {d.id for d in droplets}
        if new_droplet_id in existing_ids:
            logger.error(f"Droplet ID {new_droplet_id} is already in use")
            raise ValueError(f"Droplet ID {new_droplet_id} is already in use")
        new_id = new_droplet_id
    else:
        # Auto-generate next available ID
        existing_ids = {d.id for d in droplets}
        new_id = max(existing_ids) + 1 if existing_ids else 1

    # Create new droplet
    new_droplet = create_droplet(
        droplet_id=new_id,
        origin=position,
        target=target,
        shape=shape,
        priority=0,  # Default priority
        vital_space=vital_space
    )

    # Add to droplets list
    droplets.append(new_droplet)

    # Add trajectory to plan (initially at origin)
    new_plan.droplet_trajectories[new_id] = [position]

    logger.info(f"Created new droplet {new_id} from reservoir {reservoir_id}")
    return new_id



