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
