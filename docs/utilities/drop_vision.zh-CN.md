# Drop Vision

Drop vision 包含用于液滴和 condensate detection 的图像分析 helpers。

## 主要组件

- `DropletDetector`：基于 YOLO 的液滴检测
- `CondensateDetector`：condensate detection 和 post-processing
- `imaging_capture`：从系统 camera 或 microscope 获取 frames 的 helpers
- `time_series_analysis`：处理时间序列图像的工具

## 代码位置

- `droplogic/utils/drop_vision/droplet_detector.py`
- `droplogic/utils/drop_vision/condensate_detector.py`
- `droplogic/utils/drop_vision/imaging_capture.py`
- `droplogic/utils/drop_vision/time_series_analysis.py`

Vision utilities 是可选的。只使用 Simulator 的工作流不需要它们；真实系统只有在 camera 或 microscope 模块可用时才使用。

## 液滴检测

```python
from droplogic.utils.drop_vision import DropletDetector

detector = DropletDetector(confidence_threshold=0.25)
result = detector.detect(frame, return_annotated=True)

print(result.bounding_boxes)
print(result.confidences)
```

函数式 helper：

```python
from droplogic.utils.drop_vision import detect_droplets

result = detect_droplets(
    frame,
    confidence_threshold=0.25,
    return_annotated=True,
)
```

`DropletDetector` 默认使用 `droplogic/utils/drop_vision/models/droplets.pt`。

## Condensate Detection

```python
from droplogic.utils.drop_vision import CondensateDetector

detector = CondensateDetector(confidence_threshold=0.25)
result = detector.detect(
    frame=fam_frame,
    droplet_image=brightfield_frame,
    crop_droplet=True,
    crop_padding=50,
    return_annotated=True,
)
```

默认 models：

- `models/droplets.pt`
- `models/condensates.pt`

## DetectionResult

Detection helpers 返回 `DetectionResult`，包含：

- `bounding_boxes`
- `confidences`
- `class_ids`
- `class_names`
- 请求时的 `annotated_frame`

## Visualizer 集成

live overlays 应使用 streamer visualizer，而不是手动调用 detection：

```python
system.visualizers.streamer.enable_droplet_detection(confidence_threshold=0.25)
system.visualizers.streamer.enable_condensate_detection(crop_droplet=True)
```

手动 detection 更适合 batch analysis、保存 frames、tests 或自定义 pipelines。
