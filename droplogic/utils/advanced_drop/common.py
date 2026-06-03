"""
Common utilities and data structures for advanced droplet manipulation.

This module provides shared functionality for multi-droplet path planning,
collision detection, and vital space management on Digital Microfluidics (DMF) chips.
"""

from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Tuple, Set
import numpy as np
from ..hardware_utils import electrode_to_stage
from ..logging_config import setup_droplogic_logger
import time


@dataclass
class Droplet:
    """Represents a droplet with shape, position, and movement constraints."""
    id: int                           # Unique identifier
    shape: Set[Tuple[int, int]]      # Relative electrode positions from top-left
    origin_corner: Tuple[int, int]   # Current top-left position
    target_corner: Tuple[int, int]   # Desired top-left position
    priority: int = 0                # For conflict resolution (higher = more priority)
    vital_space: int = 1             # Minimum distance other droplets must maintain
    electrode_count: int = 0         # Total number of electrodes (for merged droplets with overlapping positions)

    def __setattr__(self, name, value):
        # We only warn when overwriting an existing initialized value
        if getattr(self, "_initialized", False) and name in ("origin_corner", "shape"):
            import inspect, warnings
            try:
                frame = inspect.currentframe().f_back
                filename = inspect.getframeinfo(frame).filename
                # Anything not inside advanced_drop is a user script / external module
                if "advanced_drop" not in filename.replace("\\", "/"):
                    warnings.warn(
                        f"\n[WARNING] Directly modifying droplet.{name} from user scripts is highly unsafe!\n"
                        f"This disconnects the SIPP routing matrix from the final physical truth.\n"
                        f"Please use `ctx.advanced_drop.correct_droplet_position({self.id}, pos)` instead "
                        f"if you need to force a trajectory correction after a hardware split/move failure.",
                        stacklevel=2
                    )
            except Exception:
                pass
        super().__setattr__(name, value)
        
    def __post_init__(self):
        self._initialized = True

