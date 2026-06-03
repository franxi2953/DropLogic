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
