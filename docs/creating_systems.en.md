# Creating Hardware Systems

This guide provides a complete starting point for implementing new DropLogic hardware systems. It captures all the best practices and patterns established in existing implementations like `BOXMini`, `Simulator`, and `DMLite`.

## Quick Start

1. **Copy the template**:
   ```bash
   cp droplogic/hardware/template/hardware_template.py droplogic/hardware/my_hardware.py
   ```

2. **Rename the class**:
   ```python
   class MyHardware(HardwareTemplate):  # Inherit from DropSystem Base
   ```

3. **Customize for your hardware** (see sections below)

4. **Test your implementation**:
   ```python
   hardware = MyHardware()
   hardware.visualizers.matrix.start()  # Test matrix visualization
   ```

## Template Structure

### Core Components

- **DropSystem Base Class**: Queue-based command processing, state management, and logging.
- **Hardware Modules**: Camera, microscope, XY stage, electrode matrix, temperature, etc.
- **Visualizers**: Automatic setup of `MatrixVisualizer` and `StreamerVisualizer`.
- **AdvancedDrop**: Built-in SIPP planning and execution capabilities (initialized automatically).

## Implementation Guide

### 1. Basic Setup

```python
from ..base import DropSystem

class MyHardware(DropSystem):
    def __init__(self, config_file="config.json", log_level="INFO"):
        # Call parent constructor
        super().__init__(config_file=config_file)
        
        # Add your custom initialization here
        # self.my_custom_module = MyCustomModule(self)
        
        # Initialize advanced drop routines
        from ..utils.advanced_drop import AdvancedDrop
        self.advanced_drop = AdvancedDrop(self)
```

### 2. Hardware Module Initialization

Inject the modules your system needs matching your configurations:

```python
from .modules.camera import CameraModule
from .modules.xy_stage import XYStageModule
from .modules.electrode_matrix import ElectrodeMatrixModule

# Initialize the modules required by your system
self.camera = CameraModule(self, self.state.get("camera_settings", {}).get("version", "CameraV1"))
self.xy_stage = XYStageModule(self, self.state.get("xy_stage", {}).get("version", "XYStageV1"))
self.electrode_matrix = ElectrodeMatrixModule(
    self, None, 128, 128, version="DMLite"
)
```

### 3. Command Processing

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

### 4. Cleanup and Resource Management

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

## Best Practices

1. **Follow the naming conventions** used in existing implementations.
2. **Use appropriate logging levels** for debugging and monitoring.
3. **Handle exceptions gracefully** in hardware operations to prevent crashing the main thread.
4. **Test with the simulator first** before moving to real hardware integration.
5. **Document your hardware-specific parameters** in `config.json`.
6. **Implement proper error recovery** for hardware communication failures.

## Reference Implementations

You can study the existing systems inside the `droplogic/hardware/` directory:

- **BOXMini** (`box_mini1.py`): Full hardware system including camera, microscope, and XY stage.
- **Simulator** (`simulator.py`): Simulation-only environment mimicking the electrode matrix behavior.
