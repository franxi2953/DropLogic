from ..base import DropSystem, Priority
from typing import Any
from ..utils.advanced_drop import AdvancedDrop
from .modules.temperature import TemperatureModule
from .modules.electrode_matrix import ElectrodeMatrixModule
from .modules.capacitive_feedback import CapacitiveFeedbackModule
from .modules.xy_stage import XYStageModule
from .modules.microscope import MicroscopeModule
from .modules.camera import CameraModule
from .modules.light import LightModule
from ..utils.visualizer import StreamerVisualizer, MatrixVisualizer
import numpy as np
import serial
import usb.core
import usb.util
from ctypes import c_char
from .modules.light.versions.helpers.UPLEDController import UPLEDController
import threading
import time
import logging


class BOXMini(DropSystem):
    """Represents the BOXMini hardware system as a singleton."""

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
        
        super().__init__("BOXMini", state_file=config_file, log_level=log_level)
        self.logger.info("BOXMini initialization started")

        # Initialize electrode matrix from state
        electrode_config = self.state.get("electrode_matrix", {})
        rows = electrode_config.get("rows", 128)
        columns = electrode_config.get("columns", 128)
        electrode_config["matrix"] = np.zeros((rows, columns))
        version = electrode_config.get("version", "DMLite")
        voltage = int(electrode_config.get("voltage", 55))

        # Define serial locks
        self._temperature_lock = threading.Lock()
        self._electrode_matrix_lock = threading.Lock()
        self._light_lock = threading.Lock()
        self._microscope_lock = threading.Lock()

        # Initialize serial/USB connections.
        self.initialize_serial()

        # Initialize hardware modules using state.
        light_settings = self.state.get("light_settings", {})
        light_version = light_settings.get("version", "LightV1")
        if light_version == "LightV2":
            self.light = LightModule(self, ring_serial=self.light_serial, coaxial_controller=self.upled, version=light_version)
        else:
            self.light = LightModule(self, ring_serial=self.light_serial, coaxial_controller=None, version=light_version)
        self.electrode_matrix = ElectrodeMatrixModule(
            self,
            None,  # Deprecated argument
            rows, columns,
            version=version,
            initial_voltage=voltage,
            debug=False
        )
        self.capacitive_feedback = CapacitiveFeedbackModule(self, self.state.get("capacitive_feedback", {}).get("version", "CapacitiveFeedbackV1"))
        self.xy_stage = XYStageModule(self, self.state.get("xy_stage", {}).get("version", "XYStageV1"))
        self.microscope = MicroscopeModule(self, self.microscope_serial, self.state.get("microscope_settings", {}).get("version", "MicroscopeV1"))
        self.camera = CameraModule(self, self.state.get("camera_settings", {}).get("version", "CameraV1"))
        self.temperature = TemperatureModule(self, self.temperature_serial, self.state.get("temperature", {}).get("version", "TemperatureV1"))

        #initialize matrix as a 0 matrix
        rows = self.state["electrode_matrix"]["rows"]
        cols = self.state["electrode_matrix"]["columns"]
        matrix = np.zeros((rows, cols), int).tolist()
        self.update_state("electrode_matrix.matrix", matrix)

        # Initialize temperature update thread
        self._temperature_update_thread = None
        self._temperature_update_stop = threading.Event()

        self._initialized = True
        self.logger.info("BOXMini initialized successfully")
        
        # Initialize hardware modules with config values
        self._initialize_hardware_from_config()

        # Initialize visualizers namespace
        self.visualizers = self._VisualizersContainer()
        self._initialize_visualizers()

        # Initialize advanced drop functionality after visualizers setup
        self.advanced_drop = AdvancedDrop(self)

        # Start temperature update thread
        self._start_temperature_update_thread()
        
    def _process_hardware_command(self, path: str, value: Any, priority: Priority):
        """Process hardware commands for BOXMini - routes to specific module processors."""
        try:
            if path.startswith("xy_stage."):
                return self._process_xy_stage_command(path, value)
            elif path.startswith("camera_settings."):
                return self._process_camera_command(path, value)
            elif path.startswith("microscope_settings."):
                return self._process_microscope_command(path, value)
            elif path.startswith("electrode_matrix."):
                return self._process_electrode_command(path, value)
            elif path.startswith("temperature."):
                return self._process_temperature_command(path, value)
            elif path.startswith("light_settings."):
                return self._process_light_command(path, value)
            else:
                self.logger.warning(f"Unknown command path: {path}")
                return False
        except Exception as e:
            self.logger.error(f"Hardware command failed for {path}: {e}")
            return False
        
    # Individual Command Processors
    def _process_xy_stage_command(self, path: str, value: Any) -> bool:
        """Process XY stage commands."""
        if not self.xy_stage:
            return False
            
        try:
            path_parts = path.split('.')
            
            if path_parts[1] == "continuous_movement":
                # Handle continuous movement: xy_stage.continuous_movement.X/Y/Z
                axis = path_parts[2]
                direction = int(value)
                if direction == 0:
                    self.xy_stage.stop_continuous_movement(axis)
                else:
                    self.xy_stage.start_continuous_movement(axis, direction)
                return True
                
            elif path_parts[1] == "position":
                # Handle absolute positioning: xy_stage.position
                if isinstance(value, dict):
                    # Multiple axes: {"X": 1000, "Y": 2000, "Z": 3000}
                    for axis, position in value.items():
                        retries = 0
                        while retries < 10:
                            if self.xy_stage.move_axis_to_position(axis, position):
                                break
                            retries += 1
                            time.sleep(0.1)
                        if retries == 10:
                            self.logger.error(f"Failed to move {axis} to {position} after 10 retries")
                            return False
                else:
                    # Single axis: xy_stage.position.X
                    axis = path_parts[2]
                    position = value
                    retries = 0
                    while retries < 10:
                        if self.xy_stage.move_axis_to_position(axis, position):
                            break
                        retries += 1
                        time.sleep(0.1)
                    if retries == 10:
                        self.logger.error(f"Failed to move {axis} to {position} after 10 retries")
                        return False
                return True
                
            elif path_parts[1] == "motion_params":
                # Handle motion parameters: xy_stage.motion_params.dMaxV/dMaxA
                current_params = self._state.get("xy_stage", {}).get("motion_params", {})
                self.xy_stage.set_params(current_params)
                return True
                
        except Exception as e:
            self.logger.error(f"XY stage command failed: {e}")
            return False
            
        return False
        
    def _process_camera_command(self, path: str, value: Any) -> bool:
        """Process camera commands."""
        if not self.camera:
            return False
            
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            if param_name == "auto_exposure":
                self.camera.set_exposure_auto(bool(value))
                return True
            elif param_name == "exposure_time":
                # Only set if not in auto exposure mode
                if not self._state.get("camera_settings", {}).get("auto_exposure", False):
                    self.camera.set_parameter("float_value", "ExposureTime", float(value))
                return True
            elif param_name == "gain":
                gain = max(0, min(23.9, float(value)))
                self.camera.set_parameter("float_value", "Gain", gain)
                return True
                
        except Exception as e:
            self.logger.error(f"Camera command failed: {e}")
            return False
            
        return False
        
    def _process_microscope_command(self, path: str, value: Any) -> bool:
        """Process microscope commands."""
        if not self.microscope:
            return False
            
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            if param_name == "auto_exposure":
                self.microscope.set_exposure_auto(bool(value))
                return True
            elif param_name == "exposure_time":
                # Only set if not in auto exposure mode
                if not self._state.get("microscope_settings", {}).get("auto_exposure", False):
                    self.microscope.set_parameter("float_value", "ExposureTime", float(value))
                return True
            elif param_name == "gain":
                gain = max(0, min(12, float(value)))
                self.microscope.set_parameter("float_value", "Gain", gain)
                return True
            elif param_name == "current_channel":
                channel = value
                if channel in ["FAM", "Brightfield"]:
                    self.microscope.set_channel(channel)
                    return True
                else:
                    self.logger.warning(f"Unknown microscope channel: {channel}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Microscope command failed: {e}")
            return False
            
        return False
        
    def _process_electrode_command(self, path: str, value: Any) -> bool:
        """Process electrode matrix commands."""
        if not self.electrode_matrix:
            return False
            
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            with self._electrode_matrix_lock:
                if param_name == "voltage":
                    voltage = int(value)
                    retries = 10
                    while retries > 0:
                        try:
                            self.electrode_matrix.set_voltage(voltage)
                            return True
                        except Exception as e:
                            if "operation timeout" in str(e).lower():
                                self.logger.warning(f"Voltage timeout, retrying... ({10 - retries + 1}/10)")
                                time.sleep(1)
                                retries -= 1
                            else:
                                raise
                    self.logger.error("Voltage update failed after 10 attempts")
                    return False
                    
                elif param_name == "matrix":
                    matrix = value
                    if isinstance(matrix, np.ndarray):
                        matrix = matrix.astype(int).tolist()
                        
                    retries = 10
                    while retries > 0:
                        try:
                            matrix_bin = [[1 if v in (1, 2) else 0 for v in row] for row in matrix]
                            self.electrode_matrix.set_chip(matrix_bin)
                            return True
                        except Exception as e:
                            if "operation timeout" in str(e).lower():
                                self.logger.warning(f"Matrix timeout, retrying... ({10 - retries + 1}/10)")
                                time.sleep(1)
                                retries -= 1
                            else:
                                raise
                    self.logger.error("Matrix update failed after 10 attempts")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Electrode command failed: {e}")
            return False
            
        return False
        
    def _process_temperature_command(self, path: str, value: Any) -> bool:
        """Process temperature commands."""
        if not self.temperature:
            return False
            
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            with self._temperature_lock:
                if param_name == "target":
                    target_temp = value
                    if target_temp is not None and target_temp != -1:
                        self.temperature.set_temperature(float(target_temp))
                        return True
                        
        except Exception as e:
            self.logger.error(f"Temperature command failed: {e}")
            return False
            
        return False
        
    def _process_light_command(self, path: str, value: Any) -> bool:
        """Process light commands."""
        if not self.light:
            return False
            
        try:
            path_parts = path.split('.')
            param_name = path_parts[1]
            
            with self._light_lock:
                if param_name == "coaxial_intensity":
                    self.light.set_coaxial_light(int(value))
                    return True
                elif param_name == "ring_intensity":
                    self.light.set_ring_light(int(value))
                    return True
                    
        except Exception as e:
            self.logger.error(f"Light command failed: {e}")
            return False
            
        return False

    # Initialize serial connections
    def initialize_serial(self):
        self.logger.info("Initializing serial connections")
        try:
            # Use individual locks for different serial devices
            with self._temperature_lock:
                temp_version = self.state.get("temperature", {}).get("version", "TemperatureV1")
                if temp_version == "TemperatureV2":
                    self.temperature_serial = None  # TemperatureV2 opens its own serial
                else:
                    temp_port = self.state["temperature"]["Port"]
                    self.temperature_serial = serial.Serial(temp_port, baudrate=9600)

            with self._light_lock:
                # Check light version to handle different initialization
                light_version = self.state.get("light_settings", {}).get("version", "LightV1")
                if light_version == "LightV2":
                    # For LightV2, initialize both ring light USB serial AND coaxial UPLED
                    
                    # Initialize ring light USB serial connection
                    self.logger.info("Initializing ring light USB serial for LightV2")
                    try:
                        light_vid = int(self.state["light_settings"]["VID"], 16)
                        light_pid = int(self.state["light_settings"]["PID"], 16)
                        self.light_serial = usb.core.find(idVendor=light_vid, idProduct=light_pid)
                        if self.light_serial is None:
                            self.logger.error("Ring light USB device not found")
                        else:
                            self.logger.info("Ring light USB serial initialized successfully")
                    except Exception as e:
                        self.logger.error(f"Failed to initialize ring light USB serial: {e}")
                        self.light_serial = None
                    # Initialize UPLED for coaxial light
                    self.logger.info("Initializing UPLED for coaxial light (LightV2)")
                    try:
                        self.upled = UPLEDController()
                        device_count = self.upled.find_devices()
                        if device_count:
                            led_index = 0
                            upName = (c_char * 256)()
                            self.upled.lib.TLUP_getRsrcName(0, led_index, upName)
                            resource_name = upName.value.decode()
                            self.logger.info(f"LED resource name: {resource_name}")
                            res = self.upled.connect_device(0)
                            self.logger.info(f"LED connect result: {res}")
                            if res != 0:
                                self.logger.warning(f"Failed to connect to LED, error {res}")
                            else:
                                if not self.upled.is_upled():
                                    self.logger.warning("Connected LED device is not recognized as upLED")
                                # Set setpoint source to internal
                                self.upled.set_led_current_setpoint_source(0)
                                setpoint_source = self.upled.get_led_current_setpoint_source()
                                self.logger.info(f"LED setpoint source set to: {setpoint_source}")
                                
                                # Get and set current limit
                                current_limit = 0.35  # Default to 0.35 A if not retrievable
                                self.logger.info(f"LED factory current limit: {current_limit} A")
                                if current_limit > 0:
                                    self.upled.set_led_current_limit_user(current_limit)
                                    self.logger.info(f"Set LED current limit to: {current_limit} A")
                                
                                # Check operating mode
                                op_mode, op_desc = self.upled.get_op_mode()
                                self.logger.info(f"LED operating mode: {op_mode} - {op_desc}")
                                
                                if current_limit == 0.0:
                                    self.led_limit = 1.2
                                else:
                                    self.led_limit = current_limit
                                self.logger.info(f"Using LED current limit: {self.led_limit} A")
                        else:
                            self.logger.error("No LED devices found for coaxial light")
                            self.led_limit = 1.2
                    except Exception as e:
                        self.logger.error(f"Failed to initialize UPLED: {e}")
                        self.upled = None
                        self.led_limit = 1.2
                else:
                    light_vid = int(self.state["light_settings"]["VID"], 16)
                    light_pid = int(self.state["light_settings"]["PID"], 16)
                    self.light_serial = usb.core.find(idVendor=light_vid, idProduct=light_pid)

            with self._microscope_lock:
                microscope_port = self.state["microscope_settings"]["Port"]
                self.microscope_serial = serial.Serial(microscope_port, baudrate=9600)

            # No need to initialize anything for electrode matrix as the DropSystem DLL (loaded directly on the class) 
            # is the one initializing the serial automatically

            self.logger.info("Serial connections initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize serial connections: {e}")
            raise

    def _state_monitor_loop(self):
        """Lightweight state monitoring loop for position and temperature feedback."""
        while not all([
            hasattr(self, "camera"),
            hasattr(self, "microscope"),
            hasattr(self, "electrode_matrix"),
            hasattr(self, "temperature"),
            hasattr(self, "light"),
            hasattr(self, "xy_stage"),
            hasattr(self, "capacitive_feedback"),
        ]):
            time.sleep(1)  # Wait until all modules are properly assigned

        # Track continuous movement state for faster updates
        continuous_movement_active = False

        while not self._monitor_stop.is_set():
            try:
                # Check if continuous movement is active (any axis has non-zero movement)
                current_continuous_movement = any(
                    self._state.get("xy_stage", {}).get("continuous_movement", {}).get(axis, 0) != 0
                    for axis in ["X", "Y", "Z"]
                )

                # Update position feedback (non-blocking)
                if self.xy_stage:
                    for axis in ["X", "Y", "Z"]:
                        try:
                            current_pos = self.xy_stage.get_position(axis)
                            if current_pos is not None:
                                self._state["xy_stage"]["position"][axis] = current_pos
                        except Exception:
                            # Skip position update on error
                            pass

                # Update temperature feedback (non-blocking)
                if self.temperature:
                    try:
                        current_temp = self.temperature.get_temperature()
                        if current_temp is not None:
                            self._state["temperature"]["current"] = current_temp
                    except Exception:
                        # Skip temperature update on error
                        pass

                # Adjust update frequency based on continuous movement
                if current_continuous_movement:
                    # Faster updates during continuous movement (10ms)
                    self._monitor_stop.wait(0.01)
                else:
                    # Normal updates when stationary (50ms)
                    self._monitor_stop.wait(0.05)

            except Exception as e:
                self.logger.error(f"State monitor error: {e}")
                self._monitor_stop.wait(0.05)  # Default to 50ms on error

    def _initialize_hardware_from_config(self):
        """Initialize hardware modules with values from config.json."""
        try:
            # Initialize XY Stage with motion parameters
            if self.xy_stage:
                params = self.state.get("xy_stage", {}).get("motion_params", {})
                self.xy_stage.set_params(params)
                self.logger.info(f"XY Stage initialized with params: {params}")
                
            # Initialize Camera with config values
            if self.camera:
                cam_settings = self.state.get("camera_settings", {})
                ae = bool(cam_settings.get("auto_exposure", False))
                self.camera.set_exposure_auto(ae)
                if not ae:
                    exp = float(cam_settings.get("exposure_time", 0))
                    self.camera.set_parameter("float_value", "ExposureTime", exp)
                gain = max(0, min(23.9, float(cam_settings.get("gain", 0))))
                self.camera.set_parameter("float_value", "Gain", gain)
                self.logger.info(f"Camera initialized: auto_exposure={ae}, exposure={exp if not ae else 'auto'}, gain={gain}")
                
            # Initialize Microscope with config values
            if self.microscope:
                mic_settings = self.state.get("microscope_settings", {})
                ae = bool(mic_settings.get("auto_exposure", False))
                self.microscope.set_exposure_auto(ae)
                if not ae:
                    exp = float(mic_settings.get("exposure_time", 0))
                    self.microscope.set_parameter("float_value", "ExposureTime", exp)
                gain = max(0, min(12, float(mic_settings.get("gain", 0))))
                self.microscope.set_parameter("float_value", "Gain", gain)
                
                # Set channel from config
                channel = mic_settings.get("current_channel", "Brightfield")
                self.microscope.set_channel(channel)
                self.logger.info(f"Microscope initialized: auto_exposure={ae}, exposure={exp if not ae else 'auto'}, gain={gain}, channel={channel}")
                
            # Initialize Electrode Matrix with config voltage
            if self.electrode_matrix:
                voltage = int(self.state.get("electrode_matrix", {}).get("voltage", 55))
                self.electrode_matrix.set_voltage(voltage)
                self.logger.info(f"Electrode matrix initialized with voltage: {voltage}V")
                
            # Initialize Light with config values
            if self.light:
                light_settings = self.state.get("light_settings", {})
                coaxial = light_settings.get("coaxial_intensity", 0)
                ring = light_settings.get("ring_intensity", 0)
                self.light.set_coaxial_light(coaxial)
                self.light.set_ring_light(ring)
                self.logger.info(f"Light initialized: coaxial={coaxial}, ring={ring}")
                
        except Exception as e:
            self.logger.error(f"Hardware initialization failed: {e}")

    class _VisualizersContainer:
        """Container for visualizer instances."""
        def __init__(self):
            self.streamer = None
            self.matrix = None

    def _initialize_visualizers(self):
        """Initialize visualizer instances for live streaming and matrix display."""
        try:
            # Initialize MatrixVisualizer for electrode matrix display
            self.visualizers.matrix = MatrixVisualizer(
                box=self,
                window_name="BOXMini Matrix Display",
                record_movie=False  # Can be enabled by user
            )
            self.logger.info("MatrixVisualizer initialized")

            # Initialize StreamerVisualizer for live camera/microscope streaming
            # Prefer camera over microscope for better quality
            stream_device = None
            if self.microscope:
                stream_device = self.microscope
                self.logger.info("StreamerVisualizer initialized with microscope")
            elif self.camera:
                stream_device = self.camera
                self.logger.info("StreamerVisualizer initialized with camera")
            
            if stream_device:
                self.visualizers.streamer = StreamerVisualizer(
                    device=stream_device,
                    window_name="BOXMini Live Stream",
                    box=self  # Pass box for overlay features
                )
                # Enable electrode overlay and coordinates by default
                self.visualizers.streamer.electrode_overlay = True
                self.visualizers.streamer.coordinates = False
                # Note: Streamer visualizer is no longer auto-started here
                # Users can start it manually when needed
                self.logger.info("StreamerVisualizer initialized (not started)")
            else:
                self.visualizers.streamer = None
                self.logger.info("No camera/microscope available - StreamerVisualizer not initialized")

        except Exception as e:
            self.logger.error(f"Visualizer initialization failed: {e}")
            self.visualizers.matrix = None
            self.visualizers.streamer = None

    def on_state_updated(self):
        """Called when state is updated - no longer needs to do anything as queue system handles updates."""
        pass

    def _start_temperature_update_thread(self):
        """Start the background thread for updating temperature state."""
        self._temperature_update_stop.clear()
        self._temperature_update_thread = threading.Thread(
            target=self._temperature_update_loop,
            name="TemperatureUpdateThread",
            daemon=True
        )
        self._temperature_update_thread.start()
        self.logger.debug("Temperature update thread started")

    def _temperature_update_loop(self):
        """Background loop to periodically update temperature state."""
        while not self._temperature_update_stop.is_set():
            try:
                if self.temperature:
                    temp = self.temperature.get_temperature()
                    if temp is not None:
                        self.update_state("temperature.current", temp)
            except Exception as e:
                self.logger.debug(f"Error updating temperature state: {e}")
            time.sleep(1.0)  # Update every second
    
    def close(self):
        if getattr(self, "_closed", False):
            # Already closed, so skip closing again.
            return

        self._closed = True

        # Clear the singleton instance so a new one can be created
        BOXMini._instance = None

        # Stop temperature update thread
        if self._temperature_update_thread and self._temperature_update_thread.is_alive():
            self._temperature_update_stop.set()
            self._temperature_update_thread.join(timeout=2.0)
            self.logger.debug("Temperature update thread stopped")

        # Close visualizers first so movie writers flush before their camera/microscope disappears.
        if hasattr(self, 'visualizers') and self.visualizers:
            if self.visualizers.matrix:
                try:
                    self.visualizers.matrix.stop()
                    time.sleep(1.0)
                except Exception as e:
                    self.logger.debug(f"Error closing MatrixVisualizer: {e}")

            if self.visualizers.streamer:
                try:
                    self.visualizers.streamer.stop()
                    time.sleep(1.0)
                except Exception as e:
                    self.logger.debug(f"Error closing StreamerVisualizer: {e}")

        self.logger.info("Closing hardware modules")
        for module in [self.temperature, self.electrode_matrix, self.xy_stage,
                self.microscope, self.camera, self.light]:
            if module:
                try:
                    module.close()
                except Exception as e:
                    self.logger.debug(f"Error closing module {module.__class__.__name__}: {e}")

        # Close UPLED
        if hasattr(self, 'upled') and self.upled:
            try:
                self.upled.close()
                self.logger.debug("UPLED closed")
            except Exception as e:
                self.logger.debug(f"Error closing UPLED: {e}")

        # Close serial ports
        try:
            if hasattr(self, 'temperature_serial') and self.temperature_serial:
                self.temperature_serial.close()
                self.logger.debug("Temperature serial port closed")
            if hasattr(self, 'microscope_serial') and self.microscope_serial:
                self.microscope_serial.close()
                self.logger.debug("Microscope serial port closed")
        except Exception as e:
            self.logger.debug(f"Error closing serial ports: {e}")

        self.logger.debug("Disposing USB resources")
        try:
            # Dispose USB resources for light
            if hasattr(self, "light_serial") and self.light_serial:
                usb.util.dispose_resources(self.light_serial)
        except Exception as e:
            self.logger.debug(f"Error disposing USB resources: {e}")

        # Call parent close to handle queue cleanup
        super().close()

    def __del__(self):
        self.close()
