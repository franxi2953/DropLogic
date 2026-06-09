# 視覺同修正

Vision helpers 係可選嘅。只有當系統具備所需嘅 camera、microscope 同/或 XY stage 模組時，佢哋先工作。

Simulator 同 DMLite 工作流仍然可以使用 debug modes 同邏輯修正工具。

## 驗證液滴

`verify_droplets()` 檢查液滴係咪喺 plan 期望嘅位置。

```python
results, frame_files = system.advanced_drop.verify_droplets(
    frame_idx=20,
    droplet_ids=[1, 2],
    save_frames_path="runs/verification_frames",
)
```

返回：

- `results`：由 `droplet_id` 到 `True` 或 `False`。
- `frame_files`：提供 `save_frames_path` 時保存嘅圖像路徑。

要求：

- XY stage module
- camera 或 microscope module
- 初始化過嘅 `DropletPositionValidator`

冇硬件視覺時，可以用 debug mode 測試 recovery logic。

## 修正邏輯位置

當物理液滴位於 planner 以為位置以外嘅電極時，使用 `correct_droplet_position()`。

```python
ad.correct_droplet_position(
    droplet_id=1,
    correct_pos=(34, 42),
)
```

佢會追加 correction frame，更新液滴 trajectory，並更新液滴物件嘅目前 corner。protocol script 入面唔好直接賦值 `droplet.origin_corner = ...`。

## 將 Stage 移到液滴中心

```python
ok = ad.move_to_droplet_center(
    droplet_id=1,
    wait_before_check=0.5,
    wait_after_check=0.5,
)
```

佢計算液滴中心，轉換為 stage coordinates，更新 `xy_stage.position`，並等待移動完成。

## 偵測 Condensates

`detect_condensates()` 喺傳入 frame 或新擷取嘅 microscope frames 上運行液滴同 condensate detection。

```python
results, annotated = ad.detect_condensates(
    confidence_threshold=0.25,
    crop_droplet=True,
    crop_padding=50,
    return_annotated=True,
    save_image_path="runs/condensates.png",
)
```

返回 `results` 同可選嘅 annotated image。`debug=True` 會建立 mock detections。

當 `frame=None` 時，函數會透過系統 camera/microscope pathway 擷取 fluorescence 同 brightfield frames，並嘗試恢復之前嘅 microscope/light settings。
