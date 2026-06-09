# Drop Vision

Drop vision 包含用於液滴同 condensate detection 嘅圖像分析 helpers。

## 主要組件

- `DropletDetector`：基於 YOLO 嘅液滴偵測
- `CondensateDetector`：condensate detection 同 post-processing
- `imaging_capture`：由系統 camera 或 microscope 取得 frames 嘅 helpers
- `time_series_analysis`：處理時間序列圖像嘅工具

## 程式位置

- `droplogic/utils/drop_vision/droplet_detector.py`
- `droplogic/utils/drop_vision/condensate_detector.py`
- `droplogic/utils/drop_vision/imaging_capture.py`
- `droplogic/utils/drop_vision/time_series_analysis.py`

Vision utilities 係可選嘅。只使用 Simulator 嘅工作流唔需要佢哋；真實系統只有 camera 或 microscope 模組可用時先使用。

## 液滴偵測

```python
from droplogic.utils.drop_vision import DropletDetector

detector = DropletDetector(confidence_threshold=0.25)
result = detector.detect(frame, return_annotated=True)

print(result.bounding_boxes)
print(result.confidences)
```

函數式 helper：

```python
from droplogic.utils.drop_vision import detect_droplets

result = detect_droplets(
    frame,
    confidence_threshold=0.25,
    return_annotated=True,
)
```

`DropletDetector` 預設使用 `droplogic/utils/drop_vision/models/droplets.pt`。

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

預設 models：

- `models/droplets.pt`
- `models/condensates.pt`

## DetectionResult

Detection helpers 返回 `DetectionResult`，包含：

- `bounding_boxes`
- `confidences`
- `class_ids`
- `class_names`
- 請求時嘅 `annotated_frame`

## Visualizer 集成

live overlays 應該使用 streamer visualizer，而唔係手動調用 detection：

```python
system.visualizers.streamer.enable_droplet_detection(confidence_threshold=0.25)
system.visualizers.streamer.enable_condensate_detection(crop_droplet=True)
```

手動 detection 更適合 batch analysis、保存 frames、tests 或自訂 pipelines。
