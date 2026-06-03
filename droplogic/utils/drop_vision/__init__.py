"""
Drop Vision Module for Droplet Detection and Analysis

This module provides computer vision capabilities specifically designed for droplet
detection and analysis in Digital Microfluidics (DMF) applications.

Key Features:
- YOLO11-based droplet and condensate detection
- Real-time bounding box detection
- Integration with DropSystem visualizer components
- Feedback systems for droplet movement validation
"""

from .droplet_detector import DropletDetector, detect_droplets
from .condensate_detector import CondensateDetector, detect_condensates
from .imaging_capture import capture_channel_frame, configure_capture_channel

__all__ = [
	'DropletDetector',
	'detect_droplets',
	'CondensateDetector',
	'detect_condensates',
	'capture_channel_frame',
	'configure_capture_channel',
]
