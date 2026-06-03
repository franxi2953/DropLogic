# Drop Vision

Drop vision contains image-analysis helpers for droplet and condensate detection.

## Main Pieces

- `DropletDetector`: YOLO-backed droplet detection
- `CondensateDetector`: condensate detection and post-processing
- `imaging_capture`: helpers for grabbing camera or microscope frames from a system
- `time_series_analysis`: utilities for processing image sequences over time

## Where It Lives

- `droplogic/utils/drop_vision/droplet_detector.py`
- `droplogic/utils/drop_vision/condensate_detector.py`
- `droplogic/utils/drop_vision/imaging_capture.py`
- `droplogic/utils/drop_vision/time_series_analysis.py`

Vision utilities are optional. Simulator-only workflows do not need them, and real systems only use them when camera or microscope modules are available.

## Droplet Detection

```python
from droplogic.utils.drop_vision import DropletDetector

detector = DropletDetector(confidence_threshold=0.25)
result = detector.detect(frame, return_annotated=True)

print(result.bounding_boxes)
print(result.confidences)
```

Functional helper:

```python
from droplogic.utils.drop_vision import detect_droplets

result = detect_droplets(
    frame,
    confidence_threshold=0.25,
    return_annotated=True,
)
```

`DropletDetector` uses `droplogic/utils/drop_vision/models/droplets.pt` by default.

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

Functional helper:

```python
from droplogic.utils.drop_vision import detect_condensates

result = detect_condensates(
    frame=fam_frame,
    droplet_image=brightfield_frame,
    crop_droplet=True,
    confidence_threshold=0.25,
)
```

Default models:

- `models/droplets.pt`
- `models/condensates.pt`

## DetectionResult

Detection helpers return a `DetectionResult` with:

- `bounding_boxes`
- `confidences`
- `class_ids`
- `class_names`
- `annotated_frame` when requested

## Visualizer Integration

For live overlays, use the streamer visualizer rather than calling detection manually:

```python
system.visualizers.streamer.enable_droplet_detection(confidence_threshold=0.25)
system.visualizers.streamer.enable_condensate_detection(crop_droplet=True)
```

Manual detection is better for batch analysis, saved frames, tests, or custom pipelines.
