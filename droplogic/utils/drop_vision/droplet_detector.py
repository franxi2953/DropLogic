"""
Droplet Detection Module using YOLO11

This module provides the main interface for droplet detection using a trained YOLO11 model.
It handles model loading, inference, and result processing for droplet detection in microscopy images.
"""

import sys
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Union
from dataclasses import dataclass

from ..logging_config import setup_droplogic_logger

# Set up logger
logger = setup_droplogic_logger('droplogic.drop_vision.droplet_detector')


@dataclass
class DetectionResult:
    """Container for droplet detection results."""
    bounding_boxes: List[Tuple[float, float, float, float]]  # List of (x1, y1, x2, y2) coordinates
    confidences: List[float]                                 # Confidence scores for each detection
    class_ids: List[int]                                     # Class IDs (if multiple droplet types)
    class_names: List[str]                                   # Human-readable class names
    annotated_frame: Optional[np.ndarray] = None             # Frame with bounding boxes drawn


class DropletDetector:
    """
    YOLO11-based droplet detector for microscopy images.
    
    This class handles loading the trained YOLO11 model and performing inference
    on microscopy frames to detect droplets and return their bounding box coordinates.
    """
    
    def __init__(self, model_path: Optional[Union[str, Path]] = None,
                 confidence_threshold: float = 0.25,
                 image_size: int = 640):
        """
        Initialize the droplet detector.

        Args:
            model_path: Path to the trained YOLO11 model file (.pt).
                        Defaults to models/best.pt in the drop_vision directory.
            confidence_threshold: Minimum confidence score for detections
            image_size: Input image size for the model
        """
        # Set default model path if none provided
        if model_path is None:
            model_path = Path(__file__).parent / "models" / "droplets.pt"

        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.image_size = image_size
        self.model = None
        self._model_loaded = False

        # Try to load the model if path is provided
        if model_path:
            self.load_model(model_path)
        else:
            logger.warning("No model path provided. Call load_model() before detection.")
    
    def load_model(self, model_path: Union[str, Path]) -> bool:
        """
        Load the YOLO11 model from file.
        
        Args:
            model_path: Path to the model file
            
        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            from ultralytics import YOLO
            
            model_path = Path(model_path)
            if not model_path.exists():
                logger.error(f"Model file not found: {model_path}")
                return False
            
            logger.info(f"Loading YOLO11 model from: {model_path}")
            self.model = YOLO(str(model_path))
            self.model_path = model_path
            self._model_loaded = True
            
            logger.info(f"Model loaded successfully. Classes: {self.model.names}")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import YOLO: {e}")
            logger.error("Make sure ultralytics is installed: pip install ultralytics")
            return False
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def detect(self, frame: np.ndarray, 
               confidence_threshold: Optional[float] = None,
               return_annotated: bool = True,
               debug: bool = False) -> DetectionResult:
        """
        Detect droplets in a given frame.
        
        Args:
            frame: Input image as numpy array (BGR format)
            confidence_threshold: Override default confidence threshold
            return_annotated: Whether to return frame with bounding boxes drawn
            debug: If True, ensures at least some fake detections are returned for testing
            
        Returns:
            DetectionResult containing bounding boxes, confidences, and optionally annotated frame
        """
        if not self._model_loaded:
            logger.error("Model not loaded. Call load_model() first.")
            return DetectionResult([], [], [], [])
        
        if frame is None or frame.size == 0:
            logger.warning("Empty or invalid frame provided")
            return DetectionResult([], [], [], [])
        
        # Use provided confidence threshold or default
        conf_threshold = confidence_threshold or self.confidence_threshold
        
        try:
            bounding_boxes = []
            confidences = []
            class_ids = []
            class_names = []

            # Run inference
            results = self.model.predict(
                source=frame,
                conf=conf_threshold,
                imgsz=self.image_size,
                save=False,
                verbose=False
            )
            
            # Process results
            if results and len(results) > 0:
                result = results[0]
                
                if result.boxes is not None and len(result.boxes) > 0:
                    for box in result.boxes:
                        # Extract bounding box coordinates (x1, y1, x2, y2)
                        bbox = box.xyxy[0].cpu().numpy().tolist()
                        bounding_boxes.append(tuple(bbox))
                        
                        # Extract confidence
                        confidence = float(box.conf[0].cpu().numpy())
                        confidences.append(confidence)
                        
                        # Extract class information
                        class_id = int(box.cls[0].cpu().numpy())
                        class_ids.append(class_id)
                        class_names.append(self.model.names[class_id])
                    
                    logger.debug(f"Detected {len(bounding_boxes)} droplets")
                else:
                    logger.debug("No droplets detected")
            
            # Debug mode: ensure at least some fake detections are returned
            if debug and not bounding_boxes:
                frame_h, frame_w = frame.shape[:2]
                fake_bbox = (frame_w//2 - 100, frame_h//2 - 100, frame_w//2 + 100, frame_h//2 + 100)
                bounding_boxes.append(fake_bbox)
                confidences.append(0.99)
                class_ids.append(0)
                class_names.append('droplet')
                logger.debug("Debug mode: Added fake droplet detection")

            # Create annotated frame if requested
            annotated_frame = None
            if return_annotated:
                annotated_frame = self._draw_detections(frame.copy(), bounding_boxes, confidences, class_names)
            
            return DetectionResult(
                bounding_boxes=bounding_boxes,
                confidences=confidences,
                class_ids=class_ids,
                class_names=class_names,
                annotated_frame=annotated_frame
            )
            
        except Exception as e:
            logger.error(f"Error during detection: {e}")
            return DetectionResult([], [], [], [])
    
    def _draw_detections(self, frame: np.ndarray, 
                        bounding_boxes: List[Tuple[float, float, float, float]],
                        confidences: List[float],
                        class_names: List[str]) -> np.ndarray:
        """
        Draw bounding boxes and labels on the frame.
        
        Args:
            frame: Input frame to draw on
            bounding_boxes: List of (x1, y1, x2, y2) coordinates
            confidences: Confidence scores
            class_names: Class names for each detection
            
        Returns:
            Frame with bounding boxes drawn
        """
        for bbox, conf, class_name in zip(bounding_boxes, confidences, class_names):
            x1, y1, x2, y2 = map(int, bbox)
            
            # Draw bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Draw label with confidence
            label = f"{class_name}: {conf:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
            
            # Draw label background
            cv2.rectangle(frame, (x1, y1 - label_size[1] - 10), 
                         (x1 + label_size[0], y1), (0, 255, 0), -1)
            
            # Draw label text
            cv2.putText(frame, label, (x1, y1 - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        return frame
    
    def is_loaded(self) -> bool:
        """Check if model is loaded and ready for inference."""
        return self._model_loaded
    
    def get_model_info(self) -> Dict:
        """Get information about the loaded model."""
        if not self._model_loaded:
            return {}
        
        return {
            'model_path': str(self.model_path),
            'classes': self.model.names,
            'num_classes': len(self.model.names),
            'confidence_threshold': self.confidence_threshold,
            'image_size': self.image_size
        }


def detect_droplets(frame: np.ndarray, 
                   model_path: Optional[Union[str, Path]] = None,
                   confidence_threshold: float = 0.25,
                   image_size: int = 640,
                   return_annotated: bool = True,
                   debug: bool = False) -> DetectionResult:
    """
    Convenience function for one-time droplet detection.
    
    Args:
        frame: Input image as numpy array
        model_path: Path to YOLO11 model file. Defaults to models/best.pt in drop_vision directory.
        confidence_threshold: Minimum confidence for detections
        image_size: Input size for the model
        return_annotated: Whether to return annotated frame
        debug: If True, ensures at least some fake detections are returned for testing
        
    Returns:
        DetectionResult with detection information
    """
    detector = DropletDetector(model_path, confidence_threshold, image_size)
    return detector.detect(frame, return_annotated=return_annotated, debug=debug)
