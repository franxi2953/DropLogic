## Calibration And Geometry
- `config.json` is source of truth for machine calibration: pixel calibration, chip origin, electrode-to-stage mapping, backlash, named presets.
- Cartridge JSON stores cartridge geometry such as input holes and blocked/no-go regions.
- Use `droplogic.utils.hardware_utils` helpers instead of hand-written conversion math when writing code or interpreting calibrated quantities:
  - `electrode_to_stage(row, col)`
  - `stage_to_electrode((x, y))`, `stage_to_electrode_float((x, y))`
  - `pixels_to_microns(...)`, `microns_to_pixels(...)`, `get_pixel_calibration_info(...)`
  - `pixels_to_volume_nl(pixel_area, height_microns=50)`, `area_pixels_to_radius_microns(pixel_area)`
- For image-derived DMLite volume, use `height_microns=50`: `pixel_area * microns_per_pixel^2 * 50 / 1_000_000` nL.
