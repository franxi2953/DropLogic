# 硬件工具

Hardware utilities 提供真实系统常用的转换和配置 helpers。

## 主要职责

- 加载和保存 `config.json`
- 将电极坐标转换为 stage 坐标
- 将 stage 坐标转换回电极坐标
- 转换 pixels、microns 和估算体积
- 暴露 camera models 的 calibration metadata

## 代码位置

- `droplogic/utils/hardware_utils/utils.py`

这些 helpers 应保持小而确定。系统专属逻辑属于 systems 和 modules；这里的 utilities 应在不同硬件集成间可复用。

## 加载和保存 Config

```python
from droplogic.utils.hardware_utils import load_config, save_config

config = load_config("config.json")
config["electrode_matrix"]["voltage"] = 45
save_config(config, "config.json")
```

如果不传路径，helper 使用库级 `config.json`。

## Electrode to Stage

```python
from droplogic.utils.hardware_utils import electrode_to_stage

stage_pos = electrode_to_stage(20, 35, config_path="config.json")
system.update_state("xy_stage.position", stage_pos)
```

返回：

```python
{"X": 12345, "Y": 67890, "Z": 0}
```

转换使用 `calibration.chip_origin`、`inter_row`、`inter_column`、`offset_x` 和 `offset_y`。

## Stage to Electrode

```python
from droplogic.utils.hardware_utils import stage_to_electrode

electrode = stage_to_electrode((12345, 67890), config_path="config.json")
```

返回最近的 `(row, col)`，如果点映射到矩阵外则返回 `None`。

overlays 可使用 floating 版本：

```python
from droplogic.utils.hardware_utils import stage_to_electrode_float

row_f, col_f = stage_to_electrode_float((12345, 67890), config_path="config.json")
```

## Pixel 和体积 Helpers

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

当前基础 `config.json` 为 `AM16k` 定义默认 calibration。使用机器专属配置时传入 `config_path`。
