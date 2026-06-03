#!/usr/bin/env py
"""
Quick test script for condensate detection functionality.
"""

import sys
import os
import cv2
import numpy as np

# Add the DropLogic library root to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

def test_condensate_detection():
    """Test condensate detection with sample images."""

    try:
        # Import the condensate detector
        from droplogic.utils.drop_vision import CondensateDetector, detect_condensates
        print("✓ Successfully imported CondensateDetector")

        # Load test images
        brightfield_path = os.path.join(os.path.dirname(__file__), 'test_images', 'brightfield.jpg')
        fam_path = os.path.join(os.path.dirname(__file__), 'test_images', 'FAM.jpg')
        
        if not os.path.exists(brightfield_path):
            print(f"✗ Brightfield image not found: {brightfield_path}")
            return
        if not os.path.exists(fam_path):
            print(f"✗ FAM image not found: {fam_path}")
            return

        brightfield_frame = cv2.imread(brightfield_path)
        fam_frame = cv2.imread(fam_path)
        
        if brightfield_frame is None:
            print(f"✗ Failed to load brightfield image: {brightfield_path}")
            return
        if fam_frame is None:
            print(f"✗ Failed to load FAM image: {fam_path}")
            return

        print(f"✓ Loaded brightfield image with shape: {brightfield_frame.shape}")
        print(f"✓ Loaded FAM image with shape: {fam_frame.shape}")

        # Test 1: Direct condensate detection on FAM frame (no cropping) with NMS
        print("\n--- Test 1: Direct condensate detection on FAM frame (with NMS) ---")
        try:
            detector = CondensateDetector()
            if detector.is_loaded():
                print("✓ Condensate detector loaded successfully")
                result = detector.detect(fam_frame, crop_droplet=False, draw_labels=False, nms_threshold=0.5)
                print(f"✓ Detection completed. Found {len(result.bounding_boxes)} condensates (after NMS)")
                if result.annotated_frame is not None:
                    print("✓ Annotated frame generated")
                    # Save the annotated image
                    output_path = os.path.join(os.path.dirname(__file__), 'test_images', 'fam_direct_detection_nms.jpg')
                    cv2.imwrite(output_path, result.annotated_frame)
                    print(f"✓ Saved annotated image: {output_path}")
                    
                    # Increase brightness and save
                    brightened = cv2.convertScaleAbs(result.annotated_frame, alpha=1.5, beta=50)
                    bright_output_path = os.path.join(os.path.dirname(__file__), 'test_images', 'fam_direct_detection_nms_bright.jpg')
                    cv2.imwrite(bright_output_path, brightened)
                    print(f"✓ Saved brightened image: {bright_output_path}")
            else:
                print("✗ Condensate detector failed to load models")
        except Exception as e:
            print(f"✗ Error in direct detection: {e}")

        # Test 2: Convenience function with NMS
        print("\n--- Test 2: Convenience function (with NMS) ---")
        try:
            result = detect_condensates(fam_frame, crop_droplet=False, draw_labels=False, nms_threshold=0.5)
            print(f"✓ Convenience function worked. Found {len(result.bounding_boxes)} condensates (after NMS)")
            if result.annotated_frame is not None:
                output_path = os.path.join(os.path.dirname(__file__), 'test_images', 'fam_convenience_detection_nms.jpg')
                cv2.imwrite(output_path, result.annotated_frame)
                print(f"✓ Saved annotated image: {output_path}")
                
                # Increase brightness and save
                brightened = cv2.convertScaleAbs(result.annotated_frame, alpha=1.5, beta=50)
                bright_output_path = os.path.join(os.path.dirname(__file__), 'test_images', 'fam_convenience_detection_nms_bright.jpg')
                cv2.imwrite(bright_output_path, brightened)
                print(f"✓ Saved brightened image: {bright_output_path}")
        except Exception as e:
            print(f"✗ Error in convenience function: {e}")

        # Test 3: With cropping (using brightfield for droplet detection, FAM for condensate detection) with NMS
        print("\n--- Test 3: Detection with cropping (brightfield → FAM) with NMS ---")
        try:
            result = detect_condensates(
                fam_frame,  # Frame to detect condensates in
                droplet_image=brightfield_frame,  # Use brightfield for droplet detection
                crop_droplet=True,
                crop_padding=50,
                draw_labels=False,
                nms_threshold=0.5
            )
            print(f"✓ Cropped detection worked. Found {len(result.bounding_boxes)} condensates (after NMS)")
            if result.annotated_frame is not None:
                output_path = os.path.join(os.path.dirname(__file__), 'test_images', 'fam_cropped_detection_nms.jpg')
                cv2.imwrite(output_path, result.annotated_frame)
                print(f"✓ Saved annotated image: {output_path}")
                
                # Increase brightness and save
                brightened = cv2.convertScaleAbs(result.annotated_frame, alpha=1.5, beta=50)
                bright_output_path = os.path.join(os.path.dirname(__file__), 'test_images', 'fam_cropped_detection_nms_bright.jpg')
                cv2.imwrite(bright_output_path, brightened)
                print(f"✓ Saved brightened image: {bright_output_path}")
        except Exception as e:
            print(f"✗ Error in cropped detection: {e}")

        print("\n✓ All tests completed!")

    except ImportError as e:
        print(f"✗ Failed to import required modules: {e}")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")

if __name__ == "__main__":
    test_condensate_detection()