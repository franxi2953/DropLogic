"""
Condensate Detection Module using YOLO11

This module provides the main interface for condensate detection using trained YOLO11 models.
It handles model loading, inference, and result processing for condensate detection in microscopy images,
with optional droplet-based cropping.
"""

import sys
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Union
from dataclasses import dataclass

from ..logging_config import setup_droplogic_logger

# Set up logger
logger = setup_droplogic_logger('droplogic.drop_vision.condensate_detector')


@dataclass
class DetectionResult:
    """Container for condensate detection results."""
    bounding_boxes: List[Tuple[float, float, float, float]]  # List of (x1, y1, x2, y2) coordinates
    confidences: List[float]                                 # Confidence scores for each detection
    class_ids: List[int]                                     # Class IDs (if multiple condensate types)
    class_names: List[str]                                   # Human-readable class names
    annotated_frame: Optional[np.ndarray] = None             # Frame with bounding boxes drawn
    droplet_centers: Optional[List[Optional[Tuple[float, float]]]] = None  # Normalized center (x,y) of droplet each detection belongs to (when cropping), None for direct detections


class CondensateDetector:
    """
    YOLO11-based condensate detector for microscopy images with optional droplet cropping.
    
    This class handles loading the trained YOLO11 models for droplets and condensates,
    and performing inference on microscopy frames to detect condensates, optionally
    cropping around detected droplets first.
    """
    
    def __init__(self, droplet_model_path: Optional[Union[str, Path]] = None,
                 condensate_model_path: Optional[Union[str, Path]] = None,
                 confidence_threshold: float = 0.25,
                 image_size: int = 1024):
        """
        Initialize the condensate detector.

        Args:
            droplet_model_path: Path to the trained YOLO11 droplet model file (.pt).
                               Defaults to models/droplets.pt in the drop_vision directory.
            condensate_model_path: Path to the trained YOLO11 condensate model file (.pt).
                                   Defaults to models/condensates.pt in the drop_vision directory.
            confidence_threshold: Minimum confidence score for detections
            image_size: Input image size for the model (default 1024, multiple of 32)
        """
        # Set default model paths if none provided
        if droplet_model_path is None:
            droplet_model_path = Path(__file__).parent / "models" / "droplets.pt"
        if condensate_model_path is None:
            condensate_model_path = Path(__file__).parent / "models" / "condensates.pt"

        self.droplet_model_path = droplet_model_path
        self.condensate_model_path = condensate_model_path
        self.confidence_threshold = confidence_threshold
        self.image_size = image_size
        self.droplet_model = None
        self.condensate_model = None
        self.last_condensate_crops = []
        self._models_loaded = False

        # Try to load the models if paths are provided
        if droplet_model_path and condensate_model_path:
            self.load_models(droplet_model_path, condensate_model_path)
        else:
            logger.warning("Model paths not provided. Call load_models() before detection.")
    
    def load_models(self, droplet_model_path: Union[str, Path], 
                   condensate_model_path: Union[str, Path]) -> bool:
        """
        Load the YOLO11 models from files.
        
        Args:
            droplet_model_path: Path to the droplet model file
            condensate_model_path: Path to the condensate model file
            
        Returns:
            True if models loaded successfully, False otherwise
        """
        try:
            from ultralytics import YOLO
            
            droplet_path = Path(droplet_model_path)
            condensate_path = Path(condensate_model_path)
            
            if not droplet_path.exists():
                logger.error(f"Droplet model file not found: {droplet_path}")
                return False
            if not condensate_path.exists():
                logger.error(f"Condensate model file not found: {condensate_path}")
                return False
            
            logger.info(f"Loading YOLO11 droplet model from: {droplet_path}")
            self.droplet_model = YOLO(str(droplet_path))
            self.droplet_model_path = droplet_path
            
            logger.info(f"Loading YOLO11 condensate model from: {condensate_path}")
            self.condensate_model = YOLO(str(condensate_path))
            self.condensate_model_path = condensate_path
            
            self._models_loaded = True
            
            logger.info(f"Models loaded successfully. Condensate classes: {self.condensate_model.names}")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import YOLO: {e}")
            logger.error("Make sure ultralytics is installed: pip install ultralytics")
            return False
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            return False
    
    def detect(self, frame: np.ndarray, 
               droplet_image: Optional[np.ndarray] = None,
               crop_droplet: bool = True,
               crop_padding: int = 50,
               confidence_threshold: Optional[float] = None,
               return_annotated: bool = True,
               draw_labels: bool = True,
               nms_threshold: float = 0.5,
               debug: bool = False) -> DetectionResult:
        """
        Detect condensates in a given frame, optionally cropping around droplets first.
        
        Args:
            frame: Input image as numpy array (BGR format) for condensate detection
            droplet_image: Optional separate image for droplet detection (if cropping)
            crop_droplet: Whether to crop around detected droplets before condensate detection
            crop_padding: Padding in pixels around droplet bounding boxes for cropping
            confidence_threshold: Override default confidence threshold
            return_annotated: Whether to return frame with bounding boxes drawn
            draw_labels: Whether to draw class labels and confidence scores on bounding boxes
            nms_threshold: Non-maximum suppression threshold (0.0-1.0). Boxes with IoU > threshold are suppressed
            debug: If True, ensures at least some fake detections are returned for testing
            
        Returns:
            DetectionResult containing bounding boxes, confidences, and optionally annotated frame
        """
        if not self._models_loaded:
            logger.error("Models not loaded. Call load_models() first.")
            return DetectionResult([], [], [], [])
        
        if frame is None or frame.size == 0:
            logger.warning("Empty or invalid frame provided")
            return DetectionResult([], [], [], [])
        
        # Use provided confidence threshold or default
        conf_threshold = confidence_threshold or self.confidence_threshold
        try:
            self.last_condensate_crops = []
            all_bounding_boxes = []
            all_confidences = []
            all_class_ids = []
            all_class_names = []
            all_droplet_centers = []

            
            if crop_droplet and droplet_image is not None:
                # Detect droplets in the separate image
                droplet_results = self.droplet_model.predict(
                    source=droplet_image,
                    conf=conf_threshold,
                    imgsz=self.image_size,
                    save=False,
                    verbose=False
                )
                if droplet_results and len(droplet_results) > 0:
                    droplet_result = droplet_results[0]
                    if droplet_result.boxes is not None and len(droplet_result.boxes) > 0:
                        logger.info(f"Detected {len(droplet_result.boxes)} droplets for cropping")
                        
                        # Sort droplets spatially: top-left to bottom-right based on bounding box centers
                        boxes_with_centers = []
                        for box in droplet_result.boxes:
                            bbox = box.xyxy[0].cpu().numpy()
                            x1, y1, x2, y2 = bbox
                            center_x = (x1 + x2) / 2
                            center_y = (y1 + y2) / 2
                            boxes_with_centers.append((box, center_y, center_x))
                        
                        # Sort by y (top to bottom), then by x (left to right)
                        boxes_with_centers.sort(key=lambda x: (x[1], x[2]))
                        
                        # Process each droplet in spatial order
                        for droplet_idx, (box, _, _) in enumerate(boxes_with_centers):
                            # Get droplet bounding box
                            droplet_bbox = box.xyxy[0].cpu().numpy()
                            x1, y1, x2, y2 = droplet_bbox
                            
                            # Calculate normalized center: (0,0) center, (-1,1) top-left
                            if droplet_image is not None:
                                img_height, img_width = droplet_image.shape[:2]
                            else:
                                img_height, img_width = frame.shape[:2]
                            center_x = (x1 + x2) / 2
                            center_y = (y1 + y2) / 2
                            norm_x = (center_x - img_width / 2) / (img_width / 2)
                            norm_y = (img_height / 2 - center_y) / (img_height / 2)
                            droplet_center = (norm_x, norm_y)
                            
                            # Calculate crop coordinates with padding
                            crop_x1 = max(0, int(x1) - crop_padding)
                            crop_y1 = max(0, int(y1) - crop_padding)
                            crop_x2 = min(frame.shape[1], int(x2) + crop_padding)
                            crop_y2 = min(frame.shape[0], int(y2) + crop_padding)
                            
                            # Crop the frame
                            crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
                            brightfield_crop = None
                            if droplet_image is not None:
                                brightfield_crop = droplet_image[crop_y1:crop_y2, crop_x1:crop_x2]
                            
                            if crop.size == 0:
                                continue

                            # Store exact crop windows used for condensate inference
                            crop_entry = {
                                'droplet_index': droplet_idx,
                                'droplet_center': droplet_center,
                                'crop_bbox': (crop_x1, crop_y1, crop_x2, crop_y2),
                                'fam_crop': crop.copy(),
                                'brightfield_crop': brightfield_crop.copy() if brightfield_crop is not None and brightfield_crop.size > 0 else None,
                                'condensate_detections': [],
                            }
                            self.last_condensate_crops.append(crop_entry)
                            
                            # Detect condensates in the crop
                            condensate_results = self.condensate_model.predict(
                                source=crop,
                                conf=conf_threshold,
                                imgsz=self.image_size,
                                save=False,
                                verbose=False
                            )
                            
                            if condensate_results and len(condensate_results) > 0:
                                condensate_result = condensate_results[0]
                                if condensate_result.boxes is not None and len(condensate_result.boxes) > 0:
                                    for c_box in condensate_result.boxes:
                                        # Extract bounding box coordinates relative to crop
                                        c_bbox = c_box.xyxy[0].cpu().numpy()
                                        cx1, cy1, cx2, cy2 = c_bbox

                                        crop_entry['condensate_detections'].append({
                                            'bbox': (float(cx1), float(cy1), float(cx2), float(cy2)),
                                            'confidence': float(c_box.conf[0].cpu().numpy()),
                                            'class_id': int(c_box.cls[0].cpu().numpy()),
                                        })
                                        
                                        # Adjust coordinates back to original frame
                                        orig_x1 = cx1 + crop_x1
                                        orig_y1 = cy1 + crop_y1
                                        orig_x2 = cx2 + crop_x1
                                        orig_y2 = cy2 + crop_y1
                                        
                                        all_bounding_boxes.append((orig_x1, orig_y1, orig_x2, orig_y2))
                                        
                                        # Extract confidence
                                        confidence = float(c_box.conf[0].cpu().numpy())
                                        all_confidences.append(confidence)
                                        
                                        # Extract class information
                                        class_id = int(c_box.cls[0].cpu().numpy())
                                        all_class_ids.append(class_id)
                                        all_class_names.append(self.condensate_model.names[class_id])
                                        
                                        # Track which droplet this detection belongs to
                                        all_droplet_centers.append(droplet_center)
                    else:
                        logger.debug("No droplets detected for cropping")
                else:
                    logger.debug("No droplet detection results")
            else:
                # Direct condensate detection on the frame
                logger.debug("Performing direct condensate detection (no cropping)")
                condensate_results = self.condensate_model.predict(
                    source=frame,
                    conf=conf_threshold,
                    imgsz=self.image_size,
                    save=False,
                    verbose=False
                )
                if condensate_results and len(condensate_results) > 0:
                    condensate_result = condensate_results[0]
                    if condensate_result.boxes is not None and len(condensate_result.boxes) > 0:
                        for box in condensate_result.boxes:
                            # Extract bounding box coordinates
                            bbox = box.xyxy[0].cpu().numpy().tolist()
                            all_bounding_boxes.append(tuple(bbox))
                            
                            # Extract confidence
                            confidence = float(box.conf[0].cpu().numpy())
                            all_confidences.append(confidence)
                            
                            # Extract class information
                            class_id = int(box.cls[0].cpu().numpy())
                            all_class_ids.append(class_id)
                            all_class_names.append(self.condensate_model.names[class_id])
                            
                            # No droplet center for direct detections
                            all_droplet_centers.append(None)
            
            logger.debug(f"Detected {len(all_bounding_boxes)} condensates")

            # Debug mode: ensure at least some detections
            if debug and not all_bounding_boxes:
                frame_h, frame_w = frame.shape[:2]
                if crop_droplet and droplet_image is not None:
                    # Add fake droplet center and condensates
                    fake_droplet_center = (0.0, 0.0)  # normalized center
                    # Add fake condensates around the center
                    fake_bbox1 = (frame_w//2 - 50, frame_h//2 - 50, frame_w//2 + 50, frame_h//2 + 50)
                    all_bounding_boxes.append(fake_bbox1)
                    all_confidences.append(0.99)
                    all_class_ids.append(0)
                    all_class_names.append('condensate')
                    all_droplet_centers.append(fake_droplet_center)
                    
                    fake_bbox2 = (frame_w//4 - 25, frame_h//4 - 25, frame_w//4 + 25, frame_h//4 + 25)
                    all_bounding_boxes.append(fake_bbox2)
                    all_confidences.append(0.95)
                    all_class_ids.append(0)
                    all_class_names.append('condensate')
                    all_droplet_centers.append(fake_droplet_center)
                    
                    logger.debug("Debug mode: Added fake condensates for fake droplet")
                else:
                    # Direct detection: add fake condensates
                    fake_bbox = (frame_w//2 - 50, frame_h//2 - 50, frame_w//2 + 50, frame_h//2 + 50)
                    all_bounding_boxes.append(fake_bbox)
                    all_confidences.append(0.99)
                    all_class_ids.append(0)
                    all_class_names.append('condensate')
                    all_droplet_centers.append(None)
                    
                    logger.debug("Debug mode: Added fake condensates for direct detection")

            # Apply non-maximum suppression to remove overlapping boxes
            if all_bounding_boxes and nms_threshold < 1.0:
                all_bounding_boxes, all_confidences, all_class_ids, all_class_names, all_droplet_centers = self._apply_nms(
                    all_bounding_boxes, all_confidences, all_class_ids, all_class_names, all_droplet_centers, nms_threshold
                )
                logger.debug(f"After NMS ({nms_threshold}): {len(all_bounding_boxes)} condensates")

            # Create annotated frame if requested
            annotated_frame = None
            if return_annotated:
                annotated_frame = self._draw_detections(frame.copy(), all_bounding_boxes, all_confidences, all_class_names, draw_labels)

            return DetectionResult(
                bounding_boxes=all_bounding_boxes,
                confidences=all_confidences,
                class_ids=all_class_ids,
                class_names=all_class_names,
                annotated_frame=annotated_frame,
                droplet_centers=all_droplet_centers if all_droplet_centers else None
            )
            
        except Exception as e:
            logger.error(f"Error during detection: {e}")
            return DetectionResult([], [], [], [])
    
    def _draw_detections(self, frame: np.ndarray, 
                        bounding_boxes: List[Tuple[float, float, float, float]],
                        confidences: List[float],
                        class_names: List[str],
                        draw_labels: bool = True) -> np.ndarray:
        """
        Draw bounding boxes and optionally labels on the frame.
        
        Args:
            frame: Input frame to draw on
            bounding_boxes: List of (x1, y1, x2, y2) coordinates
            confidences: Confidence scores
            class_names: Class names for each detection
            draw_labels: Whether to draw class labels and confidence scores
            
        Returns:
            Frame with bounding boxes drawn
        """
        for bbox, conf, class_name in zip(bounding_boxes, confidences, class_names):
            x1, y1, x2, y2 = map(int, bbox)
            
            # Draw bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 1)
            
            # Draw label with confidence if requested
            if draw_labels:
                label = f"{class_name}: {conf:.2f}"
                label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
                
                # Draw label background
                cv2.rectangle(frame, (x1, y1 - label_size[1] - 10), 
                             (x1 + label_size[0], y1), (0, 255, 0), -1)
                
                # Draw label text
                cv2.putText(frame, label, (x1, y1 - 5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        return frame
    
    def _apply_nms(self, bounding_boxes: List[Tuple[float, float, float, float]],
                   confidences: List[float],
                   class_ids: List[int],
                   class_names: List[str],
                   droplet_centers: Optional[List[Optional[Tuple[float, float]]]],
                   nms_threshold: float) -> Tuple[List[Tuple[float, float, float, float]], List[float], List[int], List[str], Optional[List[Optional[Tuple[float, float]]]]]:
        """
        Apply non-maximum suppression to remove overlapping bounding boxes.
        
        Args:
            bounding_boxes: List of (x1, y1, x2, y2) coordinates
            confidences: Confidence scores
            class_ids: Class IDs
            class_names: Class names
            droplet_centers: Optional list of droplet centers for each detection
            nms_threshold: IoU threshold for suppression
            
        Returns:
            Filtered bounding boxes, confidences, class_ids, class_names, and droplet_centers
        """
        if not bounding_boxes:
            return bounding_boxes, confidences, class_ids, class_names, droplet_centers
        
        # Convert to numpy arrays for easier processing
        boxes = np.array(bounding_boxes)
        scores = np.array(confidences)
        
        # Sort by confidence score (highest first)
        indices = np.argsort(scores)[::-1]
        
        keep = []
        while len(indices) > 0:
            # Keep the box with highest confidence
            current = indices[0]
            keep.append(current)
            
            if len(indices) == 1:
                break
                
            # Calculate IoU with remaining boxes
            remaining = indices[1:]
            current_box = boxes[current]
            
            # Calculate intersection over union (IoU)
            x1 = np.maximum(current_box[0], boxes[remaining, 0])
            y1 = np.maximum(current_box[1], boxes[remaining, 1])
            x2 = np.minimum(current_box[2], boxes[remaining, 2])
            y2 = np.minimum(current_box[3], boxes[remaining, 3])
            
            # Intersection area
            intersection = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
            
            # Union area
            current_area = (current_box[2] - current_box[0]) * (current_box[3] - current_box[1])
            remaining_areas = (boxes[remaining, 2] - boxes[remaining, 0]) * (boxes[remaining, 3] - boxes[remaining, 1])
            union = current_area + remaining_areas - intersection
            
            # IoU
            iou = intersection / union
            
            # Keep boxes with IoU below threshold
            indices = indices[1:][iou <= nms_threshold]
        
        # Return filtered results
        filtered_boxes = [bounding_boxes[i] for i in keep]
        filtered_confidences = [confidences[i] for i in keep]
        filtered_class_ids = [class_ids[i] for i in keep]
        filtered_class_names = [class_names[i] for i in keep]
        filtered_droplet_centers = [droplet_centers[i] for i in keep] if droplet_centers is not None else None
        
        return filtered_boxes, filtered_confidences, filtered_class_ids, filtered_class_names, filtered_droplet_centers
    
    def is_loaded(self) -> bool:
        """Check if models are loaded and ready for inference."""
        return self._models_loaded
    
    def get_model_info(self) -> Dict:
        """Get information about the loaded models."""
        if not self._models_loaded:
            return {}
        
        return {
            'droplet_model_path': str(self.droplet_model_path),
            'condensate_model_path': str(self.condensate_model_path),
            'condensate_classes': self.condensate_model.names,
            'num_condensate_classes': len(self.condensate_model.names),
            'confidence_threshold': self.confidence_threshold,
            'image_size': self.image_size
        }


def detect_condensates(frame: np.ndarray, 
                      droplet_image: Optional[np.ndarray] = None,
                      crop_droplet: bool = True,
                      crop_padding: int = 50,
                      droplet_model_path: Optional[Union[str, Path]] = None,
                      condensate_model_path: Optional[Union[str, Path]] = None,
                      confidence_threshold: float = 0.25,
                      image_size: int = 1024,
                      return_annotated: bool = True,
                      draw_labels: bool = True,
                      nms_threshold: float = 0.5,
                      debug: bool = False) -> DetectionResult:
    """
    Convenience function for one-time condensate detection.
    
    Args:
        frame: Input image as numpy array for condensate detection
        droplet_image: Optional separate image for droplet detection
        crop_droplet: Whether to crop around droplets
        crop_padding: Padding around droplet boxes
        droplet_model_path: Path to droplet model. Defaults to models/droplets.pt
        condensate_model_path: Path to condensate model. Defaults to models/condensates.pt
        confidence_threshold: Minimum confidence for detections
        image_size: Input size for the model
        return_annotated: Whether to return annotated frame
        draw_labels: Whether to draw class labels and confidence scores on bounding boxes
        nms_threshold: Non-maximum suppression threshold (0.0-1.0). Boxes with IoU > threshold are suppressed
        debug: If True, ensures at least some fake detections are returned for testing
        
    Returns:
        DetectionResult with detection information
    """
    detector = CondensateDetector(droplet_model_path, condensate_model_path, confidence_threshold, image_size)
    return detector.detect(frame, droplet_image, crop_droplet, crop_padding, 
                          return_annotated=return_annotated, draw_labels=draw_labels, nms_threshold=nms_threshold, debug=debug)