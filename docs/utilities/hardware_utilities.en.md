# Hardware Utilities

Hardware utilities provide common conversions and configuration helpers used by real systems.

## Main Responsibilities

- load and save `config.json`
- convert electrode coordinates to stage coordinates
- convert stage coordinates back to electrode coordinates
- convert pixels, microns, and estimated volumes
- expose calibration metadata for camera models

## Where It Lives

- `droplogic/utils/hardware_utils/utils.py`

These helpers should stay small and deterministic. System-specific logic belongs in systems and modules, while these utilities should remain reusable across hardware integrations.

## Load and Save Config

```python
from droplogic.utils.hardware_utils import load_config, save_config

config = load_config("config.json")
config["electrode_matrix"]["voltage"] = 45
save_config(config, "config.json")
```

If no path is passed, the helper uses the library-level `config.json`.

## Electrode to Stage

```python
from droplogic.utils.hardware_utils import electrode_to_stage

stage_pos = electrode_to_stage(20, 35, config_path="config.json")
system.update_state("xy_stage.position", stage_pos)
```

Returns:

```python
{"X": 12345, "Y": 67890, "Z": 0}
```

The conversion uses:

- `calibration.chip_origin`
- `calibration.electrode_mapping.inter_row`
- `calibration.electrode_mapping.inter_column`
- `offset_x`
- `offset_y`

## Stage to Electrode

```python
from droplogic.utils.hardware_utils import stage_to_electrode

electrode = stage_to_electrode((12345, 67890), config_path="config.json")
```

Returns the nearest `(row, col)` or `None` if the point maps outside the matrix.

Use the floating version for overlays:

```python
from droplogic.utils.hardware_utils import stage_to_electrode_float

row_f, col_f = stage_to_electrode_float((12345, 67890), config_path="config.json")
```

## Pixel and Volume Helpers

```python
from droplogic.utils.hardware_utils import (
    pixels_to_microns,
    microns_to_pixels,
    pixels_to_volume_nl,
    area_pixels_to_radius_microns,
)

diameter_um = pixels_to_microns(120, camera_model="AM16k")
diameter_px = microns_to_pixels(200, camera_model="AM16k")
volume_nl = pixels_to_volume_nl(pixel_area=3500, height_microns=50)
radius_um = area_pixels_to_radius_microns(pixel_area=3500)
```

The default calibration is currently defined for `AM16k`.
