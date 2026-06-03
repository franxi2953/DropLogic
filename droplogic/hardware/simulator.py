from ..base import DropSystem, Priority
from typing import Any
import numpy as np
import threading
import time
import logging
from ..utils.advanced_drop import AdvancedDrop
from ..utils.visualizer import MatrixVisualizer

class Simulator(DropSystem):
    """Simulated DropSystem hardware system with electrode matrix functionality only."""

    _instance = None
    
    def __new__(cls, config_file="config.json", log_level=logging.INFO):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_file="config.json", log_level=logging.INFO):
        if isinstance(log_level, str):
            log_level = getattr(logging, log_level.upper(), logging.INFO)
        
        if hasattr(self, "_initialized") and self._initialized:
            # Update logger level even if already initialized
            self.logger.setLevel(log_level)
            for handler in self.logger.handlers:
                handler.setLevel(log_level)
            from ..utils.logging_config import set_droplogic_logging_level
            set_droplogic_logging_level(log_level)
            return  # Already initialized
        
        super().__init__("Simulator", state_file=config_file, log_level=log_level)
        self.logger.info("Simulator initialization started")

        # Initialize electrode matrix from state
        electrode_config = self.state.get("electrode_matrix", {})
        rows = electrode_config.get("rows", 128)
        columns = electrode_config.get("columns", 128)
        voltage = electrode_config.get("voltage", 40)
        
        # Initialize simulated electrode matrix state
        self._simulated_matrix = np.zeros((rows, columns), dtype=int)
        self._simulated_voltage = voltage
        
        # Thread lock for electrode operations
        self._electrode_lock = threading.Lock()
        
        # Initialize matrix as zeros in state
        matrix = np.zeros((rows, columns), int).tolist()
        self.update_state("electrode_matrix.matrix", matrix)
        
        # Initialize simulated XY stage
        self._xy_stage_lock = threading.Lock()
        self._simulated_xy_position = {
            'X': self.state.get('xy_stage', {}).get('position', {}).get('X', 0),
            'Y': self.state.get('xy_stage', {}).get('position', {}).get('Y', 0),
            'Z': self.state.get('xy_stage', {}).get('position', {}).get('Z', 0)
        }
        self._xy_motion_complete = {'X': True, 'Y': True, 'Z': True}
        
        # Create a simple XY stage mock object for compatibility
        self.xy_stage = self._XYStageMock(self)
        
        self._initialized = True
        self.logger.info(f"Simulator initialized with {rows}x{columns} electrode matrix at {voltage}V")

        # Initialize visualizers namespace
        self.visualizers = self._VisualizersContainer()
        self._initialize_visualizers()

        # Initialize advanced drop functionality after visualizers setup
        self.advanced_drop = AdvancedDrop(self)

    class _XYStageMock:
        """Mock XY stage for simulator compatibility."""
        def __init__(self, simulator):
            self.simulator = simulator
        
        def is_motion_complete(self, axis: str) -> bool:
            """Check if motion is complete for given axis."""
            with self.simulator._xy_stage_lock:
                return self.simulator._xy_motion_complete.get(axis, True)
        
        def get_position(self, axis: str) -> int:
            """Get current position for given axis."""
            with self.simulator._xy_stage_lock:
                return self.simulator._simulated_xy_position.get(axis, 0)
    
    class _VisualizersContainer:
        """Container for visualizer instances."""
        def __init__(self):
            self.streamer = None
            self.matrix = None

    def _initialize_visualizers(self):
        """Initialize visualizer instances for simulator."""
        try:
            # Initialize MatrixVisualizer for electrode matrix display
            self.visualizers.matrix = MatrixVisualizer(
                box=self,
                window_name="Simulator Matrix Display",
                record_movie=False  # Can be enabled by user
            )
            self.logger.info("MatrixVisualizer initialized for simulator")
        except Exception as e:
            self.logger.error(f"Visualizer initialization failed: {e}")
            self.visualizers.matrix = None

    def _determine_command_priority(self, path: str) -> Priority:
        """Determine command priority based on path."""
        if "emergency" in path.lower() or "stop" in path.lower():
            return Priority.CRITICAL
        elif path.startswith("electrode_matrix."):
            return Priority.HIGH  # Electrode operations are high priority
        else:
            return Priority.MEDIUM
        
    def _process_hardware_command(self, path: str, value: Any, priority: Priority):
        """Process hardware commands for Simulator - handles electrode matrix and XY stage."""
        try:
            if path.startswith("electrode_matrix."):
                return self._process_electrode_command(path, value)
            elif path.startswith("xy_stage."):
                return self._process_xy_stage_command(path, value)
            else:
                self.logger.warning(f"Simulator only supports electrode_matrix and xy_stage commands. Ignoring: {path}")
                return False
        except Exception as e:
            self.logger.error(f"Hardware command failed for {path}: {e}")
            return False
            
    def _process_electrode_command(self, path: str, value: Any) -> bool:
        """Process electrode matrix commands in simulation."""
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            with self._electrode_lock:
                if param_name == "voltage":
                    voltage = int(value)
                    self._simulated_voltage = voltage
                    # self.logger.debug(f"Electrode voltage set to {voltage}V")
                    return True
                    
                elif param_name == "matrix":
                    matrix = value
                    if isinstance(matrix, np.ndarray):
                        matrix = matrix.astype(int).tolist()
                    
                    # Convert to numpy array for simulation
                    matrix_array = np.array(matrix, dtype=int)
                    self._simulated_matrix = matrix_array

                    # Count active electrodes for feedback
                    active_count = np.sum(matrix_array > 0)
                    # self.logger.debug(f"Electrode matrix updated - {active_count} active electrodes")
                    return True
                    
        except Exception as e:
            # self.logger.error(f"Electrode command failed: {e}")
            return False
            
        return False
    
    def _process_xy_stage_command(self, path: str, value: Any) -> bool:
        """Process XY stage commands in simulation."""
        try:
            path_parts = path.split('.')
            
            if path_parts[1] == "position":
                # Handle absolute positioning
                with self._xy_stage_lock:
                    if isinstance(value, dict):
                        # Multiple axes: {"X": 1000, "Y": 2000, "Z": 3000}
                        for axis, position in value.items():
                            self._simulated_xy_position[axis] = int(position)
                            self._xy_motion_complete[axis] = False
                            # Simulate motion completion after short delay
                            threading.Timer(0.1, self._complete_motion, args=(axis,)).start()
                        self.logger.debug(f"XY stage moved to {value}")
                    else:
                        # Single axis: xy_stage.position.X
                        axis = path_parts[2]
                        position = int(value)
                        self._simulated_xy_position[axis] = position
                        self._xy_motion_complete[axis] = False
                        # Simulate motion completion after short delay
                        threading.Timer(0.1, self._complete_motion, args=(axis,)).start()
                        self.logger.debug(f"XY stage axis {axis} moved to {position}")
                return True
                
            elif path_parts[1] == "continuous_movement":
                # Handle continuous movement (just log it, don't actually move)
                axis = path_parts[2]
                direction = int(value)
                self.logger.debug(f"XY stage continuous movement: {axis} direction={direction}")
                return True
                
            elif path_parts[1] == "motion_params":
                # Handle motion parameters (just acknowledge)
                self.logger.debug("XY stage motion parameters updated (simulated)")
                return True
                
        except Exception as e:
            self.logger.error(f"XY stage command failed: {e}")
            return False
            
        return False
    
    def _complete_motion(self, axis: str):
        """Mark motion as complete for given axis."""
        with self._xy_stage_lock:
            self._xy_motion_complete[axis] = True
    
    def get_simulated_matrix(self) -> np.ndarray:
        """Get the current simulated electrode matrix state."""
        with self._electrode_lock:
            return self._simulated_matrix.copy()
    
    def get_simulated_voltage(self) -> int:
        """Get the current simulated voltage setting."""
        with self._electrode_lock:
            return self._simulated_voltage
    
    def get_active_electrode_count(self) -> int:
        """Get the number of currently active electrodes."""
        with self._electrode_lock:
            return int(np.sum(self._simulated_matrix > 0))
    
    def get_electrode_state(self, row: int, column: int) -> int:
        """Get the state of a specific electrode (1-indexed coordinates)."""
        with self._electrode_lock:
            if 1 <= row <= self._simulated_matrix.shape[0] and 1 <= column <= self._simulated_matrix.shape[1]:
                return int(self._simulated_matrix[row-1, column-1])
            else:
                raise ValueError(f"Electrode coordinates ({row}, {column}) out of bounds")
    
    def set_electrode_state(self, row: int, column: int, state: int):
        """Set the state of a specific electrode (1-indexed coordinates)."""
        if 1 <= row <= self._simulated_matrix.shape[0] and 1 <= column <= self._simulated_matrix.shape[1]:
            with self._electrode_lock:
                self._simulated_matrix[row-1, column-1] = state
                # Update the state in the DropSystem
                matrix = self._simulated_matrix.tolist()
                self.update_state("electrode_matrix.matrix", matrix)
                # self.logger.debug(f"Electrode ({row}, {column}) set to state {state}")
        else:
            raise ValueError(f"Electrode coordinates ({row}, {column}) out of bounds")
    
    def activate_electrode_pattern(self, pattern_name: str):
        """Activate predefined electrode patterns for testing."""
        rows, cols = self._simulated_matrix.shape
        
        with self._electrode_lock:
            if pattern_name == "all_off":
                self._simulated_matrix.fill(0)
            elif pattern_name == "all_on":
                self._simulated_matrix.fill(1)
            elif pattern_name == "checkerboard":
                for i in range(rows):
                    for j in range(cols):
                        self._simulated_matrix[i, j] = (i + j) % 2
            elif pattern_name == "border":
                self._simulated_matrix.fill(0)
                self._simulated_matrix[0, :] = 1  # Top row
                self._simulated_matrix[-1, :] = 1  # Bottom row
                self._simulated_matrix[:, 0] = 1  # Left column
                self._simulated_matrix[:, -1] = 1  # Right column
            elif pattern_name == "center_cross":
                self._simulated_matrix.fill(0)
                mid_row, mid_col = rows // 2, cols // 2
                self._simulated_matrix[mid_row, :] = 1  # Horizontal line
                self._simulated_matrix[:, mid_col] = 1  # Vertical line
            elif pattern_name == "corners":
                self._simulated_matrix.fill(0)
                self._simulated_matrix[0, 0] = 1      # Top-left
                self._simulated_matrix[0, -1] = 1     # Top-right
                self._simulated_matrix[-1, 0] = 1     # Bottom-left
                self._simulated_matrix[-1, -1] = 1    # Bottom-right
            else:
                self.logger.warning(f"Unknown pattern: {pattern_name}")
                return False
            
            # Update the state in the DropSystem
            matrix = self._simulated_matrix.tolist()
            self.update_state("electrode_matrix.matrix", matrix)
            active_count = np.sum(self._simulated_matrix > 0)
            # self.logger.debug(f"Applied pattern '{pattern_name}' - {active_count} active electrodes")
            return True
    
    def print_matrix_summary(self):
        """Print a summary of the current matrix state."""
        with self._electrode_lock:
            rows, cols = self._simulated_matrix.shape
            active_count = np.sum(self._simulated_matrix > 0)
            total_count = rows * cols
            
            self.logger.info(f"Matrix Summary: Size={rows}x{cols} ({total_count} total), Active={active_count}, Voltage={self._simulated_voltage}V, Utilization={active_count/total_count*100:.1f}%")
    
    def close(self):
        """Close the simulator."""
        if getattr(self, "_closed", False):
            return

        self._closed = True
        self.logger.info("Closing Simulator")

        # Close visualizers
        if hasattr(self, 'visualizers') and self.visualizers:
            if self.visualizers.matrix:
                try:
                    self.visualizers.matrix.stop()
                except Exception as e:
                    self.logger.error(f"Error closing MatrixVisualizer: {e}")

        # Call parent close to handle queue cleanup
        super().close()

    def __del__(self):
        self.close()