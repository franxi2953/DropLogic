# 视觉和校正

Vision helpers 是可选的。只有当系统具备所需的 camera、microscope 和/或 XY stage 模块时，它们才工作。

Simulator 和 DMLite 工作流仍可使用 debug modes 和逻辑校正工具。

## 验证液滴

`verify_droplets()` 检查液滴是否位于 plan 期望的位置。

```python
results, frame_files = system.advanced_drop.verify_droplets(
    frame_idx=20,
    droplet_ids=[1, 2],
    save_frames_path="runs/verification_frames",
)
```

返回：

- `results`：从 `droplet_id` 到 `True` 或 `False`。
- `frame_files`：提供 `save_frames_path` 时保存的图像路径。

要求：

- XY stage module
- camera 或 microscope module
- 初始化过的 `DropletPositionValidator`

没有硬件视觉时，可以用 debug mode 测试 recovery logic：

```python
results, frame_files = ad.verify_droplets(
    frame_idx=10,
    droplet_ids=[1],
    debug=True,
    save_frames_path="runs/debug_verification",
)
```

## 校正逻辑位置

当物理液滴位于 planner 认为位置以外的电极时，使用 `correct_droplet_position()`。

```python
ad.correct_droplet_position(
    droplet_id=1,
    correct_pos=(34, 42),
)
```

它会追加 correction frame，更新液滴 trajectory，并更新液滴对象的当前 corner。协议脚本中不要直接赋值 `droplet.origin_corner = ...`。

## 将 Stage 移到液滴中心

```python
ok = ad.move_to_droplet_center(
    droplet_id=1,
    wait_before_check=0.5,
    wait_after_check=0.5,
)
```

它计算液滴中心，转换为 stage coordinates，更新 `xy_stage.position`，并等待移动完成。

## 检测 Condensates

`detect_condensates()` 在传入 frame 或新捕获的 microscope frames 上运行液滴和 condensate detection。

```python
results, annotated = ad.detect_condensates(
    confidence_threshold=0.25,
    crop_droplet=True,
    crop_padding=50,
    return_annotated=True,
    save_image_path="runs/condensates.png",
)
```

返回 `results` 和可选的 annotated image。`debug=True` 会创建 mock detections。

当 `frame=None` 时，函数会通过系统 camera/microscope pathway 捕获 fluorescence 和 brightfield frames，并尝试恢复之前的 microscope/light settings。
