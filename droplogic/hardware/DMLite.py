from ..base import DropSystem, Priority
from typing import Any
from .modules.electrode_matrix import ElectrodeMatrixModule
from ..utils.advanced_drop import AdvancedDrop
from ..utils.visualizer import MatrixVisualizer
import numpy as np
import threading
import logging
import platform

class DMLite(DropSystem):
    """Represents a lightweight version of the DropSystem hardware system focused only on the electrode matrix."""

    _instance = None
    _hardware_sync_stop = threading.Event()
    
    def __new__(cls, config_file="config.json", log_level=logging.INFO):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_file="config.json", log_level=logging.INFO):
        if isinstance(log_level, str):
            log_level = getattr(logging, log_level.upper(), logging.INFO)

        if platform.system() == "Darwin":
            type(self)._instance = None
            raise RuntimeError(
                "DMLite native hardware control is currently Windows-only because "
                "the Acxel SDK is distributed as Windows DLLs. macOS support is a "
                "placeholder for now; use Simulator on macOS or run DMLite from Windows."
            )

        if hasattr(self, "_initialized") and self._initialized:
            self.logger.setLevel(log_level)
            for handler in self.logger.handlers:
                handler.setLevel(log_level)
            from ..utils.logging_config import set_droplogic_logging_level
            set_droplogic_logging_level(log_level)
            return  # Already initialized

        super().__init__("DMLite", state_file=config_file, log_level=log_level)
        self.logger.info("DMLite initialization started")

        # Initialize electrode matrix from state
        electrode_config = self.state.get("electrode_matrix", {})
        rows = electrode_config.get("rows", 128)
        columns = electrode_config.get("columns", 128)
        electrode_config["matrix"] = np.zeros((rows, columns))
        version = electrode_config.get("version", "DMLite")

        # Define lock for electrode matrix
        self._electrode_matrix_lock = threading.Lock()

        # Initialize electrode matrix module
        self.electrode_matrix = ElectrodeMatrixModule(
            self,
            None,
            rows, columns,
            version=version,
            debug=False
        )

        # Initialize matrix as a 0 matrix
        matrix = np.zeros((rows, columns), int).tolist()
        self.update_state("electrode_matrix.matrix", matrix)

        self._initialized = True
        self.logger.info("DMLite initialized successfully")
        
        # Initialize electrode matrix with config voltage
        voltage = int(self.state.get("electrode_matrix", {}).get("voltage", 40))
        self.electrode_matrix.set_voltage([voltage] * 9)
        self.logger.info(f"Electrode matrix initialized with voltage: {voltage}V")

        # Initialize visualizers namespace
        self.visualizers = self._VisualizersContainer()
        self._initialize_visualizers()

        # Initialize advanced drop functionality after visualizers setup
        self.advanced_drop = AdvancedDrop(self)

    def _determine_command_priority(self, path: str) -> Priority:
        """DMLite-specific command priority assignment - only electrode matrix."""
        if "emergency" in path.lower() or "stop" in path.lower():
            return Priority.CRITICAL
        elif path.startswith("electrode_matrix."):
            return Priority.HIGH  # Electrode operations are high priority for DMLite
        else:
            return Priority.MEDIUM
    
    def _process_hardware_command(self, path: str, value: Any, priority: Priority):
        """Process hardware commands for DMLite - only electrode matrix commands."""
        try:
            if path.startswith("electrode_matrix."):
                return self._process_electrode_command(path, value)
            else:
                self.logger.warning(f"DMLite only supports electrode_matrix commands, got: {path}")
                return False
        except Exception as e:
            self.logger.error(f"DMLite hardware command failed for {path}: {e}")
            return False
    
    def _process_electrode_command(self, path: str, value: Any) -> bool:
        """Process electrode matrix commands for DMLite."""
        if not self.electrode_matrix:
            return False
            
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            with self._electrode_matrix_lock:
                if param_name == "voltage":
                    voltage = int(value)
                    self.electrode_matrix.set_voltage([voltage] * 9)
                    return True
                    
                elif param_name == "matrix":
                    matrix = value
                    if isinstance(matrix, np.ndarray):
                        matrix = matrix.astype(int).tolist()
                    
                    # Convert to binary matrix for DMLite
                    matrix_bin = [[1 if v in (1, 2) else 0 for v in row] for row in matrix]
                    self.electrode_matrix.set_chip(matrix_bin)
                    return True
                    
        except Exception as e:
            self.logger.error(f"Electrode command failed: {e}")
            return False
            
        return False

    class _VisualizersContainer:
        """Container for visualizer instances."""
        def __init__(self):
            self.streamer = None
            self.matrix = None

    def _initialize_visualizers(self):
        """Initialize visualizer instances for DMLite."""
        try:
            # Initialize MatrixVisualizer for electrode matrix display
            self.visualizers.matrix = MatrixVisualizer(
                box=self,
                window_name="DMLite Matrix Display",
                record_movie=False  # Can be enabled by user
            )
            self.logger.info("MatrixVisualizer initialized for DMLite")

            # No StreamerVisualizer for DMLite (no camera/microscope)
            self.visualizers.streamer = None

        except Exception as e:
            self.logger.error(f"Visualizer initialization failed: {e}")
            self.visualizers.matrix = None

    def on_state_updated(self):
        """Called when state is updated - parent queue system handles everything."""
        pass
    
    def close(self):
        if getattr(self, "_closed", False):
            return

        self._closed = True

        logger = getattr(self, "logger", None)
        if logger:
            logger.info("Closing hardware modules")

        electrode_matrix = getattr(self, "electrode_matrix", None)
        if electrode_matrix:
            try:
                electrode_matrix.close()
            except Exception as e:
                if logger:
                    logger.error(f"Error closing electrode matrix module: {e}")

        # Close visualizers
        if hasattr(self, 'visualizers') and self.visualizers:
            if self.visualizers.matrix:
                try:
                    self.visualizers.matrix.stop()
                except Exception as e:
                    if logger:
                        logger.error(f"Error closing MatrixVisualizer: {e}")

        # Parent class handles queue cleanup
        if hasattr(self, "_queue_stop_event"):
            super().close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
