# Calibration

Calibration connects physical coordinates, camera pixels, and electrode positions.

DropLogic keeps calibration separate from systems so the same system can be tuned for different machines, chips, cameras, and optical setups.

## Main Pieces

- `CalibrationManager`: stores and retrieves calibration data
- `XYCalibration`: maps XY stage space to electrode and imaging references
- hardware utility conversion functions

## Where It Lives

- `droplogic/calibration/calibration_manager.py`
- `droplogic/calibration/xy_calibration.py`
- `droplogic/utils/hardware_utils/utils.py`

Calibration data should be treated as deployment-specific state. The library can provide structure and conversion routines, but measured calibration values belong to the installed machine.

## Save and Load Calibration

```python
from droplogic.calibration.calibration_manager import CalibrationManager

manager = CalibrationManager(system)
manager.save_calibration("calibration_data.json")
manager.load_calibration("calibration_data.json")
```

`CalibrationManager` reads and writes the `system.state["calibration"]` block.

## Set Chip Origin

```python
from droplogic.calibration.xy_calibration import XYCalibration

xy = XYCalibration(system)
origin = xy.set_chip_origin(x_position=12345, y_position=67890)
```

This updates:

- `calibration.chip_origin.X`
- `calibration.chip_origin.Y`

The chip origin is the stage coordinate corresponding to electrode `(0, 0)` plus the configured mapping offsets.

## Practical Workflow

1. Move the stage to the physical location corresponding to the chip origin.
2. Call `set_chip_origin()`.
3. Measure row/column step vectors and update `calibration.electrode_mapping` in `config.json`.
4. Test with `electrode_to_stage()` and `stage_to_electrode()`.
5. Save the calibration file for that machine.