class DropletList(list):
    """A list-like container for droplets with management methods."""

    def __init__(self, system, parent):
        super().__init__()
        self.system = system
        self.parent = parent  # Reference to parent AdvancedDrop

    def create_droplet(self, droplet_id, origin, target, **kwargs):
        """Create and add a droplet to the list."""
        droplet = create_droplet(droplet_id, origin, target, **kwargs)
        self.append(droplet)

        # If there's an existing plan, add a new frame with the droplet at its origin position
        if hasattr(self.parent, 'plan') and self.parent.plan and self.parent.plan.frames:
            # Create a new frame based on the last frame
            new_frame = self.parent.plan.frames[-1].copy()

            # Add the new droplet at its origin position (target and origin coincide for stationary droplets)
            droplet_positions = get_droplet_positions(droplet, droplet.origin_corner)
            for x, y in droplet_positions:
                if 0 <= x < new_frame.shape[0] and 0 <= y < new_frame.shape[1]:
                    new_frame[x, y] = 1

            # Get the last active list to include all existing active droplets
            last_active = self.parent.plan.active_droplets_per_frame[-1] if self.parent.plan.active_droplets_per_frame else []

            # Create a temporary plan for the new frame
            from .common import DropletPlan
            new_plan = DropletPlan(
                frames=[new_frame],
                frame_count=1,
                droplet_trajectories={droplet_id: [droplet.origin_corner]},
                active_droplets_per_frame=[last_active + [droplet_id]],
                events=[],
                planning_success=True,
                conflicts_resolved=[],
                targets_reached={},
                event_id_per_frame=[]
            )

            # Extend the plan using the parent's extend_plan method
            self.parent.plan = self.parent.extend_plan(self.parent.plan, new_plan, event_type="create", event_data={"droplet_id": droplet_id}, remove_duplicate_frames=False)

            # self.system.logger.debug(f"Added frame for new droplet {droplet_id} at {droplet.origin_corner}")

        return droplet

    def delete_droplet(self, droplet_id: int) -> bool:
        """Delete a droplet by ID."""
        for i, droplet in enumerate(self):
            if droplet.id == droplet_id:
                self.pop(i)
                self.system.logger.info(f"Deleted droplet {droplet_id}")
                # Note: Plan is not reset - use move() to replan for remaining droplets
                return True
        self.system.logger.warning(f"Droplet {droplet_id} not found")
        return False

    def update_droplet_target(self, droplet_id: int, new_target) -> bool:
        """Update the target position of a droplet."""
        for droplet in self:
            if droplet.id == droplet_id:
                droplet.target_corner = new_target
                # self.system.logger.info(f"Updated droplet {droplet_id} target to {new_target}")
                # Note: Plan is not reset - use move() to replan for active droplets
                return True
        self.system.logger.warning(f"Droplet {droplet_id} not found")
        return False

    def update_droplet_position(self, droplet_id: int, new_position) -> bool:
        """Update the current position of a droplet."""
        for droplet in self:
            if droplet.id == droplet_id:
                droplet.origin_corner = new_position
                # self.system.logger.info(f"Updated droplet {droplet_id} position to {new_position}")
                return True
        self.system.logger.warning(f"Droplet {droplet_id} not found")
        return False

    def get_droplet(self, droplet_id: int):
        """Get a specific droplet by ID."""
        for droplet in self:
            if droplet.id == droplet_id:
                return droplet
        return None
    
    def get_droplet_info(self, droplet_id: int):
            """Get detailed information about a specific droplet."""
            droplet = self.get_droplet(droplet_id)
            if droplet:
                return {
                    'id': droplet.id,
                    'current_position': droplet.origin_corner,
                    'target_position': droplet.target_corner,
                    'shape': droplet.shape,
                    'priority': droplet.priority,
                    'vital_space': droplet.vital_space
                }
            return None

    def add_droplets(self, droplets_list):
        """Add multiple droplets at once."""
        created_droplets = []
        for droplet_data in droplets_list:
            try:
                droplet = self.create_droplet(
                    droplet_id=droplet_data['id'],
                    origin=droplet_data['origin'],
                    target=droplet_data['target'],
                    shape=droplet_data.get('shape'),
                    width=droplet_data.get('width'),
                    height=droplet_data.get('height'),
                    priority=droplet_data.get('priority', 0),
                    vital_space=droplet_data.get('vital_space', 1)
                )
                created_droplets.append(droplet)
            except Exception as e:
                self.system.logger.error(f"Failed to create droplet {droplet_data.get('id', 'unknown')}: {e}")

        # self.system.logger.info(f"Added {len(created_droplets)} droplets")
        return created_droplets

    def get_droplets_summary(self):
        """Get a summary of all current droplets and their status."""
        summary = {
            'total_droplets': len(self),
            'droplets': [],
            'has_plan': self.parent.plan is not None
        }

        for droplet in self:
            droplet_info = {
                'id': droplet.id,
                'current_position': droplet.origin_corner,
                'target_position': droplet.target_corner,
                'at_target': droplet.origin_corner == droplet.target_corner,
                'priority': droplet.priority,
                'shape_size': len(droplet.shape),
                'vital_space': droplet.vital_space
            }
            summary['droplets'].append(droplet_info)

        return summary
    
@dataclass
class DropletPlan:
    """Represents a complete plan for droplet manipulation operations on a DMF chip."""
    frames: List[np.ndarray]  # List of 2D arrays showing electrode ON/OFF states for each frame
    frame_count: int  # Total number of frames in the plan (should equal len(frames))
    droplet_trajectories: Dict[int, List[Tuple[int, int]]]  # Maps droplet ID to list of (row,col) positions over time
    active_droplets_per_frame: List[List[int]]  # List of lists; each sublist contains droplet IDs active in that frame
    events: List[Tuple[int, str, Any]]  # Chronological log of events: (frame_index, event_type, metadata_dict)
    planning_success: bool  # True if all droplet targets were successfully reached
    conflicts_resolved: List[Dict]  # List of dicts documenting any conflicts that were detected and resolved
    targets_reached: Dict[int, bool]  # Maps droplet ID to boolean indicating if its target position was reached
    event_id_per_frame: List[Optional[int]] = field(default_factory=list)  # Tags each frame with an event ID (or None)

def init_event_tracking(plan: DropletPlan) -> None:
    """Pad event_id_per_frame to match the number of frames."""
    if len(plan.event_id_per_frame) < len(plan.frames):
        plan.event_id_per_frame.extend([None] * (len(plan.frames) - len(plan.event_id_per_frame)))

def ensure_event_capacity(plan: DropletPlan, size: int) -> None:
    """Ensure event_id_per_frame has at least 'size' elements."""
    if len(plan.event_id_per_frame) < size:
        plan.event_id_per_frame.extend([None] * (size - len(plan.event_id_per_frame)))

