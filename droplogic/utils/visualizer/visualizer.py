from droplogic.utils.window_manager import bring_window_to_front
import time
import cv2
import threading
import numpy as np
import sys
import os
import platform
from queue import Queue, Empty

# Add the DropLogic library root to the path for proper module imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from droplogic.utils.hardware_utils.utils import stage_to_electrode, stage_to_electrode_float
from droplogic.utils.logging_config import setup_droplogic_logger


def _resolve_host_platform(box):
    runtime = getattr(box, "host_platform", None) if box is not None else None
    if isinstance(runtime, dict):
        return runtime

    system = platform.system() or "Unknown"
    return {
        "system": system,
        "normalized_system": {
            "Darwin": "macos",
            "Windows": "windows",
            "Linux": "linux",
        }.get(system, system.lower()),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "gui_requires_main_thread": system == "Darwin",
    }

# ————————————————————————————————————————————————
# 1) StreamerVisualizer: streams from a device + optional processor
# ————————————————————————————————————————————————

class StreamerVisualizer:
    def __init__(self,
                 device=None,
                 external_frame_processor=lambda f: f,
                 window_name="Live Stream",
                 exposure_time_us=10_000,
                 exit_flag=None,
                 box=None,
                 record_movie=False,                   # ← recording metadata for executor
                 movie_filename=None,                  # ← output movie filename
                 movie_fps=30):                        # ← movie frame rate metadata
        """
        device: any object with capture_image() -> np.ndarray
        external_frame_processor: function(frame: np.ndarray) -> np.ndarray
        """
        self.device = device
        self.external_frame_processor = external_frame_processor
        self.window_name = window_name
        self.exposure_time = exposure_time_us / 1_000_000
        self.box = box

        # If box is not provided but device is part of a BOXMini, try to get the box reference
        if self.box is None and hasattr(device, 'parent'):
            self.box = device.parent

        # Load config from parent DropSystem class if available
        if self.box and hasattr(self.box, 'config'):
            self.config = self.box.config
        else:
            self.config = {}

        if exit_flag is not None:
            self.flag_exit = exit_flag
        else:
            self.flag_exit = threading.Event()

        self.frame_lock = threading.Lock()
        self.raw_frame = None
        self.proc_frame = None
        self.thread = None
        self.capture_thread = None
        self.display_thread = None
        self.host_platform = _resolve_host_platform(self.box)
        self._display_active = False
        self._window_mode = "background"
        self.window_size = (960, 720)
        self.placeholder_frame_shape = (720, 960, 3)

        self.coordinates = False
        self.electrode_overlay = False
        self.droplet_detection_overlay = False  # Enable/disable droplet detection overlay

        self.electrode_width_px = 375  # Width of each electrode rectangle in pixels
        self.electrode_height_px = 375  # Height of each electrode rectangle in pixels
        self.electrode_spacing_x_px = 5  # Horizontal spacing between electrodes in pixels
        self.electrode_spacing_y_px = 5  # Vertical spacing between electrodes in pixels
        self.offset_range = 2  # How many electrodes to show in each direction

        # Store the current FOV electrodes for API access
        self.current_fov_electrodes = []

        # Droplet detection settings
        self.droplet_detector = None
        self.detection_confidence_threshold = 0.25
        self.detection_box_color = (0, 255, 0)  # Green bounding boxes
        self.detection_text_color = (255, 255, 255)  # White text
        self.detection_box_thickness = 2

        # Condensate detection settings
        self.condensate_detector = None
        self.condensate_detection_overlay = False
        self.condensate_confidence_threshold = 0.25
        self.condensate_box_color = (255, 0, 255)  # Purple bounding boxes
        self.condensate_text_color = (255, 255, 255)  # White text
        self.condensate_box_thickness = 2
        self.condensate_crop_droplet = True
        self.condensate_crop_padding = 50

        # Movie recording metadata used by PlanExecutor's synchronized recorder.
        self.record_movie = record_movie
        self.movie_filename = movie_filename or f"streamer_recording_{int(time.time())}.mp4"
        self.movie_fps = movie_fps
        self.movie_segment_duration_seconds = None
        self.movie_segment_frame_limit = None

        # Set up logger for this module
        self.logger = setup_droplogic_logger('droplogic.utils.visualizer', console_output=False)

    def requires_main_thread_window(self):
        return bool(self.host_platform.get("gui_requires_main_thread"))

    def is_running(self):
        return bool(
            self._display_active
            or (self.capture_thread is not None and self.capture_thread.is_alive())
            or (self.display_thread is not None and self.display_thread.is_alive())
        )

    def start(self, stop_condition=None):
        """Start capture immediately and display in the safest mode for the host OS."""
        if self.is_running():
            self._bring_to_front()
            return

        self.flag_exit.clear()
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name=f"{self.window_name}_capture",
        )
        self.capture_thread.start()

        if self.requires_main_thread_window():
            self._window_mode = "foreground"
            if threading.current_thread() is not threading.main_thread():
                self.logger.warning(
                    "Skipping %s window creation on %s because GUI windows require the main thread",
                    self.window_name,
                    self.host_platform.get("system", "this OS"),
                )
                return

            self._display_loop(stop_condition=stop_condition)
            return

        self._window_mode = "background"
        self.display_thread = threading.Thread(
            target=self._display_loop,
            kwargs={"stop_condition": stop_condition},
            daemon=True,
            name=f"{self.window_name}_display",
        )
        self.display_thread.start()
        self.thread = self.display_thread  # For backward compatibility
        self._bring_to_front()

    def set_device(self, device):
        """Switch to a different capture device at runtime."""
        with self.frame_lock:
            self.device = device

    def set_processor(self, fn):
        """Install a new frame-processor callback.
        WARNING: MAKE A COPY OF THE FRAME (raw_frame.copy()) IF YOU PLAN TO MODIFY IT!
        DONT MODIFY THE raw_frame VARIABLE!"""

        self.external_frame_processor = fn

    def _capture_loop(self):
        while not self.flag_exit.is_set():
            with self.frame_lock:
                dev = self.device

            if dev is not None:
                try:
                    # Check if device has a capture_lock (like CameraV1)
                    if hasattr(dev, 'capture_lock'):
                        with dev.capture_lock:
                            frame = dev.capture_image()
                    else:
                        frame = dev.capture_image()
                        # for debug show size of image
                        # print(f"Captured frame size: {frame.shape if frame is not None else 'None'}")

                    if frame is not None:
                        # Ensure frame is in color format (BGR) for consistent processing
                        if len(frame.shape) == 2:  # Grayscale
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                        with self.frame_lock:
                            self.raw_frame = frame.copy()
                            try:
                                self.proc_frame = self.internal_frame_processor(self.raw_frame.copy())
                                if self.external_frame_processor is not None:
                                    self.proc_frame = self.external_frame_processor(self.proc_frame)
                            except Exception:
                                self.proc_frame = self.raw_frame.copy()
                    else:
                        # If frame is None (camera closed), clear the frames
                        with self.frame_lock:
                            self.raw_frame = None
                            self.proc_frame = None
                except Exception as e:
                    # Log the error but don't crash the thread
                    self.logger.warning(f"Capture error: {e}")
                    # Clear frames on error to prevent stale data
                    with self.frame_lock:
                        self.raw_frame = None
                        self.proc_frame = None

            # Frame rate pacing (e.g., 50 ms = 20 fps)
            # time.sleep(self.exposure_time)

    def _display_loop(self, stop_condition=None):
        self._display_active = True
        try:
            try:
                cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
            except Exception as e:
                self.logger.warning(f"Failed to create window '{self.window_name}': {e}")
                return

            time.sleep(0.1)
            self._bring_to_front()

            while not self.flag_exit.is_set():
                if stop_condition is not None and stop_condition():
                    self.flag_exit.set()
                    break

                try:
                    with self.frame_lock:
                        img = None if self.proc_frame is None else self.proc_frame.copy()

                        if img is not None:
                            # Get current window size
                            _, _, win_w, win_h = cv2.getWindowImageRect(self.window_name)

                            # Define target aspect ratio, e.g., 4:3 or match original frame
                            aspect_ratio = img.shape[1] / img.shape[0]  # width / height

                            # Adjust window size to keep aspect ratio
                            if win_w / win_h > aspect_ratio:
                                # Window is too wide, adjust width
                                new_h = win_h
                                new_w = int(aspect_ratio * new_h)
                            else:
                                # Window is too tall, adjust height
                                new_w = win_w
                                new_h = int(new_w / aspect_ratio)

                            resized_img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

                            # Add black padding to center it in window if needed
                            padded = np.zeros((win_h, win_w, 3), dtype=np.uint8)
                            x_offset = (win_w - new_w) // 2
                            y_offset = (win_h - new_h) // 2
                            padded[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_img

                            cv2.imshow(self.window_name, padded)
                        else:
                            # still pump events so window stays responsive
                            empty_frame = np.zeros((10,10,3), np.uint8)
                            cv2.imshow(self.window_name, empty_frame)

                        key = cv2.waitKey(1)
                        if key & 0xFF == ord('q'):
                            self.flag_exit.set()
                            break
                except Exception as e:
                    self.logger.warning(f"Display loop error: {e}")
                    if "window" in str(e).lower():
                        # Window was closed externally
                        self.flag_exit.set()
                        break
                    time.sleep(0.1)  # Brief pause on error
        finally:
            self._display_active = False
            self.thread = None
            self.display_thread = None
            try:
                cv2.destroyWindow(self.window_name)
            except:
                pass

    def internal_frame_processor(self, frame):
        if self.box is None:
            return frame

        # Store droplet detection results if enabled (run detection before overlays)
        detection_results = None
        if self.droplet_detection_overlay and self.droplet_detector is not None and self.droplet_detector.is_loaded():
            try:
                # Run detection on the raw frame before any overlays
                detection_results = self.droplet_detector.detect(
                    frame,
                    confidence_threshold=self.detection_confidence_threshold,
                    return_annotated=False  # We'll draw our own annotations later
                )
            except Exception as e:
                self.logger.warning(f"Droplet detection error: {e}")

        # Store condensate detection results if enabled (run detection before overlays)
        condensate_results = None
        if self.condensate_detection_overlay and self.condensate_detector is not None and self.condensate_detector.is_loaded():
            try:
                # Run condensate detection on the raw frame before any overlays
                condensate_results = self.condensate_detector.detect(
                    frame,
                    droplet_image=frame if self.condensate_crop_droplet else None,  # Use same frame for droplet detection if cropping
                    crop_droplet=self.condensate_crop_droplet,
                    crop_padding=self.condensate_crop_padding,
                    confidence_threshold=self.condensate_confidence_threshold,
                    return_annotated=False  # We'll draw our own annotations later
                )
            except Exception as e:
                self.logger.warning(f"Condensate detection error: {e}")

        # Apply coordinates overlay
        if self.coordinates:
            pos = self.box.state["xy_stage"]["position"]
            cv2.putText(frame, f"X:{pos['X']} Y:{pos['Y']} Z:{pos['Z']}",
                        (10,40), cv2.FONT_HERSHEY_SIMPLEX, 2, (0,255,0), 2)

        # Apply electrode overlay
        if self.electrode_overlay:
            if "electrode_matrix" in self.box.state:
                try:
                    # Get frame dimensions
                    height, width = frame.shape[:2]
                    center_x, center_y = width // 2, height // 2

                    # Get current electrode matrix state
                    matrix = self.box.state["electrode_matrix"]["matrix"]

                    # Get matrix dimensions
                    if len(matrix) == 0:
                        return frame

                    matrix_rows = len(matrix)
                    matrix_cols = len(matrix[0]) if matrix_rows > 0 else 0

                    # Get current electrode position based on stage coordinates
                    # Always use fresh position from hardware for accurate overlay positioning
                    if hasattr(self.box, 'xy_stage') and self.box.xy_stage:
                        try:
                            # Always get fresh position from hardware for accurate overlay
                            fresh_x = self.box.xy_stage.get_position("X")
                            fresh_y = self.box.xy_stage.get_position("Y")
                            fresh_z = self.box.xy_stage.get_position("Z")
                            pos = {"X": fresh_x, "Y": fresh_y, "Z": fresh_z}
                        except Exception:
                            pos = self.box.state["xy_stage"]["position"]
                    else:
                        pos = self.box.state["xy_stage"]["position"]

                    try:
                        # Use floating-point electrode coordinates for precise overlay positioning
                        electrode_pos_float = stage_to_electrode_float((pos["X"], pos["Y"]))

                        if electrode_pos_float is None:
                            # Default to electrode 0,0 if stage position is outside the grid
                            current_row, current_col = 0, 0
                        else:
                            # Use floating-point coordinates for sub-pixel accuracy
                            current_row, current_col = electrode_pos_float[0], electrode_pos_float[1]

                    except Exception as e:
                        print(f"Error in stage_to_electrode_float: {e}")
                        return frame
                except Exception as e:
                    print(f"Error in electrode overlay: {e}")
                    return frame
                
                # Create overlay for transparent drawing
                overlay = np.zeros_like(frame, dtype=np.uint8)
                
                # Calculate total size of electrode cells (including spacing)
                total_cell_width = self.electrode_width_px + self.electrode_spacing_x_px
                total_cell_height = self.electrode_height_px + self.electrode_spacing_y_px

                # Reset FOV electrodes list
                self.current_fov_electrodes = []

                # Calculate which electrodes should be visible in the current camera frame
                # Instead of drawing in a fixed grid pattern, calculate based on camera position

                # Calculate the electrode range that would be visible in the camera frame
                # Camera center corresponds to (current_row, current_col) electrode position
                # We need to find which electrodes would appear in the frame

                # Calculate how many electrodes fit in the frame dimensions
                electrodes_per_frame_width = frame.shape[1] / total_cell_width
                electrodes_per_frame_height = frame.shape[0] / total_cell_height

                # Calculate the electrode range visible in frame (centered on current position)
                # Add minimal padding to avoid including extra electrodes at the edges
                padding = 0.25  # Reduced padding for more accurate FOV calculation
                min_visible_row = current_row - electrodes_per_frame_height / 2 - padding
                max_visible_row = current_row + electrodes_per_frame_height / 2 + padding
                min_visible_col = current_col - electrodes_per_frame_width / 2 - padding
                max_visible_col = current_col + electrodes_per_frame_width / 2 + padding

                # Draw electrodes that would be visible in the current frame
                for electrode_row in range(max(0, int(min_visible_row)), min(matrix_rows, int(max_visible_row) + 2)):
                    for electrode_col in range(max(0, int(min_visible_col)), min(matrix_cols, int(max_visible_col) + 2)):
                        # Calculate exact floating-point position for this electrode
                        electrode_row_float = float(electrode_row)
                        electrode_col_float = float(electrode_col)

                        # Add to FOV electrodes list
                        self.current_fov_electrodes.append([electrode_row, electrode_col])

                        # Determine if electrode is active (convert to 0-indexed for matrix access)
                        try:
                            # Using 0-indexed coordinates directly
                            is_active = matrix[electrode_row][electrode_col] > 0
                            color = (0, 255, 0) if is_active else (0, 0, 255)  # Green if active, Red if inactive

                            # Calculate position offset from center using floating-point precision
                            # Account for 90-degree clockwise rotation between matrix and visualization:
                            # - row in matrix becomes column in visualization (going right)
                            # - column in matrix becomes row in visualization (going down, but inverted)
                            x_offset = -(electrode_row_float - current_row) * total_cell_width
                            y_offset = (electrode_col_float - current_col) * total_cell_height

                            # Draw rectangle on overlay
                            half_width = self.electrode_width_px // 2
                            half_height = self.electrode_height_px // 2
                            top_left = (int(center_x + x_offset - half_width), int(center_y + y_offset - half_height))
                            bottom_right = (int(center_x + x_offset + half_width), int(center_y + y_offset + half_height))

                            # Check if rectangle is within frame bounds
                            frame_h, frame_w = frame.shape[:2]
                            if (top_left[0] >= 0 and top_left[1] >= 0 and
                                bottom_right[0] < frame_w and bottom_right[1] < frame_h):
                                cv2.rectangle(overlay, top_left, bottom_right, color, 3)

                            # Add electrode coordinates text in a rounded rectangle background
                            text = f"{electrode_row},{electrode_col}"
                            text_pos = (top_left[0] + 5, top_left[1] + 40)  # Moved down by 10 pixels

                            # Get text size for background rectangle (using thicker font)
                            (text_width, text_height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.8, 4)

                            # Draw rounded rectangle background on overlay
                            bg_top_left = (text_pos[0] - 5, text_pos[1] - text_height - 5)
                            bg_bottom_right = (text_pos[0] + text_width + 5, text_pos[1] + 5)

                            # Draw filled rounded rectangle on overlay
                            cv2.rectangle(overlay, bg_top_left, bg_bottom_right, color, -1)

                            # Add white text on overlay with bolder font (thicker strokes)
                            cv2.putText(overlay, text, text_pos, cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 4)
                        except (IndexError, TypeError) as e:
                            print(f"[DEBUG] Error drawing electrode ({electrode_row}, {electrode_col}): {e}")
                            # Skip this electrode if there's an error
                            return frame
                
                # Blend overlay onto frame with 20% opacity (80% transparency)
                frame = cv2.addWeighted(frame, 1.0, overlay, 0.2, 0)

        # Draw droplet detection bounding boxes on top of overlays
        if detection_results is not None:
            # Draw bounding boxes and labels
            for bbox, conf, class_name in zip(
                detection_results.bounding_boxes, detection_results.confidences, detection_results.class_names):

                x1, y1, x2, y2 = map(int, bbox)

                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2),
                            self.detection_box_color, self.detection_box_thickness)

                # Prepare label text
                label = f"{class_name}: {conf:.2f}"

                # Get text size for background
                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)

                # Draw label background
                cv2.rectangle(frame,
                            (x1, y1 - text_height - baseline - 5),
                            (x1 + text_width, y1),
                            self.detection_box_color, -1)

                # Draw label text
                cv2.putText(frame, label, (x1, y1 - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                          self.detection_text_color, 2)

            # Add detection count info
            if detection_results.bounding_boxes:
                count_text = f"Droplets: {len(detection_results.bounding_boxes)}"
                cv2.putText(frame, count_text, (10, 80),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                          self.detection_text_color, 2)

        # Draw condensate detection bounding boxes on top of overlays
        if condensate_results is not None:
            # Draw bounding boxes and labels
            for bbox, conf, class_name in zip(
                condensate_results.bounding_boxes, condensate_results.confidences, condensate_results.class_names):

                x1, y1, x2, y2 = map(int, bbox)

                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2),
                            self.condensate_box_color, self.condensate_box_thickness)

                # Prepare label text
                label = f"{class_name}: {conf:.2f}"

                # Get text size for background
                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)

                # Draw label background
                cv2.rectangle(frame,
                            (x1, y1 - text_height - baseline - 5),
                            (x1 + text_width, y1),
                            self.condensate_box_color, -1)

                # Draw label text
                cv2.putText(frame, label, (x1, y1 - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                          self.condensate_text_color, 2)

            # Add detection count info
            if condensate_results.bounding_boxes:
                count_text = f"Condensates: {len(condensate_results.bounding_boxes)}"
                cv2.putText(frame, count_text, (10, 110),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                          self.condensate_text_color, 2)

        return frame
    
    def enable_droplet_detection(self, model_path=None, confidence_threshold=0.25):
        """Enable droplet detection overlay.
        
        Args:
            model_path: Path to YOLO model. If None, uses default models/best.pt
            confidence_threshold: Minimum confidence for detections
        """
        try:
            from droplogic.utils.drop_vision import DropletDetector
            self.droplet_detector = DropletDetector(
                model_path=model_path,
                confidence_threshold=confidence_threshold
            )
            self.detection_confidence_threshold = confidence_threshold
            self.droplet_detection_overlay = True
            self.logger.info(f"Droplet detection enabled with confidence threshold: {confidence_threshold}")
        except ImportError as e:
            self.logger.error(f"Failed to enable droplet detection: {e}")
            self.logger.error("Make sure the drop_vision module is available")
        except Exception as e:
            self.logger.error(f"Error initializing droplet detector: {e}")
    
    def disable_droplet_detection(self):
        """Disable droplet detection overlay."""
        self.droplet_detection_overlay = False
        self.droplet_detector = None
        self.logger.debug("Droplet detection disabled")
    
    def enable_condensate_detection(self, droplet_model_path=None, condensate_model_path=None, 
                                   confidence_threshold=0.25, crop_droplet=True, crop_padding=50):
        """Enable condensate detection overlay.
        
        Args:
            droplet_model_path: Path to droplet YOLO model. If None, uses default models/droplets.pt
            condensate_model_path: Path to condensate YOLO model. If None, uses default models/condensates.pt
            confidence_threshold: Minimum confidence for detections
            crop_droplet: Whether to crop around detected droplets before condensate detection
            crop_padding: Padding in pixels around droplet bounding boxes for cropping
        """
        try:
            from droplogic.utils.drop_vision import CondensateDetector
            self.condensate_detector = CondensateDetector(
                droplet_model_path=droplet_model_path,
                condensate_model_path=condensate_model_path,
                confidence_threshold=confidence_threshold
            )
            self.condensate_confidence_threshold = confidence_threshold
            self.condensate_crop_droplet = crop_droplet
            self.condensate_crop_padding = crop_padding
            self.condensate_detection_overlay = True
            self.logger.info(f"Condensate detection enabled with confidence threshold: {confidence_threshold}, crop_droplet: {crop_droplet}")
        except ImportError as e:
            self.logger.error(f"Failed to enable condensate detection: {e}")
            self.logger.error("Make sure the drop_vision module is available")
        except Exception as e:
            self.logger.error(f"Error initializing condensate detector: {e}")
    
    def disable_condensate_detection(self):
        """Disable condensate detection overlay."""
        self.condensate_detection_overlay = False
        self.condensate_detector = None
        self.logger.debug("Condensate detection disabled")
    
    def set_detection_style(self, box_color=(0, 255, 0), text_color=(255, 255, 255), box_thickness=2):
        """Configure detection overlay appearance.
        
        Args:
            box_color: BGR color tuple for bounding boxes
            text_color: BGR color tuple for text labels
            box_thickness: Thickness of bounding box lines
        """
        self.detection_box_color = box_color
        self.detection_text_color = text_color
        self.detection_box_thickness = box_thickness
    
    def set_condensate_detection_style(self, box_color=(255, 0, 255), text_color=(255, 255, 255), box_thickness=2):
        """Configure condensate detection overlay appearance.
        
        Args:
            box_color: BGR color tuple for bounding boxes (default purple)
            text_color: BGR color tuple for text labels
            box_thickness: Thickness of bounding box lines
        """
        self.condensate_box_color = box_color
        self.condensate_text_color = text_color
        self.condensate_box_thickness = box_thickness
    
    def _add_droplet_detection_overlay(self, frame):
        """Add droplet detection bounding boxes to frame.
        
        Args:
            frame: Input frame (numpy array)
            
        Returns:
            Frame with detection overlay
        """
        if self.droplet_detector is None or not self.droplet_detector.is_loaded():
            return frame
        
        try:
            # Run detection on the frame
            result = self.droplet_detector.detect(
                frame, 
                confidence_threshold=self.detection_confidence_threshold,
                return_annotated=False  # We'll draw our own annotations
            )
            
            # Draw bounding boxes and labels
            for bbox, conf, class_name in zip(
                result.bounding_boxes, result.confidences, result.class_names):
                
                x1, y1, x2, y2 = map(int, bbox)
                
                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), 
                            self.detection_box_color, self.detection_box_thickness)
                
                # Prepare label text
                label = f"{class_name}: {conf:.2f}"
                
                # Get text size for background
                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                
                # Draw label background
                cv2.rectangle(frame, 
                            (x1, y1 - text_height - baseline - 5),
                            (x1 + text_width, y1),
                            self.detection_box_color, -1)
                
                # Draw label text
                cv2.putText(frame, label, (x1, y1 - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, 
                          self.detection_text_color, 2)
            
            # Add detection count info
            if result.bounding_boxes:
                count_text = f"Droplets: {len(result.bounding_boxes)}"
                cv2.putText(frame, count_text, (10, 80),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.8, 
                          self.detection_text_color, 2)
            
        except Exception as e:
            # Don't crash the visualizer if detection fails
            self.logger.warning(f"Detection error: {e}")
        
        return frame

    def _bring_to_front(self):

        # Bring window to front OS gracefully
        try:
            bring_window_to_front(self.window_name)
        except Exception:
            pass

    def get_electrodes_in_fov(self):
        """
        Get list of electrode coordinates that are currently in the field of view.
        This returns the electrodes that are actually being drawn in the overlay.

        Returns:
            List of [row, col] electrode coordinates (0-indexed) in the current FOV
        """
        return self.current_fov_electrodes.copy()

    def get_raw_frame(self):
        """
        Get the last buffered raw frame without blocking the frame refreshing process.

        This method provides thread-safe access to the most recent raw frame captured
        by the visualizer, allowing external components to access frames without
        interfering with the continuous capture loop.

        Returns:
            numpy.ndarray or None: The last captured raw frame, or None if no frame is available
        """
        with self.frame_lock:
            return self.raw_frame.copy() if self.raw_frame is not None else None

    def get_processed_frame(self):
        """
        Get the last buffered processed frame without blocking the frame refreshing process.

        This method provides thread-safe access to the most recent processed frame,
        which includes all overlays and external processing applied by the visualizer.

        Returns:
            numpy.ndarray or None: The last processed frame, or None if no frame is available
        """
        with self.frame_lock:
            return self.proc_frame.copy() if self.proc_frame is not None else None

    def get_snapshot_frame(self):
        """
        Return a stable frame for snapshotting or executor-synchronised recording.

        Prefers the latest processed frame, then raw frame, and finally falls back to
        a placeholder canvas so downstream recorders can still keep frame parity.
        """
        with self.frame_lock:
            if self.proc_frame is not None:
                return self.proc_frame.copy()
            if self.raw_frame is not None:
                return self.raw_frame.copy()

        empty_frame = np.zeros(self.placeholder_frame_shape, np.uint8)
        cv2.putText(
            empty_frame,
            "Waiting for live microscope frames...",
            (40, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (180, 180, 180),
            2,
        )
        return empty_frame

    def stop(self):
        self.flag_exit.set()
        current_thread = threading.current_thread()

        # Wait for threads to finish with longer timeout
        if self.capture_thread and self.capture_thread.is_alive() and self.capture_thread is not current_thread:
            self.capture_thread.join(timeout=3.0)
            if self.capture_thread.is_alive():
                self.logger.warning(f"Capture thread for {self.window_name} did not stop gracefully")
        if self.display_thread and self.display_thread.is_alive() and self.display_thread is not current_thread:
            self.display_thread.join(timeout=3.0)
            if self.display_thread.is_alive():
                self.logger.warning(f"Display thread for {self.window_name} did not stop gracefully")
        if self.thread and hasattr(self.thread, "is_alive") and self.thread.is_alive() and self.thread is not current_thread:
            self.thread.join(timeout=3.0)

        # Force destroy window with multiple attempts
        for attempt in range(5):
            try:
                if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) >= 0:
                    cv2.destroyWindow(self.window_name)
                    time.sleep(0.2)
                else:
                    break
            except:
                break

        # Final cleanup - destroy all windows as fallback
        try:
            cv2.destroyAllWindows()
        except:
            pass

class MatrixVisualizer:
    """
    Live visualiser for BOXMini’s electrode matrix.

    * Reads `box.state["electrode_matrix"]["matrix"]` (rows×cols list/array)
      on every refresh.
    * Optionally blends a background camera frame behind that matrix.
    * Quit when the shared `exit_flag` is set or when the user presses ‘q’.
    """

    def __init__(self,
                 box,                                   # ← BOXMini instance
                 window_name="Matrix Display",
                 matrix_size=(680, 600),
                 margins=(18,80,15,57),             # top, right, bottom, left
                 bg_rotation_deg=0.8,
                 exit_flag=None,
                 paths=None,                           # ← new parameter for droplet paths
                 record_movie=False,                   # ← recording metadata for executor
                 movie_filename=None,                  # ← output movie filename
                 movie_fps=30,                         # ← movie frame rate metadata
                 matrix_rotation_degrees=90):

        self.box         = box
        self.window_name = window_name
        self.matrix_size = matrix_size
        self.margins     = margins
        self.bg_rot      = bg_rotation_deg
        self.matrix_rotation_degrees = self._normalize_matrix_rotation_degrees(
            matrix_rotation_degrees
        )

        self.background  = None                       # optional camera frame
        self.flag_exit   = exit_flag or threading.Event()
        self.lock        = threading.Lock()
        self.thread      = None
        self.host_platform = _resolve_host_platform(self.box)
        self._display_active = False
        self._window_mode = "background"
        
        # Path tracking for droplet trajectories
        self.paths       = paths or []                # list of paths (each path is a list of (row, col) positions)
        self.path_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]  # BGR colors

        # Breakpoint visualization
        self.breakpoint_positions = {}                # Dict: frame_num -> list of (row, col) positions
        self.current_frame = 0                        # Current frame being displayed
        
        # Movie recording metadata used by PlanExecutor's synchronized recorder.
        self.record_movie = record_movie
        self.movie_filename = movie_filename or f"droplet_simulation_{int(time.time())}.mp4"
        self.movie_fps = movie_fps
        self.movie_segment_duration_seconds = None
        self.movie_segment_frame_limit = None

        # Mouse callback
        self.mouse_callback = None
        self.electrode_click_callback = None
        self.last_canvas_shape = None
        self.last_display_shape = None
        self.last_matrix_shape = None

    # ───────────────────────────── public API ────────────────────────────────
    def requires_main_thread_window(self):
        return bool(self.host_platform.get("gui_requires_main_thread"))

    def is_running(self):
        return self._display_active or (self.thread is not None and self.thread.is_alive())

    def start(self, stop_condition=None):
        if self.is_running():
            self._bring_to_front()
            return

        self.flag_exit.clear()
        if self.requires_main_thread_window():
            self._window_mode = "foreground"
            if threading.current_thread() is not threading.main_thread():
                print(
                    f"[Visualizer] Skipping '{self.window_name}' window creation on "
                    f"{self.host_platform.get('system', 'this OS')} because GUI windows require the main thread."
                )
                return

            self._run_display(stop_condition=stop_condition)
            return

        self._window_mode = "background"
        self.thread = threading.Thread(
            target=self._run_display,
            kwargs={"stop_condition": stop_condition},
            daemon=False,  # Not daemon so we can wait for it
        )
        self.thread.start()
        self._bring_to_front()

    def set_background(self, frame):
        with self.lock:
            self.background = frame.copy()

    def set_matrix_rotation(self, degrees):
        """Set display rotation for the electrode matrix in clockwise degrees."""
        with self.lock:
            self.matrix_rotation_degrees = self._normalize_matrix_rotation_degrees(degrees)

    def set_electrode_click_callback(self, callback):
        """Set callback receiving clicked electrode as (row, col)."""
        with self.lock:
            self.electrode_click_callback = callback
    
    def set_paths(self, paths):
        """Update the droplet paths to be displayed.
        
        Args:
            paths: List of paths, where each path is a list of (row, col) positions
                  representing droplet trajectory positions (0-indexed)
        """
        with self.lock:
            self.paths = paths or []
    
    def add_path(self, path):
        """Add a single droplet path to the visualization.

        Args:
            path: List of (row, col) positions representing droplet trajectory (0-indexed)
        """
        with self.lock:
            self.paths.append(path)

    def set_breakpoint_positions(self, positions):
        """Set all breakpoint positions for all frames.

        Args:
            positions: Dict mapping frame_num -> list of (row, col) tuples
        """
        with self.lock:
            self.breakpoint_positions = positions.copy()

    def set_current_frame(self, frame_num):
        """Set the current frame being displayed.

        Args:
            frame_num: Current frame number
        """
        with self.lock:
            self.current_frame = frame_num
    
    def clear_paths(self):
        """Clear all droplet paths from the visualization."""
        with self.lock:
            self.paths = []

    def get_snapshot_frame(self):
        """Render and return the current matrix frame for snapshots or executor recording."""
        try:
            mat = self.box.state["electrode_matrix"]["matrix"]
            mat_np = np.array(mat, dtype=int)
        except Exception:
            return None

        with self.lock:
            bg = None if self.background is None else self.background.copy()

        try:
            return self._compose_frame(mat_np, bg)
        except Exception:
            return None

    def save_snapshot(self, output_path):
        """Render the current matrix visualizer frame and save it to disk."""
        frame = self.get_snapshot_frame()
        if frame is None:
            return False

        try:
            output_path = os.path.abspath(str(output_path))
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            return bool(cv2.imwrite(output_path, frame))
        except Exception:
            return False

    # ───────────────────────────── internal loop ─────────────────────────────
    def _run_display(self, stop_condition=None):
        self._display_active = True
        try:
            try:
                cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
                cv2.resizeWindow(self.window_name, *self.matrix_size)
            except Exception as e:
                print(f"[Visualizer] Failed to create '{self.window_name}' window: {e}")
                return

            time.sleep(0.1)
            self._bring_to_front()

            cv2.setMouseCallback(self.window_name, self._handle_mouse_event)

            prev_size = (0, 0)
            while not self.flag_exit.is_set():
                if stop_condition is not None and stop_condition():
                    self.flag_exit.set()
                    break

                # 1) fetch the latest electrode matrix straight from BOXMini
                mat = self.box.state["electrode_matrix"]["matrix"]
                # ensure numpy int array
                mat_np = np.array(mat, dtype=int)

                # 2) copy latest background (if any) under lock
                with self.lock:
                    bg = None if self.background is None else self.background.copy()

                # 3) build the canvas ------------------------------------------------
                canvas = self._compose_frame(mat_np, bg)

                # 4) show + keep aspect ratio ---------------------------------------
                try:
                    _, _, win_w, win_h = cv2.getWindowImageRect(self.window_name)
                except cv2.error:
                    win_w, win_h = 0, 0
                if win_w > 0 and win_h > 0:
                    h, w = canvas.shape[:2]
                    ar = w / h
                    if win_w / win_h > ar:
                        nw, nh = int(win_h * ar), win_h
                    else:
                        nw, nh = win_w, int(win_w / ar)
                    if abs(nw - prev_size[0]) > 2 or abs(nh - prev_size[1]) > 2:
                        cv2.resizeWindow(self.window_name, nw, nh)
                        prev_size = (nw, nh)
                    disp = cv2.resize(canvas, (nw, nh), interpolation=cv2.INTER_AREA)
                else:
                    disp = canvas

                with self.lock:
                    self.last_canvas_shape = canvas.shape[:2]
                    self.last_display_shape = disp.shape[:2]
                    self.last_matrix_shape = mat_np.shape

                cv2.imshow(self.window_name, disp)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.flag_exit.set()
                    break
        finally:
            self._display_active = False
            self.thread = None
            try:
                cv2.destroyWindow(self.window_name)
            except:
                pass

    # ───────────────────────── helper building the frame ─────────────────────
    def _compose_frame(self, matrix, bg):
        """Return a BGR image of size self.matrix_size ready for display."""
        # background (optionally rotated)
        if bg is not None:
            if self.bg_rot % 360 != 0:
                bg = self._rotate_image(bg, self.bg_rot)
            canvas = cv2.resize(bg, self.matrix_size,
                                interpolation=cv2.INTER_AREA)
        else:
            canvas = np.zeros((self.matrix_size[1],
                               self.matrix_size[0], 3), np.uint8)

        # Calculate margins for coordinate conversion (needed for paths and breakpoints)
        top, right, bottom, left = self.margins
        W, H = self.matrix_size
        region_w = W - left - right
        region_h = H - top - bottom

        # ───── overlay droplet paths with individual semi-transparency ──────
        with self.lock:
            paths_copy = self.paths.copy()

        if paths_copy:
            rows_orig, cols_orig = matrix.shape

            for path_idx, path in enumerate(paths_copy):
                if len(path) < 2:
                    continue  # Need at least 2 points to draw a line

                # Create individual overlay for this trajectory
                trajectory_overlay = np.zeros_like(canvas, dtype=np.uint8)

                # Use white color for thin 1px line
                color = (221, 221, 221)  # White in BGR

                # Convert path positions to canvas coordinates and draw lines
                prev_point = None
                path_points = []

                for pos in path:
                    if pos is not None and len(pos) >= 2:
                        row_orig, col_orig = pos[0], pos[1]  # 0-indexed positions
                        point = self._electrode_to_canvas_point(
                            row_orig, col_orig,
                            rows_orig, cols_orig,
                            left, top, region_w, region_h,
                        )
                        if point is None:
                            continue

                        current_point = point
                        path_points.append(current_point)

                        # Draw thin white line from previous point to current point
                        if prev_point is not None:
                            cv2.line(trajectory_overlay, prev_point, current_point, color, 1)

                        prev_point = current_point

                # Find where the path actually ends (before padding with repeated positions)
                actual_end_idx = len(path) - 1
                for i in range(len(path) - 1, 0, -1):
                    if path[i] != path[i-1]:
                        actual_end_idx = i
                        break

                # Draw arrow at the actual end of the path
                if len(path_points) >= 2 and actual_end_idx < len(path_points):
                    # Get the point at actual end and the previous point
                    end_point = path_points[actual_end_idx]
                    if actual_end_idx > 0:
                        second_last = path_points[actual_end_idx - 1]
                    else:
                        second_last = path_points[0] if len(path_points) > 1 else path_points[0]

                    # Calculate direction vector
                    dx = end_point[0] - second_last[0]
                    dy = end_point[1] - second_last[1]

                    # Normalize and scale for arrow size
                    length = np.sqrt(dx*dx + dy*dy)
                    if length > 0:
                        # Arrow size (shorter)
                        arrow_length = 5
                        arrow_angle = 0.5  # radians

                        # Unit direction vector
                        ux = dx / length
                        uy = dy / length

                        # Arrow tip points
                        tip_x = end_point[0]
                        tip_y = end_point[1]

                        # Left arrow line
                        left_x = int(tip_x - arrow_length * (ux * np.cos(arrow_angle) + uy * np.sin(arrow_angle)))
                        left_y = int(tip_y - arrow_length * (uy * np.cos(arrow_angle) - ux * np.sin(arrow_angle)))

                        # Right arrow line
                        right_x = int(tip_x - arrow_length * (ux * np.cos(arrow_angle) - uy * np.sin(arrow_angle)))
                        right_y = int(tip_y - arrow_length * (uy * np.cos(arrow_angle) + ux * np.sin(arrow_angle)))

                        # Draw arrow lines (1px thickness)
                        cv2.line(trajectory_overlay, (tip_x, tip_y), (left_x, left_y), color, 1)
                        cv2.line(trajectory_overlay, (tip_x, tip_y), (right_x, right_y), color, 1)
                elif len(path_points) == 1:
                    # For single-point paths, draw a small dot to indicate the endpoint
                    point = path_points[0]
                    cv2.circle(trajectory_overlay, point, 3, color, -1)

                # Blend this trajectory overlay with 0.3 opacity
                canvas = cv2.addWeighted(canvas, 1.0, trajectory_overlay, 0.3, 0)


        # ───── overlay microscope position on the rotated grid ──────
        stage_pos = self.box.state["xy_stage"]["position"]
        rc = stage_to_electrode((stage_pos["X"], stage_pos["Y"]))

        if rc is not None:
            row_orig, col_orig = rc

            rows_orig, cols_orig = matrix.shape        # before rotation
            point = self._electrode_to_canvas_point(
                row_orig, col_orig,
                rows_orig, cols_orig,
                left, top, region_w, region_h,
            )

            # draw a circle of 5-electrode radius
            if point is not None:
                radius_px = int(15)
                cv2.circle(canvas, point, radius_px, (250, 250, 250), 1)

        # ───── draw a little circle at electrode (0,0) position ──────
        row_orig = 0
        col_orig = 0

        rows_orig, cols_orig = matrix.shape
        point = self._electrode_to_canvas_point(
            row_orig, col_orig,
            rows_orig, cols_orig,
            left, top, region_w, region_h,
        )

        if point is not None:
            px, py = point
            cv2.circle(canvas, (px, py), 5, (255, 255, 255), 1)
            cv2.putText(canvas, "0,0", (px + 8, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # ───── Draw ALL breakpoint indicators as dots ──────
        with self.lock:
            all_breakpoint_positions = self.breakpoint_positions.copy()

        if all_breakpoint_positions:
            rows_orig, cols_orig = matrix.shape

            for frame_num, positions in all_breakpoint_positions.items():
                for pos in positions:
                    if len(pos) >= 2:
                        row_orig, col_orig = pos[0], pos[1]
                        point = self._electrode_to_canvas_point(
                            row_orig, col_orig,
                            rows_orig, cols_orig,
                            left, top, region_w, region_h,
                        )
                        if point is None:
                            continue
                        px, py = point

                        # Draw dots - highlight current frame breakpoints more prominently
                        if frame_num == self.current_frame:
                            # Current frame breakpoint: Large with custom colors
                            cv2.circle(canvas, (px, py), 4, (136, 102, 78), -1)      # Large 4E6688 fill
                            cv2.circle(canvas, (px, py), 5, (178, 238, 227), 1)    
                        else:
                            # Future breakpoint: Smaller with custom colors
                            cv2.circle(canvas, (px, py), 3, (136, 102, 78), -1)      # Smaller 4E6688 fill

        # ───── overlay electrode matrix (droplets) on TOP of everything ──────
        mat_img = self._matrix_to_image(matrix, (region_w, region_h))

        x0, y0 = left, top
        region = canvas[y0:y0+region_h, x0:x0+region_w]
        # Draw droplets on top without blending (solid overlay)
        mask = mat_img > 0  # Where there are active electrodes/droplets
        region[mask] = mat_img[mask]

        # ───── add row and column labels centered in each axis ──────
        rotation = self.matrix_rotation_degrees
        horizontal_label = "Rows" if rotation in (90, 270) else "Columns"
        vertical_label = "Columns" if rotation in (90, 270) else "Rows"

        # Vertical axis label on the right, centered as rotated text.
        x_cols = left + region_w + 20
        y_center = top + region_h // 2
        text_img = np.zeros((50, 150, 3), np.uint8)
        cv2.putText(text_img, vertical_label, (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        # Rotate 90 degrees clockwise for vertical reading
        rotated_text = cv2.rotate(text_img, cv2.ROTATE_90_CLOCKWISE)
        # Paste onto canvas centered
        text_h, text_w = rotated_text.shape[:2]
        x_paste = x_cols - text_w // 2
        y_paste = y_center - text_h // 2
        if y_paste >= 0 and y_paste + text_h <= canvas.shape[0] and x_paste >= 0 and x_paste + text_w <= canvas.shape[1]:
            canvas[y_paste:y_paste + text_h, x_paste:x_paste + text_w] = rotated_text

        # Horizontal axis label on the top, centered.
        x_rows = left + region_w // 2 - 15
        y_rows = top - 5
        cv2.putText(canvas, horizontal_label, (x_rows, y_rows), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return canvas

    def _handle_mouse_event(self, event, x, y, flags, param):
        """Handle mouse events and forward electrode clicks to callback."""
        if self.mouse_callback is not None:
            try:
                self.mouse_callback(event, x, y, flags, param)
            except Exception:
                pass

        if event != cv2.EVENT_LBUTTONDOWN:
            return

        clicked_electrode = self._display_to_electrode(x, y)
        if clicked_electrode is None:
            return

        with self.lock:
            callback = self.electrode_click_callback

        if callback is not None:
            try:
                callback(clicked_electrode)
            except Exception:
                pass

    def _display_to_electrode(self, x, y):
        """Convert displayed pixel coordinates into electrode (row, col)."""
        with self.lock:
            canvas_shape = self.last_canvas_shape
            display_shape = self.last_display_shape
            matrix_shape = self.last_matrix_shape
            matrix_rotation_degrees = self.matrix_rotation_degrees

        if canvas_shape is None or display_shape is None or matrix_shape is None:
            return None

        canvas_h, canvas_w = canvas_shape
        display_h, display_w = display_shape
        rows_orig, cols_orig = matrix_shape

        if display_h <= 0 or display_w <= 0 or rows_orig <= 0 or cols_orig <= 0:
            return None

        scale_x = canvas_w / display_w
        scale_y = canvas_h / display_h
        canvas_x = x * scale_x
        canvas_y = y * scale_y

        top, right, bottom, left = self.margins
        region_w = canvas_w - left - right
        region_h = canvas_h - top - bottom

        if canvas_x < left or canvas_x >= left + region_w or canvas_y < top or canvas_y >= top + region_h:
            return None

        local_x = canvas_x - left
        local_y = canvas_y - top

        rows_rot, cols_rot = self._rotated_matrix_shape(
            rows_orig, cols_orig, matrix_rotation_degrees
        )
        cell_w = region_w / cols_rot
        cell_h = region_h / rows_rot

        c_rot = int(local_x / cell_w)
        r_rot = int(local_y / cell_h)

        c_rot = max(0, min(cols_rot - 1, c_rot))
        r_rot = max(0, min(rows_rot - 1, r_rot))

        return self._rotated_cell_to_electrode(
            r_rot, c_rot, rows_orig, cols_orig, matrix_rotation_degrees
        )

    # ───────────────────────────── image utilities ───────────────────────────
    @staticmethod
    def _normalize_matrix_rotation_degrees(degrees):
        try:
            normalized = int(round(float(degrees))) % 360
        except Exception as exc:
            raise ValueError("matrix_rotation_degrees must be one of 0, 90, 180, or 270") from exc

        if normalized not in (0, 90, 180, 270):
            raise ValueError("matrix_rotation_degrees must be one of 0, 90, 180, or 270")
        return normalized

    @staticmethod
    def _rotated_matrix_shape(rows_orig, cols_orig, rotation_degrees):
        if rotation_degrees in (90, 270):
            return cols_orig, rows_orig
        return rows_orig, cols_orig

    @staticmethod
    def _electrode_to_rotated_cell(row_orig, col_orig, rows_orig, cols_orig, rotation_degrees):
        if rotation_degrees == 0:
            return row_orig, col_orig
        if rotation_degrees == 90:
            return col_orig, rows_orig - 1 - row_orig
        if rotation_degrees == 180:
            return rows_orig - 1 - row_orig, cols_orig - 1 - col_orig
        return cols_orig - 1 - col_orig, row_orig

    @staticmethod
    def _rotated_cell_to_electrode(r_rot, c_rot, rows_orig, cols_orig, rotation_degrees):
        if rotation_degrees == 0:
            return (r_rot, c_rot)
        if rotation_degrees == 90:
            return (rows_orig - 1 - c_rot, r_rot)
        if rotation_degrees == 180:
            return (rows_orig - 1 - r_rot, cols_orig - 1 - c_rot)
        return (c_rot, cols_orig - 1 - r_rot)

    def _electrode_to_canvas_point(self, row_orig, col_orig, rows_orig, cols_orig,
                                   left, top, region_w, region_h):
        if not (0 <= row_orig < rows_orig and 0 <= col_orig < cols_orig):
            return None

        rotation = self.matrix_rotation_degrees
        rows_rot, cols_rot = self._rotated_matrix_shape(rows_orig, cols_orig, rotation)
        cell_w = region_w / cols_rot
        cell_h = region_h / rows_rot
        r_rot, c_rot = self._electrode_to_rotated_cell(
            row_orig, col_orig, rows_orig, cols_orig, rotation
        )
        px = left + int((c_rot + 0.5) * cell_w)
        py = top + int((r_rot + 0.5) * cell_h)
        return (px, py)

    @staticmethod
    def _matrix_rotation_k(rotation_degrees):
        return -(rotation_degrees // 90)

    @staticmethod
    def _rotate_image(image, angle_deg):
        (h, w) = image.shape[:2]
        center = (w/2, h/2)
        M = cv2.getRotationMatrix2D(center, -angle_deg, 1.0)  # negative = CW
        cos, sin = abs(M[0,0]), abs(M[0,1])
        new_w = int(h*sin + w*cos)
        new_h = int(h*cos + w*sin)
        M[0,2] += (new_w/2) - center[0]
        M[1,2] += (new_h/2) - center[1]
        return cv2.warpAffine(image, M, (new_w, new_h),
                              flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=(0,0,0))

    def _matrix_to_image(self, matrix, size):
        rotated = np.rot90(
            matrix,
            k=self._matrix_rotation_k(self.matrix_rotation_degrees)
        )
        h, w = rotated.shape
        img = np.zeros((h, w, 3), np.uint8)
        img[rotated == 1]  = [187,192,113]        # 71C0BB (droplet electrodes)
        img[rotated == 2]  = [  0,255,0]          # green
        img[rotated == 3]  = [128,0,128]          # purple (vital areas)
        img[rotated == 4]  = [255,128,0]          # orange (reserved spaces)
        img[rotated == -1] = [86,45,51]           # 332D56 (forbidden)
        return cv2.resize(img, size,
                          interpolation=cv2.INTER_NEAREST)

    # ───────────────────────────── window helper ─────────────────────────────
    def _bring_to_front(self):

        # Bring window to front OS gracefully
        try:
            bring_window_to_front(self.window_name)
        except Exception:
            pass

    # ───────────────────────────── teardown ─────────────────────────────────
    def stop(self):
        self.flag_exit.set()
        current_thread = threading.current_thread()
        if self.thread and self.thread is not current_thread:
            self.thread.join(timeout=1.0)

        try:
            cv2.destroyWindow(self.window_name)
        except Exception:
            pass
