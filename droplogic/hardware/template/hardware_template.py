"""
DropSystem Hardware Template

This template provides the structure for implementing new DropSystem hardware systems.
Copy this file and customize it for your specific hardware implementation.

Key Components to Implement:
1. Hardware module initialization (camera, microscope, xy_stage, etc.)
2. Visualizer setup based on available hardware
3. Hardware-specific command processing
4. Proper cleanup and resource management

Example implementations: BOXMini, Simulator, DMLite
"""

from ..base import DropSystem, Priority
from typing import Any
from ..utils.advanced_drop import AdvancedDrop
from ..utils.visualizer import StreamerVisualizer, MatrixVisualizer
import numpy as np
import threading
import time


class HardwareTemplate(DropSystem):
    """
    Template for new DropSystem hardware implementations.

    Replace 'HardwareTemplate' with your hardware name (e.g., 'DMLite', 'CustomHardware').
    Implement the required methods and customize hardware initialization.
    """

    _instance = None

    def __new__(cls, config_file="config.json"):
        """Singleton pattern - modify if not needed for your hardware."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_file="config.json"):
        """Initialize your hardware system."""
        if hasattr(self, "_initialized") and self._initialized:
            return  # Already initialized

        # Initialize base DropSystem with your hardware name
        super().__init__("HardwareTemplate", state_file=config_file)
        self.logger.info("HardwareTemplate initialization started")

        # ===== HARDWARE-SPECIFIC INITIALIZATION =====
        # Initialize your hardware modules here
        # Example: camera, microscope, xy_stage, electrode_matrix, etc.

        # Initialize electrode matrix (common to all DMF systems)
        electrode_config = self.state.get("electrode_matrix", {})
        rows = electrode_config.get("rows", 128)
        columns = electrode_config.get("columns", 128)
        voltage = electrode_config.get("voltage", 40)

        # Initialize matrix as zeros in state
        matrix = np.zeros((rows, columns), int).tolist()
        self.update_state("electrode_matrix.matrix", matrix)

        # ===== ADD YOUR HARDWARE MODULES HERE =====
        # Example:
        # self.camera = CameraModule(self, self.state.get("camera_settings", {}).get("version", "CameraV1"))
        # self.microscope = MicroscopeModule(self, self.microscope_serial, ...)
        # self.xy_stage = XYStageModule(self, ...)
        # self.temperature = TemperatureModule(self, ...)
        # etc.

        # Define any hardware-specific locks you need
        self._electrode_matrix_lock = threading.Lock()
        # Add other locks as needed: self._camera_lock, self._microscope_lock, etc.

        # ===== VISUALIZER INITIALIZATION =====
        # Initialize visualizers namespace (required)
        self.visualizers = self._VisualizersContainer()
        self._initialize_visualizers()

        # ===== ADVANCED DROP INITIALIZATION =====
        # Initialize advanced drop functionality after visualizers setup
        self.advanced_drop = AdvancedDrop(self)

        self._initialized = True
        self.logger.info("HardwareTemplate initialized successfully")

    class _VisualizersContainer:
        """Container for visualizer instances."""
        def __init__(self):
            self.streamer = None
            self.matrix = None

    def _initialize_visualizers(self):
        """Initialize visualizer instances based on available hardware."""
        try:
            # MatrixVisualizer is usually available for all DMF systems
            self.visualizers.matrix = MatrixVisualizer(
                box=self,
                window_name="HardwareTemplate Matrix Display",
                record_movie=False  # Can be enabled by user
            )
            self.logger.info("MatrixVisualizer initialized")

            # StreamerVisualizer only if camera/microscope is available
            stream_device = None
            if hasattr(self, 'microscope') and self.microscope:
                stream_device = self.microscope
                self.logger.info("StreamerVisualizer initialized with microscope")
            elif hasattr(self, 'camera') and self.camera:
                stream_device = self.camera
                self.logger.info("StreamerVisualizer initialized with camera")

            if stream_device:
                self.visualizers.streamer = StreamerVisualizer(
                    device=stream_device,
                    window_name="HardwareTemplate Live Stream",
                    box=self  # Pass box for overlay features
                )
                # Enable useful overlays by default
                self.visualizers.streamer.electrode_overlay = True
                self.visualizers.streamer.coordinates = True
            else:
                self.visualizers.streamer = None
                self.logger.info("No camera/microscope available - StreamerVisualizer not initialized")

        except Exception as e:
            self.logger.error(f"Visualizer initialization failed: {e}")
            self.visualizers.matrix = None
            self.visualizers.streamer = None

    def _determine_command_priority(self, path: str) -> Priority:
        """Determine command priority based on path."""
        if "emergency" in path.lower() or "stop" in path.lower():
            return Priority.CRITICAL
        elif path.startswith("electrode_matrix."):
            return Priority.HIGH  # Electrode operations are high priority
        elif path.startswith(("camera", "microscope")):
            return Priority.MEDIUM
        else:
            return Priority.MEDIUM

    def _process_hardware_command(self, path: str, value: Any, priority: Priority):
        """Process hardware commands. Route to appropriate module handlers."""
        try:
            # Route commands to appropriate module processors
            if path.startswith("electrode_matrix."):
                return self._process_electrode_command(path, value)
            # Add your hardware-specific command routing here
            # elif path.startswith("camera."):
            #     return self._process_camera_command(path, value)
            # elif path.startswith("microscope."):
            #     return self._process_microscope_command(path, value)
            # etc.
            else:
                self.logger.warning(f"Unknown command path: {path}")
                return False
        except Exception as e:
            self.logger.error(f"Hardware command failed for {path}: {e}")
            return False

    def _process_electrode_command(self, path: str, value: Any) -> bool:
        """Process electrode matrix commands."""
        if not hasattr(self, 'electrode_matrix') or not self.electrode_matrix:
            return False

        try:
            path_parts = path.split('.')
            param_name = path_parts[1]

            with self._electrode_matrix_lock:
                if param_name == "voltage":
                    voltage = int(value)
                    # Implement your voltage setting logic
                    # self.electrode_matrix.set_voltage(voltage)
                    return True

                elif param_name == "matrix":
                    matrix = value
                    if isinstance(matrix, np.ndarray):
                        matrix = matrix.astype(int).tolist()

                    # Implement your matrix setting logic
                    # matrix_bin = [[1 if v in (1, 2) else 0 for v in row] for row in matrix]
                    # self.electrode_matrix.set_chip(matrix_bin)
                    return True

        except Exception as e:
            self.logger.error(f"Electrode command failed: {e}")
            return False

        return False

    # ===== ADD YOUR HARDWARE-SPECIFIC COMMAND PROCESSORS HERE =====
    # def _process_camera_command(self, path: str, value: Any) -> bool:
    #     """Process camera commands."""
    #     # Implement camera command processing
    #     pass

    # def _process_microscope_command(self, path: str, value: Any) -> bool:
    #     """Process microscope commands."""
    #     # Implement microscope command processing
    #     pass

    # ===== ADD ANY HARDWARE-SPECIFIC METHODS HERE =====
    # def initialize_serial(self):
    #     """Initialize serial connections for your hardware."""
    #     pass

    # def _initialize_hardware_from_config(self):
    #     """Initialize hardware modules with values from config.json."""
    #     pass

    def close(self):
        """Clean shutdown of hardware and resources."""
        if getattr(self, "_closed", False):
            return

        self._closed = True
        self.logger.info("Closing HardwareTemplate")

        # Close hardware modules (add your modules here)
        # for module in [self.camera, self.microscope, self.xy_stage, self.temperature]:
        #     if module:
        #         try:
        #             module.close()
        #         except Exception as e:
        #             self.logger.error(f"Error closing module {module.__class__.__name__}: {e}")

        # Close visualizers
        if hasattr(self, 'visualizers') and self.visualizers:
            if self.visualizers.matrix:
                try:
                    self.visualizers.matrix.stop()
                except Exception as e:
                    self.logger.error(f"Error closing MatrixVisualizer: {e}")

            if self.visualizers.streamer:
                try:
                    self.visualizers.streamer.stop()
                except Exception as e:
                    self.logger.error(f"Error closing StreamerVisualizer: {e}")

        # Close USB/serial resources if any
        # try:
        #     # Dispose USB resources
        #     pass
        # except Exception as e:
        #     self.logger.error(f"Error disposing resources: {e}")

        # Call parent close to handle queue cleanup
        super().close()

    def __del__(self):
        self.close()


# ===== USAGE EXAMPLE =====
"""
# Example of how to use this template for a new hardware implementation:

class MyCustomHardware(HardwareTemplate):
    def __init__(self, config_file="config.json"):
        # Call parent init
        super().__init__(config_file)

        # Add custom initialization here
        self.my_custom_module = MyCustomModule(self)

    def _process_custom_command(self, path: str, value: Any) -> bool:
        # Implement custom command processing
        pass

# Usage:
hardware = MyCustomHardware()
hardware.visualizers.matrix.start()  # Start matrix visualization
hardware.advanced_drop.plan_sipp()   # Use advanced drop functionality
"""