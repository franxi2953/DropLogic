#!/usr/bin/env python3
"""
Test script for the droplet detector module.

This script demonstrates how to use the DropletDetector class and provides
functionality to test detection with various parameters.
"""

import sys
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict

from .droplet_detector import DropletDetector, detect_droplets


def test_detection_parameters(model_path: Path, test_image_path: Path):
    """Test detection with various parameters to find optimal settings."""
    
    if not model_path.exists():
        print(f"Model file not found: {model_path}")
        return
    
    if not test_image_path.exists():
        print(f"Test image not found: {test_image_path}")
        return
    
    # Load test image
    test_image = cv2.imread(str(test_image_path))
    if test_image is None:
        print(f"Failed to load test image: {test_image_path}")
        return
    
    print(f"Loading model: {model_path}")
    detector = DropletDetector(model_path)
    
    if not detector.is_loaded():
        print("Failed to load model")
        return
    
    model_info = detector.get_model_info()
    print(f"Model classes: {model_info['classes']}")
    print(f"Number of classes: {model_info['num_classes']}")
    
    # Test different confidence thresholds and image sizes
    test_configs = [
        {"conf": 0.1, "imgsz": 640},
        {"conf": 0.2, "imgsz": 640},
        {"conf": 0.3, "imgsz": 640},
        {"conf": 0.4, "imgsz": 640},
        {"conf": 0.1, "imgsz": 1280},
        {"conf": 0.2, "imgsz": 1280},
        {"conf": 0.3, "imgsz": 1280},
        {"conf": 0.4, "imgsz": 1280},
        {"conf": 0.05, "imgsz": 640},
        {"conf": 0.05, "imgsz": 1280},
    ]
    
    print(f"\nTesting image: {test_image_path}")
    print("="*60)
    
    for i, config in enumerate(test_configs):
        print(f"\nTest {i+1}: conf={config['conf']}, imgsz={config['imgsz']}")
        print("-" * 40)
        
        try:
            # Update detector settings
            detector.confidence_threshold = config['conf']
            detector.image_size = config['imgsz']
            
            # Run detection
            result = detector.detect(test_image, return_annotated=True)
            
            if result.bounding_boxes:
                print(f"✓ Found {len(result.bounding_boxes)} detections!")
                
                # Show details of each detection
                for j, (bbox, conf, class_name) in enumerate(zip(
                    result.bounding_boxes, result.confidences, result.class_names)):
                    x1, y1, x2, y2 = bbox
                    print(f"  Detection {j+1}: {class_name} (conf: {conf:.3f})")
                    print(f"    Bbox: [{x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}]")
                
                # Save annotated result
                if result.annotated_frame is not None:
                    output_filename = f"detection_conf{config['conf']}_imgsz{config['imgsz']}.jpg"
                    output_path = Path(__file__).parent / output_filename
                    cv2.imwrite(str(output_path), result.annotated_frame)
                    print(f"    Saved: {output_filename}")
            else:
                print("✗ No detections found")
                
        except Exception as e:
            print(f"✗ Error during detection: {e}")
    
    print("\n" + "="*60)
    print("Testing complete! Check saved images for visual results.")


def test_simple_detection(model_path: Path, test_image_path: Path):
    """Simple test using the convenience function."""
    
    if not model_path.exists() or not test_image_path.exists():
        print("Model or test image not found")
        return
    
    # Load test image
    test_image = cv2.imread(str(test_image_path))
    if test_image is None:
        print("Failed to load test image")
        return
    
    print("Running simple detection test...")
    
    # Use convenience function
    result = detect_droplets(
        frame=test_image,
        model_path=model_path,
        confidence_threshold=0.25,
        return_annotated=True
    )
    
    print(f"Detected {len(result.bounding_boxes)} droplets")
    
    for i, (bbox, conf, class_name) in enumerate(zip(
        result.bounding_boxes, result.confidences, result.class_names)):
        x1, y1, x2, y2 = bbox
        print(f"Droplet {i+1}: {class_name} at ({x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}) conf={conf:.3f}")
    
    # Save result
    if result.annotated_frame is not None:
        output_path = Path(__file__).parent / "simple_detection_result.jpg"
        cv2.imwrite(str(output_path), result.annotated_frame)
        print(f"Result saved to: {output_path}")


if __name__ == "__main__":
    # Default paths - adjust these to match your setup
    default_model_path = Path(__file__).parent / "models" / "best.pt"
    default_test_image = Path(__file__).parent / "test_images" / "test.jpg"

    print("Droplet Detector Test Script")
    print("="*40)

    # Check if model exists
    if not default_model_path.exists():
        print(f"\n❌ Model file not found: {default_model_path}")
        print("\nTo run tests, you need to:")
        print("1. Train a YOLO model following YOLO_Training/droplet_training_guide.md")
        print("2. Or obtain a pre-trained model and place it at the above path")
        print("3. Ensure ultralytics is installed: pip install ultralytics")
        exit(1)

    # Check if test image exists
    if not default_test_image.exists():
        print(f"\n❌ Test image not found: {default_test_image}")
        print("\nTo run tests, you need to:")
        print("1. Place a test microscopy image at the above path")
        print("2. Or modify the test to use a different image path")
        exit(1)

    # Run simple test first
    print("\n1. Simple Detection Test:")
    test_simple_detection(default_model_path, default_test_image)

    # Run parameter testing
    print("\n2. Parameter Testing:")
    test_detection_parameters(default_model_path, default_test_image)