def tag_frame_span(plan: DropletPlan,
                   start_idx: int,
                   count: int,
                   event_id: int,
                   event_type: str,
                   data: Optional[Dict[str, Any]] = None) -> None:
    """Tag a span of frames with an event ID and log the event."""
    if data is None:
        data = {}
    init_event_tracking(plan)
    end_idx = start_idx + count - 1
    ensure_event_capacity(plan, end_idx + 1)
    for i in range(start_idx, end_idx + 1):
        plan.event_id_per_frame[i] = event_id
    plan.events.append((
        start_idx,
        event_type,
        {"event_id": event_id, "frame_span": (start_idx, end_idx), **data}
    ))

def backfill_initial_event(plan: DropletPlan, event_type="init"):
    """Tag legacy frames that were added before event tracking."""
    init_event_tracking(plan)
    if all(e is None for e in plan.event_id_per_frame) and plan.frames:
        eid = next_event_id(plan)
        tag_frame_span(plan, 0, len(plan.frames), eid, event_type=event_type, data={})

def create_droplet(droplet_id: int, origin: Tuple[int, int], target: Tuple[int, int],
                  shape: Optional[Set[Tuple[int, int]]] = None, width: Optional[int] = None, 
                  height: Optional[int] = None, priority: int = 0, vital_space: int = 1) -> Droplet:
    """
    Create a droplet with flexible shape specification.
    
    Args:
        droplet_id: Unique identifier for the droplet
        origin: Starting position (top-left corner)
        target: Target position (top-left corner)
        shape: Custom shape as set of relative positions from top-left corner
        width: Width for rectangular droplet (used with height)
        height: Height for rectangular droplet (used with width)
        priority: Priority for conflict resolution (higher = more priority)
        vital_space: Minimum distance other droplets must maintain
        
    Returns:
        Droplet object
        
    Examples:
        # Single electrode droplet
        droplet = create_droplet(1, (10, 10), (20, 20))
        
        # Rectangular droplet
        droplet = create_droplet(2, (5, 5), (15, 15), width=2, height=3)
        
        # Custom shape droplet
        custom_shape = {(0, 0), (0, 1), (1, 0)}  # L-shape
        droplet = create_droplet(3, (0, 0), (10, 10), shape=custom_shape)
    """
    # Determine shape
    if shape is not None:
        # Use provided custom shape
        droplet_shape = shape
    elif width is not None and height is not None:
        # Create rectangular shape
        droplet_shape = {(i, j) for i in range(height) for j in range(width)}
    else:
        # Default to single electrode
        droplet_shape = {(0, 0)}
    
    return Droplet(
        id=droplet_id,
        shape=droplet_shape,
        origin_corner=origin,
        target_corner=target,
        priority=priority,
        vital_space=vital_space,
        electrode_count=len(droplet_shape)
    )

def get_droplet_positions(droplet: Droplet, corner: Tuple[int, int]) -> Set[Tuple[int, int]]:
    """Get all electrode positions occupied by droplet at given corner."""
    if corner is None:
        raise ValueError("corner cannot be None")
    x, y = corner
    return {(x + dx, y + dy) for dx, dy in droplet.shape}

def get_droplet_vital_area(droplet: Droplet, corner: Tuple[int, int]) -> Set[Tuple[int, int]]:
    """Get all electrode positions within vital space of droplet."""
    droplet_positions = get_droplet_positions(droplet, corner)
    vital_area = set(droplet_positions)
    
    # Add buffer around each droplet electrode using droplet's vital_space
    for x, y in droplet_positions:
        for dx in range(-droplet.vital_space, droplet.vital_space + 1):
            for dy in range(-droplet.vital_space, droplet.vital_space + 1):
                vital_area.add((x + dx, y + dy))
    
    return vital_area

