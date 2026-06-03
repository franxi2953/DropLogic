# Drop Vision Module

The `drop_vision` module provides computer vision capabilities specifically designed for droplet detection and analysis in Digital Microfluidics (DMF) applications using a trained YOLO11 model.

## Overview

This module enables real-time droplet detection from microscopy images, providing bounding box coordinates and confidence scores that can be integrated with the DropLogic library's visualizer components and advanced droplet manipulation systems.

## Module Structure

```
droplogic/utils/drop_vision/
├── __init__.py           # Module interface and exports
├── droplet_detector.py   # Main detection class and functionality
├── test_detector.py      # Testing and validation scripts
├── models/
│   ├── best.pt          # Your trained YOLO11 model (place here)
│   └── README.md        # Model setup instructions
├── test_images/
│   ├── test.jpg         # Test image for validation
│   └── README.md        # Test image setup instructions
└── README.md            # This documentation
```

## Key Components

### DropletDetector Class

The main interface for droplet detection operations:

```python
from droplogic.utils.drop_vision import DropletDetector

# Initialize detector with your trained model
# Uses models/best.pt by default if no path specified
detector = DropletDetector(
    confidence_threshold=0.25,
    image_size=640
)

# Or specify a custom path
detector = DropletDetector(
    model_path="path/to/custom_model.pt",
    confidence_threshold=0.25,
    image_size=640
)

# Detect droplets in a frame
result = detector.detect(frame, return_annotated=True)
```

### DetectionResult Dataclass

Container for detection results:

- `bounding_boxes`: List of (x1, y1, x2, y2) coordinates
- `confidences`: Confidence scores for each detection
- `class_ids`: Class IDs (if multiple droplet types)
- `class_names`: Human-readable class names
- `annotated_frame`: Optional frame with bounding boxes drawn

## Usage Examples

### Basic Detection

```python
import cv2
from droplogic.utils.drop_vision import detect_droplets

# Load an image
frame = cv2.imread("microscopy_image.jpg")

# Detect droplets (one-time detection)
# Uses models/best.pt by default
result = detect_droplets(
    frame=frame,
    confidence_threshold=0.25
)

# Or specify a custom model path
result = detect_droplets(
    frame=frame,
    model_path="path/to/custom_model.pt",
    confidence_threshold=0.25
)

print(f"Found {len(result.bounding_boxes)} droplets")
for i, (bbox, conf) in enumerate(zip(result.bounding_boxes, result.confidences)):
    x1, y1, x2, y2 = bbox
    print(f"Droplet {i+1}: ({x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}) conf={conf:.3f}")
```

### Persistent Detector (Recommended for Multiple Detections)

```python
from droplogic.utils.drop_vision import DropletDetector

# Create detector instance (loads model once)
# Uses models/best.pt by default
detector = DropletDetector()

# Use for multiple frames
for frame in video_frames:
    result = detector.detect(frame)
    # Process results...
```

### Integration with DropLogic Visualizers

```python
from droplogic.utils.visualizer import StreamerVisualizer
from droplogic.utils.drop_vision import DropletDetector

# Create detector (uses default models/best.pt)
detector = DropletDetector()

def frame_processor_with_detection(frame):
    """Custom frame processor that adds droplet detection overlay"""
    result = detector.detect(frame, return_annotated=True)
    return result.annotated_frame if result.annotated_frame is not None else frame

# Use with visualizer
visualizer = StreamerVisualizer(
    device=camera_device,
    external_frame_processor=frame_processor_with_detection
)
visualizer.start()
```

## Configuration Parameters

### DropletDetector Parameters

- `model_path`: Path to the trained YOLO11 model file (.pt). Defaults to `models/best.pt` in the drop_vision directory.
- `confidence_threshold`: Minimum confidence score for detections (default: 0.25)
- `image_size`: Input image size for the model (default: 640)

### Detection Parameters

- `confidence_threshold`: Override default confidence threshold for specific detection
- `return_annotated`: Whether to return frame with bounding boxes drawn (default: True)

## Setup Requirements

### 1. Dependencies
Install the required packages:
```bash
pip install ultralytics
```

Or if using the project pyproject.toml:
```bash
pip install -e .
```

### 2. Model Setup
- **Model Format**: PyTorch (.pt) file from YOLO11 training
- **Model Location**: Place your `best.pt` file in the `models/` subdirectory
- **Training**: See `YOLO_Training/droplet_training_guide.md` for training instructions

### 3. Test Data (Optional)
- Place test images in `test_images/` directory
- Use `test.jpg` as the default test image
- Required for running validation tests

## Integration Points

### With Advanced Drop Module

```python
from droplogic.utils.advanced_drop import plan_multi_droplet_movement
from droplogic.utils.drop_vision import DropletDetector

# Detect current droplet positions (uses default models/best.pt)
detector = DropletDetector()
result = detector.detect(current_frame)

# Convert detections to droplet positions for path planning
detected_positions = [(int((x1+x2)/2), int((y1+y2)/2)) 
                     for x1, y1, x2, y2 in result.bounding_boxes]

# Use in path planning...
```

### With Visualizer Components

The module integrates seamlessly with DropLogic visualizer components:

- `StreamerVisualizer`: Add detection overlay to live camera feed
- `MatrixVisualizer`: Correlate detected positions with electrode matrix

### Feedback Systems

Detection results can provide feedback for:

- **Position Validation**: Verify droplets are where expected
- **Movement Tracking**: Monitor droplet displacement during operations
- **Quality Assessment**: Detect droplet splitting, merging, or loss

## Error Handling

The module includes comprehensive error handling:

- Model loading failures
- Missing model files
- Invalid input frames
- Detection processing errors

All errors are logged using the DropLogic logging system.

## Performance Considerations

- **Model Loading**: Load the model once and reuse the detector instance
- **Image Size**: Larger input sizes (1280) provide better accuracy but slower inference
- **Confidence Threshold**: Lower thresholds detect more droplets but may include false positives

## Testing

Use the included test script to validate detection performance:

```python
from droplogic.utils.drop_vision.test_detector import test_detection_parameters

# Test with different parameters
test_detection_parameters(
    model_path=Path("best.pt"),
    test_image_path=Path("test_image.jpg")
)
```

## Future Extensions

The module is designed for extensibility:

- **Multi-class Detection**: Support for different droplet types
- **Tracking**: Temporal tracking of droplet movement
- **Segmentation**: Pixel-level droplet segmentation
- **Real-time Optimization**: Performance optimizations for live detection
