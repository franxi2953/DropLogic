# 硬件工具

Hardware utilities 提供真實系統常用嘅轉換同設定 helpers。

## 主要職責

- 載入同保存 `config.json`
- 將電極座標轉換為 stage 座標
- 將 stage 座標轉換返電極座標
- 轉換 pixels、microns 同估算體積
- 暴露 camera models 嘅 calibration metadata

## 程式位置

- `droplogic/utils/hardware_utils/utils.py`

呢啲 helpers 應該保持細同 deterministic。系統專屬邏輯屬於 systems 同 modules；呢度嘅 utilities 應該可以喺唔同硬件集成之間重用。

## 載入同保存 Config

```python
from droplogic.utils.hardware_utils import load_config, save_config

config = load_config("config.json")
config["electrode_matrix"]["voltage"] = 45
save_config(config, "config.json")
```

如果唔傳路徑，helper 使用函式庫級 `config.json`。

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

轉換使用 `calibration.chip_origin`、`inter_row`、`inter_column`、`offset_x` 同 `offset_y`。

## Stage to Electrode

```python
from droplogic.utils.hardware_utils import stage_to_electrode

electrode = stage_to_electrode((12345, 67890), config_path="config.json")
```

返回最近嘅 `(row, col)`，如果點映射到矩陣外就返回 `None`。

overlays 可以使用 floating 版本：

```python
from droplogic.utils.hardware_utils import stage_to_electrode_float

row_f, col_f = stage_to_electrode_float((12345, 67890), config_path="config.json")
```

## Pixel 同體積 Helpers

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

目前基礎 `config.json` 為 `AM16k` 定義預設 calibration。使用機器專屬設定時傳入 `config_path`。