def calculate_droplet_center(droplet_id: int, corner_pos: Tuple[int, int], droplets, logger) -> Dict[str, int]:
    """
    Calculate the center position of a droplet given its corner position.

    If the droplet shape has an even number of rows or columns the true center
    lies between electrode indices. In that case this function will:
      - determine the 2 or 4 candidate electrodes that surround the center,
      - call electrode_to_stage for each candidate,
      - average the returned stage X/Y(/Z) positions for logging/debugging,
      - return the averaged electrode indices (may be fractional) so the caller
        can convert to stage coordinates (electrode_to_stage accepts fractional
        indices for interpolation).

    Args:
        droplet_id: ID of the droplet to calculate center for
        corner_pos: Corner position (row, col) of the droplet
        droplets: DropletList or list of droplets to find the droplet in
        logger: Logger instance for debug messages

    Returns:
        Dictionary with X, Y, Z stage coordinates for use with box.update_state()
    """
    # Try to get droplet info from the droplets list
    try:
        if hasattr(droplets, 'get_droplet'):
            droplet = droplets.get_droplet(droplet_id)
        else:
            droplet = next((d for d in droplets if d.id == droplet_id), None)
    except Exception as e:
        logger.debug(f"Error retrieving droplet {droplet_id}: {e}")
        droplet = None

    if droplet:
        # Build absolute electrode positions of the droplet shape based on the provided corner
        shape_positions = [(corner_pos[0] + int(dx), corner_pos[1] + int(dy)) for dx, dy in droplet.shape]
        if shape_positions:
            min_row = min(r for r, c in shape_positions)
            max_row = max(r for r, c in shape_positions)
            min_col = min(c for r, c in shape_positions)
            max_col = max(c for r, c in shape_positions)

            # Determine candidate rows/cols. If the count is odd -> single center index,
            # if even -> two candidate indices (center between them).
            num_rows = max_row - min_row + 1
            num_cols = max_col - min_col + 1

            if num_rows % 2 == 1:
                center_rows = [ (min_row + max_row) // 2 ]
            else:
                r0 = (min_row + max_row) // 2
                center_rows = [ r0, r0 + 1 ]

            if num_cols % 2 == 1:
                center_cols = [ (min_col + max_col) // 2 ]
            else:
                c0 = (min_col + max_col) // 2
                center_cols = [ c0, c0 + 1 ]

            # Candidate electrode coordinates (1, 2 or 4)
            candidates = [(r, c) for r in center_rows for c in center_cols]

            # Query stage coordinates for each candidate electrode (if possible) and average them.
            stage_points = []
            for r, c in candidates:
                try:
                    stage = electrode_to_stage(r, c)
                    # Normalize electrode_to_stage output to a sequence of floats.
                    # Support dict returns like {'X': ..., 'Y': ..., 'Z': ...} as well as sequences.
                    if stage is None:
                        continue

                    def _get_first(d, *keys):
                        for k in keys:
                            if k in d and d[k] is not None:
                                return d[k]
                        return None

                    x_val = _get_first(stage, 'X', 'x', 'x_mm', 'X_mm')
                    y_val = _get_first(stage, 'Y', 'y', 'y_mm', 'Y_mm')
                    z_val = _get_first(stage, 'Z', 'z', 'z_mm', 'Z_mm')

                    coords = []
                    if x_val is not None:
                        coords.append(float(x_val))
                    if y_val is not None:
                        coords.append(float(y_val))
                    if z_val is not None:
                        coords.append(float(z_val))

                    if coords:
                        stage_points.append(tuple(coords))

                except Exception as e:
                    logger.debug(f"electrode_to_stage failed for ({r},{c}): {e}")

            if not stage_points:
                logger.debug(f"No stage points obtained for droplet {droplet_id} candidates {candidates}")
                # Fall back to averaging electrode indices if we couldn't get any stage coordinates
                avg_row = float(np.mean([r for r, _ in candidates]))
                avg_col = float(np.mean([c for _, c in candidates]))
                logger.debug(
                    f"Droplet {droplet_id} using averaged electrode indices fallback (no stage points): ({avg_row:.3f},{avg_col:.3f})"
                )
                return {"X": int(avg_row), "Y": int(avg_col), "Z": 0}

            # Normalize all stage point tuples to (x, y, z) by padding/truncating as needed
            normalized = []
            for p in stage_points:
                if len(p) >= 3:
                    normalized.append((float(p[0]), float(p[1]), float(p[2])))
                elif len(p) == 2:
                    normalized.append((float(p[0]), float(p[1]), 0.0))
                elif len(p) == 1:
                    normalized.append((float(p[0]), 0.0, 0.0))
                else:
                    # Unexpected empty tuple; skip
                    continue

            if not normalized:
                # If normalization removed everything, fall back to electrode-index averaging
                avg_row = float(np.mean([r for r, _ in candidates]))
                avg_col = float(np.mean([c for _, c in candidates]))
                logger.debug(
                    f"Droplet {droplet_id} using averaged electrode indices fallback (normalization empty): ({avg_row:.3f},{avg_col:.3f})"
                )
                return {"X": int(avg_row), "Y": int(avg_col), "Z": 0}

            stage_points = normalized
            xs = [p[0] for p in stage_points]
            ys = [p[1] for p in stage_points]
            zs = [p[2] for p in stage_points] if len(stage_points[0]) > 2 else [0.0] * len(stage_points)

            avg_stage = (int(np.mean(xs)), int(np.mean(ys)), int(np.mean(zs)))

            # Return a dict with x,y,z as electrode_to_stage does
            return {"X": int(avg_stage[0]), "Y": int(avg_stage[1]), "Z": int(avg_stage[2])}
            
    # Default fallback if droplet not found or calculation fails completely
    try:
        stage = electrode_to_stage(corner_pos[0], corner_pos[1])
        if stage:
            return stage
    except Exception as e:
        logger.debug(f"Fallback electrode_to_stage failed: {e}")
        
    return {"X": 0, "Y": 0, "Z": 0}

def is_valid_droplet_position(droplet: Droplet, corner: Tuple[int, int], matrix: np.ndarray, logger=None) -> bool:
    """
    Check if droplet can be placed at corner position.
    
    Validates:
    - All droplet electrodes are within bounds
    - No droplet electrodes overlap forbidden positions (-1)
    - Droplet maintains vital_space distance from forbidden electrodes
    """
    # # Debug: Save matrix to file
    # debug_filename = f"debug_matrix_droplet.txt"
    # np.savetxt(debug_filename, matrix, fmt='%d')
    # # Also save as numpy binary for programmatic access
    # np.save(f"debug_matrix_droplet.npy", matrix)
    
    rows, cols = matrix.shape
    droplet_positions = get_droplet_positions(droplet, corner)
    
    # Check bounds
    if not all(0 <= x < rows and 0 <= y < cols for x, y in droplet_positions):
        if logger:
            logger.debug(f"DROPLET_{droplet.id}_POS_{corner[0]}_{corner[1]}_OUT_OF_BOUNDS")
        return False
    
    # Check direct conflicts with forbidden (-1) or permanent ON (1) electrodes
    if any(matrix[x, y] in [-1, 1] for x, y in droplet_positions):
        if logger:
            logger.debug(f"DROPLET_{droplet.id}_POS_{corner[0]}_{corner[1]}_DIRECT_CONFLICT")
            # log an ascii of the matrix around the position (4 by 4 area)
            x_min = max(0, corner[0] - 2)
            x_max = min(rows, corner[0] + 3)
            y_min = max(0, corner[1] - 2)
            y_max = min(cols, corner[1] + 3)
            matrix_snippet = matrix[x_min:x_max, y_min:y_max]
            logger.debug(f"DROPLET_{droplet.id}_POS_{corner[0]}_{corner[1]}_MATRIX_SNIPPET:\n{matrix_snippet}")
        return False
    
    # Check vital space around forbidden and permanent ON electrodes
    avoided_positions = set(zip(*np.where((matrix == -1) | (matrix == 1))))
    for avoided_pos in avoided_positions:
        fx, fy = avoided_pos
        for droplet_pos in droplet_positions:
            dx, dy = droplet_pos
            distance = max(abs(dx - fx), abs(dy - fy))  # Chebyshev distance
            if distance <= droplet.vital_space:
                if logger:
                    logger.debug(f"DROPLET_{droplet.id}_POS_{corner[0]}_{corner[1]}_VITAL_SPACE_CONFLICT_WITH_{fx}_{fy}")
                return False
    
    return True

def check_vital_space_conflict(droplet1: Droplet, corner1: Tuple[int, int],
                              droplet2: Droplet, corner2: Tuple[int, int]) -> bool:
    """
    Check if two droplets violate vital space constraint.

    Returns True if conflict exists.
    """
    positions1 = get_droplet_positions(droplet1, corner1)
    vital_area2 = get_droplet_vital_area(droplet2, corner2)

    # Check both directions - either droplet can violate the other's vital space
    vital_area1 = get_droplet_vital_area(droplet1, corner1)
    positions2 = get_droplet_positions(droplet2, corner2)
    return bool((positions1 & vital_area2) or (positions2 & vital_area1))

def init_event_tracking(plan: DropletPlan) -> None:
    # pad to current number of frames
    if plan.event_id_per_frame is None:
        plan.event_id_per_frame = []
    if len(plan.event_id_per_frame) < len(plan.frames):
        plan.event_id_per_frame.extend([None] * (len(plan.frames) - len(plan.event_id_per_frame)))

def relax_droplet_shape(droplet: Droplet, plan: DropletPlan, droplets: List[Droplet], logger) -> None:
    """
    Relax the droplet shape to fit into the smallest rectangle containing all activated electrodes.

    This function finds the minimal bounding rectangle that contains all electrodes in the current
    droplet shape. If the shape doesn't fill this rectangle completely, it redistributes the
    electrodes symmetrically to create a more compact, rectangular shape.

    Args:
        droplet: The droplet to relax
        plan: The droplet plan to add frames to
        droplets: List of all droplets for frame updates
        logger: Logger instance for logging
    """
    if not droplet.shape:
        logger.warning(f"Droplet {droplet.id} has no shape to relax")
        return

    # Check upper left position
    origin_row, origin_col = droplet.origin_corner
    logger.debug(f"Droplet {droplet.id} origin_corner: ({origin_row}, {origin_col})")

    # Count total electrode size in the shape
    total_electrodes = len(droplet.shape)
    logger.debug(f"Droplet {droplet.id} has {total_electrodes} electrodes")

    # Calculate the bounding box that contains all those electrodes
    # Convert relative coordinates to absolute for bounding box calculation
    absolute_positions = {(origin_row + rel_row, origin_col + rel_col) for rel_row, rel_col in droplet.shape}

    if not absolute_positions:
        logger.warning(f"Droplet {droplet.id} has no absolute positions")
        return

    rows = {pos[0] for pos in absolute_positions}
    cols = {pos[1] for pos in absolute_positions}
    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)

    bounding_width = max_col - min_col + 1
    bounding_height = max_row - min_row + 1
    logger.debug(f"Bounding box: {bounding_width}x{bounding_height} (rows [{min_row}, {max_row}], cols [{min_col}, {max_col}])")

    # Use the bounding box as the target rectangle
    new_height = bounding_height
    new_width = bounding_width
    logger.debug(f"Target rectangle: {new_width}x{new_height}")

    # Calculate holes in the bounding box
    holes = (new_width * new_height) - total_electrodes
    logger.debug(f"Holes to fill: {holes}")

    # Calculate the center of the droplet
    center_row = (min_row + max_row) / 2
    center_col = (min_col + max_col) / 2
    logger.debug(f"Droplet center: ({center_row}, {center_col})")

    # Create rectangle positions
    rectangle_positions = set()
    for r in range(new_height):
        for c in range(new_width):
            rectangle_positions.add((min_row + r, min_col + c))

    # Calculate Manhattan distance from all positions in the bounding box
    # Divide positions into four groups: upper right corner, upper left, bottom right, bottom left
    upper_left = []
    upper_right = []
    bottom_left = []
    bottom_right = []

    for r, c in rectangle_positions:
        dist = abs(r - center_row) + abs(c - center_col)
        if r < center_row:
            if c < center_col:
                upper_left.append((dist, (r, c)))
            else:
                upper_right.append((dist, (r, c)))
        else:
            if c < center_col:
                bottom_left.append((dist, (r, c)))
            else:
                bottom_right.append((dist, (r, c)))

    # Sort each group by distance descending (maximum first)
    upper_left.sort(reverse=True)
    upper_right.sort(reverse=True)
    bottom_left.sort(reverse=True)
    bottom_right.sort(reverse=True)

    # REMOVAL LOOP: take the list of all positions inside the bounding box
    # remove one from upper right corner, trying to choose the maximum manhattan distance
    # check if all holes have been distributed. yes? finish no? continue
    # remove one hole from bottom right corner, trying to choose the maximum
    # check if all holes have been distributed. yes? finish no? continue
    # remove one hole from bottom left corner, trying to choose the maximum
    # check if all holes have been distributed. yes? finish no? continue
    # remove one hole from top right corner, trying to choose the maximum
    # check if all holes have been distributed. yes? finish no? continue
    # repeat in circles until distributed all holes
    groups = [upper_right, bottom_right, bottom_left, upper_left]
    positions_to_remove = set()
    group_index = 0
    while len(positions_to_remove) < holes:
        group = groups[group_index % 4]
        if group:
            dist, pos = group.pop(0)
            positions_to_remove.add(pos)
        group_index += 1

    # Keep remaining positions
    new_absolute_shape = rectangle_positions - positions_to_remove

    # Convert back to relative coordinates
    new_shape = {(abs_row - origin_row, abs_col - origin_col) for abs_row, abs_col in new_absolute_shape}

    # Change the Droplet shape (and original corner) and add a frame to the droplet plan with the new droplet shape and the rest of the frame exactly the same
    old_shape = droplet.shape.copy()
    droplet.shape = new_shape

    # If the new shape changes the bounding box, we might need to adjust origin_corner
    # For now, keep the same origin_corner and let the shape be relative to it

    # Add a frame to the droplet plan with the new droplet shape and the rest of the frame exactly the same
    if plan.frames:
        # Create a new frame based on the last frame
        new_frame = plan.frames[-1].copy()

        # Update the droplet electrodes in the frame
        # Clear old droplet positions
        for rel_row, rel_col in old_shape:
            abs_row = origin_row + rel_row
            abs_col = origin_col + rel_col
            if 0 <= abs_row < new_frame.shape[0] and 0 <= abs_col < new_frame.shape[1]:
                new_frame[abs_row, abs_col] = 0

        # Set new droplet positions
        for rel_row, rel_col in new_shape:
            abs_row = origin_row + rel_row
            abs_col = origin_col + rel_col
            if 0 <= abs_row < new_frame.shape[0] and 0 <= abs_col < new_frame.shape[1]:
                new_frame[abs_row, abs_col] = 1

        # Add the new frame to the plan
        plan.frames.append(new_frame)
        plan.active_droplets_per_frame.append([d.id for d in droplets])
        plan.frame_count = len(plan.frames)

        # Update trajectories for the droplet
        if droplet.id not in plan.droplet_trajectories:
            plan.droplet_trajectories[droplet.id] = []
        plan.droplet_trajectories[droplet.id].append(droplet.origin_corner)

        # Tag the new frame with an event
        start_idx = len(plan.frames) - 1
        eid = next_event_id(plan)
        tag_frame_span(plan, start_idx, 1, eid, "relax", {"droplet_id": droplet.id})

        logger.info(f"Added relaxation frame to plan. New frame count: {plan.frame_count}")
        logger.info(f"Relaxed droplet {droplet.id}: {len(old_shape)} electrodes -> {len(new_shape)} electrodes "
           f"in {new_width}x{new_height} rectangle")

def next_event_id(container) -> int:
    """
    Accepts either a planner with `.plan` or the `plan` itself.
    Stores the counter on the plan object so all call sites share it.
    """
    plan = getattr(container, "plan", container)
    if not hasattr(plan, "_next_event_id"):
        plan._next_event_id = 1
    eid = plan._next_event_id
    plan._next_event_id += 1
    return eid

def tag_new_frames_with_event(plan: DropletPlan, start_idx: int, count: int, event_id: int,
                              event_type: str, data: Optional[Dict[str, Any]] = None):
    """Assign `event_id` to the last `count` frames starting at `start_idx` and log an event."""
    if data is None:
        data = {}
    # ensure the list is long enough
    while len(plan.event_id_per_frame) < start_idx:
        plan.event_id_per_frame.append(None)
    # tag frames
    for _ in range(count):
        plan.event_id_per_frame.append(event_id)
    # log event at the first new frame
    plan.events.append((
        start_idx,
        event_type,
        {"event_id": event_id, "frame_span": (start_idx, start_idx + count - 1), **data}
    ))

def tag_frame_span(plan: DropletPlan, start_idx: int, count: int, event_id: int,
                   event_type: str = "operation", data: Optional[Dict[str, Any]] = None):
    """Tag a span of frames with an event ID and log the event."""
    if data is None:
        data = {}
    end_frame = start_idx + count - 1
    # Ensure event_id_per_frame is long enough
    while len(plan.event_id_per_frame) <= end_frame:
        plan.event_id_per_frame.append(None)
    # Tag the frames
    for frame_idx in range(start_idx, end_frame + 1):
        plan.event_id_per_frame[frame_idx] = event_id
    # Log the event
    plan.events.append((
        start_idx,
        event_type,
        {"event_id": event_id, "frame_span": (start_idx, end_frame), **data}
    ))


