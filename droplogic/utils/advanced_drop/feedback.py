"""
Integrated Feedback System for Droplet Position Validation

Provides automated computer vision feedback that handles stage movement,
frame capture, and detection to check if droplets are where they should be.
"""

import numpy as np
import time
from typing import List, Tuple, Dict, Optional, Union
from ..logging_config import setup_droplogic_logger
from ..drop_vision import DropletDetector
from .common import Droplet, DropletPlan, calculate_droplet_center
from ..hardware_utils import electrode_to_stage
import cv2

logger = setup_droplogic_logger('droplogic.advanced_drop.feedback')


class DropletPositionValidator:
    """
    Automated droplet position validation system.

    This class handles the complete feedback loop: moving the stage to electrode
    positions, capturing frames, running detection, and reporting results.

    It automatically detects hardware from DropSystems (BOXMini, Simulator).
    """
    BRIGHTFIELD_STANDARD_CHANNEL = "Brightfield"
    BRIGHTFIELD_STANDARD_AUTO_EXPOSURE = False
    BRIGHTFIELD_STANDARD_EXPOSURE_US = 60000
    BRIGHTFIELD_STANDARD_GAIN = 12
    BRIGHTFIELD_STANDARD_COAXIAL = 4
    BRIGHTFIELD_STANDARD_RING = 0
    BRIGHTFIELD_STANDARD_SETTLE_SECONDS = 0.2
    BRIGHTFIELD_STANDARD_WARMUP_TIMEOUT_SECONDS = 3.0
    BRIGHTFIELD_STANDARD_WARMUP_FRAMES = 3

    def __init__(self,
                 system_context,
                 advanced_drop=None,
                 detector: Optional[DropletDetector] = None,
                 confidence_threshold: float = 0.5,
                 stage_settle_time: float = 0.5,
                 electrode_to_stage_map: Optional[Dict[Tuple[int, int], Tuple[float, float, float]]] = None):
        """
        Initialize the position validator.

        Args:
            system_context: DropSystem instance (BOXMini, Simulator) for automatic hardware detection
            detector: Pre-configured DropletDetector instance
            confidence_threshold: Minimum confidence for valid detections
            stage_settle_time: Time to wait after stage movement before capture
            electrode_to_stage_map: Mapping from (row, col) to (X, Y, Z) stage coordinates
        """
        # Validator must be bound to an DropSystem with an advanced_drop parent
        if system_context is None or not hasattr(system_context, 'advanced_drop') or system_context.advanced_drop is None:
            raise ValueError("DropletPositionValidator must be constructed with an system_context that has an 'advanced_drop' attribute")

        self.detector = detector or DropletDetector()
        self.confidence_threshold = confidence_threshold
        self.stage_settle_time = stage_settle_time
        self.electrode_to_stage_map = electrode_to_stage_map or {}

        # Hardware interfaces (auto-detected from DropSystem)
        self.stage = None  # XYZ stage interface
        self.camera = None  # Camera interface
        self.streamer = None  # StreamerVisualizer for frame capture
        self.system_context = system_context

        # Set up logger using DropSystem logger if available
        self.system_context = system_context
        self.advanced_drop = advanced_drop
        self.logger = system_context.logger if hasattr(system_context, 'logger') and system_context.logger else setup_droplogic_logger('droplogic.advanced_drop.feedback')

        # Auto-detect hardware and warn if components missing
        self._auto_detect_hardware(system_context)

    def _auto_detect_hardware(self, system_context):
        """Automatically detect and configure hardware from DropSystem."""
        self.logger.debug(f"Auto-detecting hardware from {system_context.name}")

        # Detect stage
        if hasattr(system_context, 'xy_stage') and system_context.xy_stage:
            self.stage = system_context.xy_stage
            self.logger.debug("XY stage detected and configured")
        else:
            self.logger.warning("No XY stage detected in DropSystem")

        # Detect camera (prefer microscope camera over regular camera)
        if hasattr(system_context, 'microscope') and system_context.microscope:
            self.camera = system_context.microscope
            self.logger.debug("Microscope camera detected and configured")
        elif hasattr(system_context, 'camera') and system_context.camera:
            self.camera = system_context.camera
            self.logger.debug("Camera detected and configured")
        else:
            self.logger.warning("No camera or microscope detected in DropSystem")

        # Detect streamer visualizer
        if hasattr(system_context, 'visualizers') and hasattr(system_context.visualizers, 'streamer') and system_context.visualizers.streamer:
            self.streamer = system_context.visualizers.streamer
            self.logger.debug("Streamer visualizer detected and configured")
        else:
            self.logger.warning("No streamer visualizer detected in DropSystem")

        if self.stage and self.camera:
            self.logger.info("Hardware auto-detection complete: stage and camera ready")
        else:
            self.logger.warning("Hardware auto-detection incomplete - some components missing")

    def set_hardware(self, stage=None, camera=None, streamer=None):
        """Manually set hardware interfaces (overrides auto-detection)."""
        if stage:
            self.stage = stage
        if camera:
            self.camera = camera
        if streamer:
            self.streamer = streamer
        self.logger.debug("Hardware interfaces manually set")

    def validate_sipp_frame(self,
                            frame_idx: int = 0,
                            droplet_ids: Optional[List[int]] = None,
                            move_stage: bool = True,
                            save_frames_path: Optional[str] = None) -> Tuple[Dict[int, bool], Dict[int, Optional[str]]]:
        """
        """
        # Always use the bound DropSystem's advanced_drop plan and droplets
        plan = self.advanced_drop.plan if self.advanced_drop else getattr(self.system_context.advanced_drop, 'plan', None)
        self.droplets = getattr(self.system_context.advanced_drop, 'droplets', None)
        if plan is None:
            raise ValueError("DropSystem provided but no advanced_drop.plan found on it")
        if self.stage is None or self.camera is None or self.streamer is None:
            raise ValueError("Hardware auto-detection failed. Check that DropSystem has xy_stage, camera/microscope, and streamer visualizer.")

        # Determine which droplets to check. If we have an DropSystem use its droplets list.
        if droplet_ids is None:
            # Check all droplets that have trajectories up to this frame
            droplet_ids = [did for did, traj in plan.droplet_trajectories.items() if len(traj) > frame_idx]

        results = {}
        frame_files = {}

        original_settings = self._snapshot_brightfield_standard_setup()
        try:
            self._ensure_brightfield_standard_setup()

            for droplet_id in droplet_ids:
                trajectory = plan.droplet_trajectories.get(droplet_id)
                if trajectory is None or len(trajectory) <= frame_idx:
                    self.logger.warning(f"No trajectory for droplet {droplet_id} at frame {frame_idx}")
                    results[droplet_id] = False
                    frame_files[droplet_id] = None
                    continue

                # Get expected position for this frame
                expected_position = trajectory[frame_idx]

                # Generate frame filename if saving is requested
                frame_filename = None
                if save_frames_path:
                    import os
                    os.makedirs(save_frames_path, exist_ok=True)
                    frame_filename = os.path.join(save_frames_path, f"validation_droplet_{droplet_id}_frame_{frame_idx}.jpg")

                # Check if droplet is at expected position - move to center of droplet
                found, saved_frame = self._check_droplet_at_position(
                    droplet_id,
                    expected_position,
                    move_stage,
                    frame_filename,
                )
                results[droplet_id] = found
                frame_files[droplet_id] = saved_frame

                self.logger.info(
                    f"Droplet {droplet_id} at frame {frame_idx}, position {expected_position}: "
                    f"{'FOUND' if found else 'NOT FOUND'}"
                )
        finally:
            self._restore_brightfield_standard_setup(original_settings)

        return results, frame_files

    # The validator is intentionally bound to the parent advanced_drop plan; external plan-setting
    # methods have been removed to avoid accidental validation of unrelated plans.

    def _resolve_brightfield_standard_settings(self) -> Dict[str, object]:
        """Return the brightfield verification settings, allowing system overrides."""
        return {
            "microscope_settings.current_channel": getattr(
                self.system_context,
                "verification_brightfield_channel",
                self.BRIGHTFIELD_STANDARD_CHANNEL,
            ),
            "microscope_settings.auto_exposure": getattr(
                self.system_context,
                "verification_brightfield_auto_exposure",
                self.BRIGHTFIELD_STANDARD_AUTO_EXPOSURE,
            ),
            "microscope_settings.exposure_time": getattr(
                self.system_context,
                "verification_brightfield_exposure_time",
                self.BRIGHTFIELD_STANDARD_EXPOSURE_US,
            ),
            "microscope_settings.gain": getattr(
                self.system_context,
                "verification_brightfield_gain",
                self.BRIGHTFIELD_STANDARD_GAIN,
            ),
            "light_settings.coaxial_intensity": getattr(
                self.system_context,
                "verification_brightfield_coaxial_intensity",
                self.BRIGHTFIELD_STANDARD_COAXIAL,
            ),
            "light_settings.ring_intensity": getattr(
                self.system_context,
                "verification_brightfield_ring_intensity",
                self.BRIGHTFIELD_STANDARD_RING,
            ),
        }

    def _snapshot_brightfield_standard_setup(self) -> Dict[str, object]:
        """Capture the current microscope/light settings before verification."""
        state = getattr(self.system_context, "state", {}) or {}
        microscope_settings = state.get("microscope_settings", {}) or {}
        light_settings = state.get("light_settings", {}) or {}
        return {
            "microscope_settings.current_channel": microscope_settings.get("current_channel"),
            "microscope_settings.auto_exposure": microscope_settings.get("auto_exposure"),
            "microscope_settings.exposure_time": microscope_settings.get("exposure_time"),
            "microscope_settings.gain": microscope_settings.get("gain"),
            "light_settings.coaxial_intensity": light_settings.get("coaxial_intensity"),
            "light_settings.ring_intensity": light_settings.get("ring_intensity"),
        }

    def _restore_brightfield_standard_setup(self, settings: Optional[Dict[str, object]]) -> None:
        """Restore microscope/light settings after verification completes."""
        if not settings:
            return

        update_state = getattr(self.system_context, "update_state", None)
        if update_state is None:
            return

        changed_keys = []
        ordered_keys = [
            "microscope_settings.current_channel",
            "microscope_settings.auto_exposure",
            "microscope_settings.exposure_time",
            "microscope_settings.gain",
            "light_settings.coaxial_intensity",
            "light_settings.ring_intensity",
        ]

        state = getattr(self.system_context, "state", {}) or {}
        try:
            for state_key in ordered_keys:
                desired_value = settings.get(state_key)
                if desired_value is None:
                    continue

                section, field = state_key.split(".", 1)
                current_value = (state.get(section, {}) or {}).get(field)
                if current_value == desired_value:
                    continue

                update_state(state_key, desired_value)
                changed_keys.append((state_key, current_value, desired_value))
                time.sleep(self.BRIGHTFIELD_STANDARD_SETTLE_SECONDS)
        except Exception as restore_error:
            self.logger.warning(f"Failed to restore verify_droplets capture settings: {restore_error}")
            return

        if changed_keys:
            self.logger.debug(
                "verify_droplets restored capture settings: %s",
                ", ".join(
                    f"{key}={old!r}->{new!r}" for key, old, new in changed_keys
                ),
            )

    def _ensure_brightfield_standard_setup(self):
        """
        Force the standard brightfield microscope/light setup before verification.

        This keeps droplet verification consistent even if previous steps left
        the microscope in fluorescence or with dark-light settings.
        """
        microscope = getattr(self.system_context, "microscope", None)
        update_state = getattr(self.system_context, "update_state", None)
        if microscope is None or update_state is None:
            return

        state = getattr(self.system_context, "state", {}) or {}
        microscope_settings = state.get("microscope_settings", {}) or {}
        light_settings = state.get("light_settings", {}) or {}

        desired_settings = self._resolve_brightfield_standard_settings()
        current_settings = {
            "microscope_settings.current_channel": microscope_settings.get("current_channel"),
            "microscope_settings.auto_exposure": microscope_settings.get("auto_exposure"),
            "microscope_settings.exposure_time": microscope_settings.get("exposure_time"),
            "microscope_settings.gain": microscope_settings.get("gain"),
            "light_settings.coaxial_intensity": light_settings.get("coaxial_intensity"),
            "light_settings.ring_intensity": light_settings.get("ring_intensity"),
        }

        changed_keys = []
        for state_key, desired_value in desired_settings.items():
            current_value = current_settings.get(state_key)
            if current_value != desired_value:
                update_state(state_key, desired_value)
                changed_keys.append((state_key, current_value, desired_value))

        if changed_keys:
            self.logger.warning(
                "verify_droplets forced standard brightfield setup: %s",
                ", ".join(
                    f"{key}={old!r}->{new!r}" for key, old, new in changed_keys
                ),
            )

        time.sleep(self.BRIGHTFIELD_STANDARD_SETTLE_SECONDS)
        self._warmup_brightfield_frames()

    def _warmup_brightfield_frames(self):
        """
        Wait for a few fresh brightfield frames after changing channel/light
        settings so validation does not consume a stale dark frame.
        """
        if self.streamer is None:
            return

        start_time = time.time()
        previous_frame = self.streamer.get_raw_frame()
        accepted_frames = 0

        while time.time() - start_time < self.BRIGHTFIELD_STANDARD_WARMUP_TIMEOUT_SECONDS:
            frame = self.streamer.get_raw_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            if (
                previous_frame is not None
                and frame.shape == previous_frame.shape
                and np.array_equal(frame, previous_frame)
            ):
                time.sleep(0.05)
                continue

            if frame.ndim == 3:
                non_black_pixels = np.sum(np.any(frame != 0, axis=-1))
            else:
                non_black_pixels = np.sum(frame != 0)

            previous_frame = frame.copy()
            if non_black_pixels < 100:
                accepted_frames = 0
                time.sleep(0.05)
                continue

            accepted_frames += 1
            if accepted_frames >= self.BRIGHTFIELD_STANDARD_WARMUP_FRAMES:
                return

            time.sleep(0.05)

        self.logger.warning(
            "verify_droplets brightfield warm-up timed out; continuing with the latest available frame"
        )

    def _check_droplet_at_position(self, droplet_id: int, electrode_pos: Tuple[int, int], move_stage: bool = True, save_frame_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Check if there's a droplet at a specific electrode position by moving to its center."""
        try:
            # Calculate the center of the droplet at this position
            # We need to get the droplet object to know its shape
            stage_coords = calculate_droplet_center(droplet_id, electrode_pos, self.advanced_drop.droplets, self.logger)
            # Move stage to droplet center position using update_state queuing system
            if move_stage:
                
                self.logger.info(f"Moving stage to droplet {droplet_id} center -> stage {stage_coords}")
                # Use the DropSystem's update_state method to trigger the stage movement immediately
                self.system_context.update_state("xy_stage.position", stage_coords)
                self._stage_was_moved = True  # Track that stage was moved

                # Wait briefly before checking motion to allow the hardware to receive the commands over USB and report "busy"
                time.sleep(0.5)

                # Wait for stage motion to complete instead of using fixed settle time
                timeout = 10.0  # 10 second timeout
                start_time = time.time()
                motion_complete = False
                while time.time() - start_time < timeout:
                    # Check if all axes (X, Y, Z) have completed their motion
                    motion_complete = all(self.system_context.xy_stage.is_motion_complete(axis) for axis in ['X', 'Y', 'Z'])
                    if motion_complete:
                        break
                    time.sleep(0.1)  # Check every 100ms

                if not motion_complete:
                    self.logger.warning(f"Stage motion timeout after {timeout}s for droplet {droplet_id}")
                else:
                    self.logger.debug(f"Stage motion completed for droplet {droplet_id}")
            else:
                self._stage_was_moved = False  # Track that stage was not moved

            # Wait for motion blur to settle before capturing frame
            self._wait_for_motion_blur_settlement()

            # Capture raw frame from streamer visualizer using the new thread-safe method
            frame = self.streamer.get_raw_frame()
            if frame is None:
                self.logger.error("Failed to capture frame from streamer")
                return False, None

            # Store current frame for center calculation
            self._current_frame = frame

            # Run detection on the raw frame
            result = self.detector.detect(frame, return_annotated=False)

            # Overlay detection boxes on the raw frame for saving
            if save_frame_path:
                annotated_frame = frame.copy()
                # Draw bounding boxes and labels
                for bbox, conf, class_name in zip(
                    result.bounding_boxes, result.confidences, result.class_names):

                    x1, y1, x2, y2 = map(int, bbox)

                    # Draw bounding box
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    # Prepare label text
                    label = f"{class_name}: {conf:.2f}"

                    # Get text size for background
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)

                    # Draw label background
                    cv2.rectangle(annotated_frame,
                                (x1, y1 - text_height - baseline - 5),
                                (x1 + text_width, y1),
                                (0, 255, 0), -1)

                    # Draw label text
                    cv2.putText(annotated_frame, label, (x1, y1 - 5),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                              (255, 255, 255), 2)

                # Add detection count info
                if result.bounding_boxes:
                    count_text = f"Droplets: {len(result.bounding_boxes)}"
                    cv2.putText(annotated_frame, count_text, (10, 80),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                              (255, 255, 255), 2)

            # Check for confident detections near image center (±100px)
            found = self._check_droplet_near_center(result, confidence_threshold=self.confidence_threshold)

            # Save frame with overlay if requested
            frame_filename = None
            if save_frame_path:
                try:
                    frame_filename = save_frame_path

                    # Use the annotated frame we created above, or save the raw frame
                    frame_to_save = annotated_frame if 'annotated_frame' in locals() else frame

                    # Resize frame to maximum 1280 pixels width while maintaining aspect ratio
                    height, width = frame_to_save.shape[:2]
                    if width > 1280:
                        aspect_ratio = height / width
                        new_width = 1280
                        new_height = int(new_width * aspect_ratio)
                        frame_to_save = cv2.resize(frame_to_save, (new_width, new_height), interpolation=cv2.INTER_AREA)

                    # Save directly - the streamer visualizer handles color format correctly
                    cv2.imwrite(frame_filename, frame_to_save)
                    self.logger.debug(f"Saved validation frame to {frame_filename} (resized to max 1280px width)")

                except Exception as e:
                    self.logger.warning(f"Failed to save validation frame: {e}")

            return found, frame_filename

        except Exception as e:
            self.logger.error(f"Error checking droplet {droplet_id} at position {electrode_pos}: {e}")
            return False, None

    def _wait_for_motion_blur_settlement(self):
        """Wait for motion blur to settle before capturing frames."""
        # Only wait if stage was moved
        if not hasattr(self, '_stage_was_moved') or not self._stage_was_moved:
            return

        self.logger.debug("Waiting for motion blur to settle...")

        # Wait up to 5 seconds for motion blur to settle
        # Check consecutive frames to detect when motion blur has diminished
        max_wait_time = 5.0  # Maximum 5 seconds
        check_interval = 0.2  # Check every 200ms
        start_time = time.time()

        prev_frame = None
        stable_count = 0
        required_stable_frames = 3  # Need 3 consecutive stable frames

        while time.time() - start_time < max_wait_time:
            current_frame = self.streamer.get_raw_frame()
            if current_frame is None:
                time.sleep(check_interval)
                continue

            if prev_frame is not None:
                # Simple motion detection: check if frames are similar
                # Convert to grayscale for comparison
                if len(current_frame.shape) == 3:
                    current_gray = cv2.cvtColor(current_frame, cv2.COLOR_RGB2GRAY)
                    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_RGB2GRAY)
                else:
                    current_gray = current_frame
                    prev_gray = prev_frame

                # Calculate frame difference
                frame_diff = cv2.absdiff(current_gray, prev_gray)
                mean_diff = np.mean(frame_diff)

                # If frames are very similar (low difference), consider motion settled
                motion_threshold = 5.0  # Adjust based on your camera/noise characteristics
                if mean_diff < motion_threshold:
                    stable_count += 1
                    if stable_count >= required_stable_frames:
                        self.logger.debug(f"Motion blur settled after {time.time() - start_time:.2f}s")
                        return
                else:
                    stable_count = 0  # Reset if motion detected

            prev_frame = current_frame.copy()
            time.sleep(check_interval)

        # If we get here, motion blur didn't settle within timeout
        self.logger.warning(f"Motion blur did not settle within {max_wait_time}s timeout")

    def _check_droplet_near_center(self, detection_result, confidence_threshold=0.5, center_tolerance_percent=10.0):
        """
        Check if there's a confident droplet detection near the image center.

        Args:
            detection_result: Detection result from droplet detector
            confidence_threshold: Minimum confidence for valid detections
            center_tolerance_percent: Maximum distance from center as percentage of image dimensions

        Returns:
            bool: True if a confident droplet is found near center, False otherwise
        """
        if not hasattr(detection_result, 'bounding_boxes') or not detection_result.bounding_boxes:
            return False

        # Get actual frame dimensions from the current frame if available
        # This is more accurate than hardcoding dimensions
        if hasattr(self, '_current_frame') and self._current_frame is not None:
            image_height, image_width = self._current_frame.shape[:2]
        else:
            # Fallback to common camera resolutions if frame not available
            image_height, image_width = 1024, 1280  # Common camera resolutions, adjust as needed

        center_x, center_y = image_width // 2, image_height // 2

        # Calculate tolerance in pixels based on percentage
        tolerance_x = (center_tolerance_percent / 100.0) * image_width
        tolerance_y = (center_tolerance_percent / 100.0) * image_height

        for bbox, conf in zip(detection_result.bounding_boxes, detection_result.confidences):
            if conf < confidence_threshold:
                continue

            # Calculate bounding box center
            x1, y1, x2, y2 = bbox
            bbox_center_x = (x1 + x2) / 2
            bbox_center_y = (y1 + y2) / 2

            # Check if bounding box center is within tolerance percentage of image center
            if (abs(bbox_center_x - center_x) <= tolerance_x and
                abs(bbox_center_y - center_y) <= tolerance_y):
                self.logger.debug(f"Found droplet at center: bbox_center=({bbox_center_x:.1f}, {bbox_center_y:.1f}), "
                                f"image_center=({center_x}, {center_y}), tolerance=({tolerance_x:.1f}, {tolerance_y:.1f}), confidence={conf:.2f}")
                return True

        return False

