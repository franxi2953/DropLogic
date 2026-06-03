# DropLogic Hardware Template

This template provides a complete starting point for implementing new DropLogic hardware systems. It captures all the best practices and patterns established in existing implementations like BOXMini and Simulator.

## Quick Start

1. **Copy the template**:
   ```bash
   cp hardware_template.py my_hardware.py
   ```

2. **Rename the class**:
   ```python
   class MyHardware(HardwareTemplate):  # Replace HardwareTemplate
   ```

3. **Customize for your hardware** (see sections below)

4. **Test your implementation**:
   ```python
   hardware = MyHardware()
   hardware.visualizers.matrix.start()  # Test matrix visualization
   ```

## Template Structure

### Core Components

- **DropSystem Base Class**: Queue-based command processing, state management, logging
- **Hardware Modules**: Camera, microscope, XY stage, electrode matrix, temperature
- **Visualizers**: Automatic setup of MatrixVisualizer and StreamerVisualizer
- **AdvancedDrop**: Built-in SIPP planning and execution capabilities (initialized after visualizers)

### Key Files

- `hardware_template.py` - Main template file
- `README.md` - This documentation

## Implementation Guide

### 1. Basic Setup

```python
class MyHardware(HardwareTemplate):
    def __init__(self, config_file="config.json"):
        # Call parent constructor with your hardware name
        super().__init__(config_file)

        # Add your custom initialization here
        self.my_custom_module = MyCustomModule(self)
```

### 2. Hardware Module Initialization

Replace the placeholder comments with your actual hardware initialization:

```python
# In __init__, replace the "ADD YOUR HARDWARE MODULES HERE" section:

# Example for a system with camera and XY stage
self.camera = CameraModule(self, self.state.get("camera_settings", {}).get("version", "CameraV1"))
self.xy_stage = XYStageModule(self, self.state.get("xy_stage", {}).get("version", "XYStageV1"))
self.electrode_matrix = ElectrodeMatrixModule(
    self, None, 128, 128, version="MyDMFVersion"
)
```

### 3. Serial/USB Connections

If your hardware uses serial or USB connections:

```python
def initialize_serial(self):
    """Initialize serial connections for your hardware."""
    self.logger.info("Initializing serial connections")

    # Example serial initialization
    try:
        self.device_serial = serial.Serial("COM1", baudrate=9600)
        self.logger.info("Serial connections initialized successfully")
    except Exception as e:
        self.logger.error(f"Failed to initialize serial: {e}")
        raise
```

### 4. Command Processing

Add routing for your hardware-specific commands:

```python
def _process_hardware_command(self, path: str, value: Any, priority: Priority):
    try:
        if path.startswith("electrode_matrix."):
            return self._process_electrode_command(path, value)
        elif path.startswith("my_device."):
            return self._process_my_device_command(path, value)
        else:
            self.logger.warning(f"Unknown command path: {path}")
            return False
    except Exception as e:
        self.logger.error(f"Hardware command failed: {e}")
        return False

def _process_my_device_command(self, path: str, value: Any) -> bool:
    """Process commands for your custom hardware."""
    path_parts = path.split('.')
    param_name = path_parts[1]

    if param_name == "setting":
        # Implement your setting logic
        return True

    return False
```

### 5. Configuration Integration

Initialize hardware with config values:

```python
def _initialize_hardware_from_config(self):
    """Initialize hardware modules with values from config.json."""
    try:
        # Camera settings
        if self.camera:
            cam_settings = self.state.get("camera_settings", {})
            ae = bool(cam_settings.get("auto_exposure", False))
            self.camera.set_exposure_auto(ae)
            if not ae:
                exp = float(cam_settings.get("exposure_time", 10000))
                self.camera.set_parameter("float_value", "ExposureTime", exp)

        # XY Stage settings
        if self.xy_stage:
            params = self.state.get("xy_stage", {}).get("motion_params", {})
            self.xy_stage.set_params(params)

        self.logger.info("Hardware initialized from config")

    except Exception as e:
        self.logger.error(f"Hardware initialization failed: {e}")
```

### 6. Cleanup and Resource Management

Ensure proper cleanup in the `close()` method:

```python
def close(self):
    """Clean shutdown of hardware."""
    if getattr(self, "_closed", False):
        return

    self._closed = True
    self.logger.info("Closing MyHardware")

    # Close your custom modules
    if hasattr(self, 'my_custom_module') and self.my_custom_module:
        try:
            self.my_custom_module.close()
        except Exception as e:
            self.logger.error(f"Error closing my_custom_module: {e}")

    # Call parent close (handles visualizers and queue cleanup)
    super().close()
```

## Built-in Features

### Visualizers

Automatically available based on hardware:

```python
# Matrix visualizer (always available for DMF systems)
hardware.visualizers.matrix.start()

# Stream visualizer (only if camera/microscope available)
if hardware.visualizers.streamer:
    hardware.visualizers.streamer.start()
```

### Advanced Drop Functionality

Full SIPP planning and execution included:

```python
# Create droplets
hardware.advanced_drop.create_droplet(1, (10, 10), (100, 100))

# Plan and execute
plan = hardware.advanced_drop.plan_sipp()
stats = hardware.advanced_drop.execute_plan(
    visualizer=hardware.visualizers.matrix,
    show_paths=True
)
```

## Complete Example

```python
from droplogic.hardware.template.hardware_template import HardwareTemplate

class MyDMFSystem(HardwareTemplate):
    """My custom DMF system implementation."""

    def __init__(self, config_file="my_config.json"):
        super().__init__(config_file)

        # Custom hardware initialization
        self.custom_controller = CustomController(self)

    def _process_hardware_command(self, path: str, value: Any, priority):
        if path.startswith("custom."):
            return self._process_custom_command(path, value)
        else:
            return super()._process_hardware_command(path, value)

    def _process_custom_command(self, path: str, value: Any) -> bool:
        # Implement custom command processing
        return True

# Usage
system = MyDMFSystem()
system.visualizers.matrix.start()
system.advanced_drop.plan_sipp()
```

## Best Practices

1. **Follow the naming conventions** used in existing implementations
2. **Use appropriate logging levels** for debugging and monitoring
3. **Handle exceptions gracefully** in hardware operations
4. **Test with the simulator first** before hardware integration
5. **Document your hardware-specific parameters** in config.json
6. **Implement proper error recovery** for hardware communication failures

## Testing

Test your implementation with the provided simulation script:

```bash
python sipp_simulation.py  # Uses Simulator by default
```

Then test with your hardware:

```python
hardware = MyHardware()
# Test basic functionality
hardware.visualizers.matrix.start()
# Test advanced features
hardware.advanced_drop.create_droplet(1, (0, 0), (127, 127))
plan = hardware.advanced_drop.plan_sipp()
```

## Reference Implementations

- **BOXMini** (`box_mini1.py`): Full hardware with camera, microscope, XY stage
- **Simulator** (`simulator.py`): Simulation-only with electrode matrix
- **DMLite** (`DMLite.py`): Another hardware implementation example

Study these for real-world implementation patterns.