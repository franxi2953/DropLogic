"""
Asynchronous Plan Executor for AdvancedDrop

Provides non-blocking execution of droplet plans with real-time position updates.
Supports dynamic plan modification during execution.
"""

import threading
import time
import logging
import json
import os
import pickle
from collections.abc import Iterable
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import platform

from ..logging_config import setup_droplogic_logger
from ..recording import SegmentedVideoWriter

# Set up logger for plan executor
logger = setup_droplogic_logger('droplogic.advanced_drop.executor')

# Import keyboard handling based on platform
if platform.system() == 'Windows':
    import msvcrt
else:
    # For non-Windows, we could use other methods, but for now just disable
    msvcrt = None


@dataclass
class ExecutionState:
    """Tracks the current execution state."""
    is_executing: bool = False
    current_frame: int = 0
    total_frames: int = 0
    frames_executed: int = 0
    execution_time: float = 0.0
    last_update: float = 0.0


class ExecutionTimeoutError(TimeoutError):
    """Raised when executor progress does not reach the expected breakpoint in time."""


class PlanExecutor:
    """
    Asynchronous plan executor that runs in a separate thread.

    Features:
    - Non-blocking execution
    - Real-time droplet position updates
    - Dynamic plan modification support
    - Thread-safe operations with locks
    - Automatic frame advancement
    """

    def __init__(self, system, advanced_drop):
        """
        Initialize the plan executor.

        Args:
            system: DropSystem instance
            advanced_drop: AdvancedDrop instance to update
        """
        self.system = system
        self.advanced_drop = advanced_drop

        # Threading components
        self.executor_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.execution_lock = threading.RLock()  # Reentrant lock for thread safety

        # Keyboard listener
        self.keyboard_thread: Optional[threading.Thread] = None
        self.keyboard_stop_event = threading.Event()
        self.enable_keyboard_pause = True  # Can be disabled if needed

        # Execution state
        self.state = ExecutionState()
        self.frame_delay = 1.0
        self.verify_positions = False
        self.enable_visualizers = False

        # Breakpoint system
        self.breakpoints = set()  # Set of frame numbers to pause at
        self.breakpoint_reached = threading.Event()  # Signals when breakpoint is hit

        # Plan references (protected by lock)
        self.current_plan = None
        self.validator = None
        self.visualizer = None
        self._owns_matrix_visualizer = False
        self._owns_streamer_visualizer = False
        self._executor_synced_matrix_recorder = None
        self._executor_synced_streamer_recorder = None

        # Manual stage-follow override from matrix visualizer clicks
        self.stage_focus_cycle_length = 5
        self.manual_stage_target: Optional[Tuple[int, int]] = None
        self.manual_stage_target_expires_at: Optional[int] = None
        self.manual_stage_command_id = 0
        self.stage_motion_lock = threading.Lock()
        self.last_stage_target_position = None
        
        # Save file path for pkl updates
        self.save_file_path = None
        self.save_file_paths = []

        # Breakpoint wait watchdog defaults
        self.breakpoint_wait_min_timeout = 300.0
        self.breakpoint_wait_per_frame_multiplier = 8.0
        self.breakpoint_wait_extra_seconds = 120.0
        self.breakpoint_wait_remote_save_penalty = 180.0
        self.breakpoint_timeout_report_filename = "executor_timeout_reports.log"

        logger.info("PlanExecutor initialized")

    def _get_streamer_visualizer(self):
        if hasattr(self.system, 'visualizers') and hasattr(self.system.visualizers, 'streamer'):
            return self.system.visualizers.streamer
        return None

    def _derive_executor_synced_movie_fps(self) -> float:
        delay = max(float(self.frame_delay or 0.0), 1e-6)
        return max(1.0 / delay, 0.1)

    def _sync_recording_fps_to_frame_delay(self):
        fps = self._derive_executor_synced_movie_fps()

        if self.visualizer is not None:
            try:
                self.visualizer.movie_fps = fps
            except Exception:
                pass

        streamer_visualizer = self._get_streamer_visualizer()
        if streamer_visualizer is not None:
            try:
                streamer_visualizer.movie_fps = fps
            except Exception:
                pass

        if self._executor_synced_matrix_recorder is not None:
            self._executor_synced_matrix_recorder.set_fps(fps)

        if self._executor_synced_streamer_recorder is not None:
            self._executor_synced_streamer_recorder.set_fps(fps)

    def _visualizer_requires_main_thread_window(self, visualizer) -> bool:
        if visualizer is None or not hasattr(visualizer, "requires_main_thread_window"):
            return False

        try:
            return bool(visualizer.requires_main_thread_window())
        except Exception:
            return False

    def _foreground_visualizer_should_stop(self) -> bool:
        thread_alive = self.executor_thread is not None and self.executor_thread.is_alive()
        execution_completed = (
            self.state.total_frames > 0
            and self.state.current_frame >= self.state.total_frames
            and not self.state.is_executing
        )
        return self.stop_event.is_set() or execution_completed or (not thread_alive and not self.state.is_executing)

    def start(self, plan=None, frame_delay=1.0, verify_positions=True, enable_visualizers=False, save_to_file=None,
              record_matrix=False, record_streamer=False, matrix_filename=None, streamer_filename=None):
        """
        Start asynchronous execution of a plan.

        Args:
            plan: DropletPlan to execute (uses current plan if None)
            frame_delay: Delay between frames in seconds
            verify_positions: Whether to verify positions
            enable_visualizers: Whether to enable matrix and streamer visualizers
            save_to_file: File path, or iterable of file paths, to save plan and droplets (pickle format)
            record_matrix: Whether to record matrix visualizer to video file
            record_streamer: Whether to record streamer visualizer to video file
            matrix_filename: Custom filename for matrix recording (auto-generated if None)
            streamer_filename: Custom filename for streamer recording (auto-generated if None)
        """
        deferred_foreground_visualizer = None
        with self.execution_lock:
            if self.state.is_executing or (self.executor_thread and self.executor_thread.is_alive()):
                logger.warning("Existing execution loop detected - stopping it before starting a new one")
                self.stop()
                time.sleep(0.2)  # Brief pause to ensure clean shutdown

            logger.info(f"Starting plan execution with frame_delay={frame_delay}, verify_positions={verify_positions}, save_to_file={save_to_file}, record_matrix={record_matrix}, record_streamer={record_streamer}")

            # Update execution parameters
            self.frame_delay = frame_delay
            self.verify_positions = verify_positions
            self.enable_visualizers = enable_visualizers

            # Set plan and related components
            if plan is not None:
                self.current_plan = plan
            elif self.advanced_drop.plan is not None:
                self.current_plan = self.advanced_drop.plan
            else:
                logger.error("No plan available for execution")
                return

            # Set validator and matrix visualizer. Recording can use the visualizer
            # snapshot path without opening an interactive window.
            self.validator = self.advanced_drop.validator if verify_positions else None
            self.visualizer = self.advanced_drop.visualizer if (enable_visualizers or record_matrix) else None
            self._owns_matrix_visualizer = False
            self._owns_streamer_visualizer = False
            self._stop_executor_synced_recorders()

            # Configure visualizer recording settings
            if self.visualizer:
                if matrix_filename:
                    self.visualizer.movie_filename = matrix_filename
                if record_matrix:
                    logger.info(
                        f"Matrix recording enabled via executor: {self.visualizer.movie_filename}"
                    )

            # Configure streamer recording if available
            streamer_visualizer = self._get_streamer_visualizer()
            if streamer_visualizer:
                if streamer_filename:
                    streamer_visualizer.movie_filename = streamer_filename
                if record_streamer:
                    logger.info(
                        f"Streamer recording enabled via executor: {streamer_visualizer.movie_filename}"
                    )

            self._sync_recording_fps_to_frame_delay()

            # Start visualizers if requested
            if enable_visualizers and self.visualizer:
                try:
                    if hasattr(self.visualizer, 'set_electrode_click_callback'):
                        self.visualizer.set_electrode_click_callback(self.set_manual_stage_target)
                    if hasattr(self.visualizer, 'start'):
                        if self._is_visualizer_running(self.visualizer):
                            logger.debug("Matrix visualizer already running; keeping external ownership")
                        elif self._visualizer_requires_main_thread_window(self.visualizer):
                            deferred_foreground_visualizer = ("matrix", self.visualizer)
                            self._owns_matrix_visualizer = True
                            logger.info("Matrix visualizer will run on the main thread for this OS")
                        else:
                            self.visualizer.start()
                            self._owns_matrix_visualizer = True
                            logger.info("Started matrix visualizer")
                except Exception as e:
                    logger.warning(f"Failed to start matrix visualizer: {e}")

            if enable_visualizers and streamer_visualizer and hasattr(streamer_visualizer, 'start'):
                try:
                    if self._is_visualizer_running(streamer_visualizer):
                        logger.debug("Streamer visualizer already running; keeping external ownership")
                    elif self._visualizer_requires_main_thread_window(streamer_visualizer):
                        if deferred_foreground_visualizer is None:
                            deferred_foreground_visualizer = ("streamer", streamer_visualizer)
                            self._owns_streamer_visualizer = True
                            logger.info("Streamer visualizer will run on the main thread for this OS")
                        else:
                            logger.warning(
                                "Skipping automatic streamer window start on this OS because a foreground visualizer is already active"
                            )
                    else:
                        streamer_visualizer.start()
                        self._owns_streamer_visualizer = True
                        logger.info("Started streamer visualizer")
                except Exception as e:
                    logger.warning(f"Failed to start streamer visualizer: {e}")

            self._start_executor_synced_recorders(
                record_matrix=record_matrix,
                matrix_visualizer=self.visualizer,
                record_streamer=record_streamer,
                streamer_visualizer=streamer_visualizer,
            )

            # Save plan and droplets to file if requested
            self.save_file_paths = self._normalize_save_paths(save_to_file)
            self.save_file_path = self.save_file_paths[0] if self.save_file_paths else None
            if self.save_file_paths:
                self._save_plan_snapshot(self.save_file_paths)
            else:
                self.save_file_path = None

            # Reset execution state
            self.state = ExecutionState(
                is_executing=True,
                total_frames=len(self.current_plan.frames) if self.current_plan else 0,
                last_update=time.time()
            )

            logger.info(f"Starting execution with plan: {len(self.current_plan.frames) if self.current_plan else 0} frames")

            # Start keyboard listener if enabled
            if self.enable_keyboard_pause and msvcrt:
                self._start_keyboard_listener()

            # Start execution thread
            self.stop_event.clear()
            self.executor_thread = threading.Thread(
                target=self._execution_loop,
                name="PlanExecutor",
                daemon=True
            )
            self.executor_thread.start()

            logger.info(f"Started asynchronous execution: {self.state.total_frames} frames")

        if deferred_foreground_visualizer is not None:
            label, visualizer = deferred_foreground_visualizer
            try:
                logger.info(f"Running {label} visualizer on the main thread")
                visualizer.start(stop_condition=self._foreground_visualizer_should_stop)
            except Exception as e:
                logger.warning(f"Failed to run {label} visualizer on the main thread: {e}")

    def stop(self):
        """Stop the current execution."""
        with self.execution_lock:
            thread_alive = self.executor_thread is not None and self.executor_thread.is_alive()
            if not self.state.is_executing and not thread_alive:
                self._stop_keyboard_listener()
                self._stop_recording_visualizers()
                return

            self.stop_event.set()
            self.state.is_executing = False

            if thread_alive:
                self.executor_thread.join(timeout=2.0)

            # Stop keyboard listener
            self._stop_keyboard_listener()

            self._stop_recording_visualizers()

            logger.info(f"Stopped execution at frame {self.state.current_frame}")

    def _start_executor_synced_recorders(self, record_matrix, matrix_visualizer, record_streamer, streamer_visualizer):
        shared_fps = self._derive_executor_synced_movie_fps()

        if record_matrix and matrix_visualizer is not None:
            recorder = SegmentedVideoWriter("MatrixExecutorRecorder")
            recorder.configure(
                matrix_visualizer.movie_filename,
                shared_fps,
                segment_duration_seconds=getattr(matrix_visualizer, "movie_segment_duration_seconds", None),
                segment_frame_limit=getattr(matrix_visualizer, "movie_segment_frame_limit", None),
            )
            recorder.start()
            self._executor_synced_matrix_recorder = recorder

        if record_streamer and streamer_visualizer is not None:
            recorder = SegmentedVideoWriter("StreamerExecutorRecorder")
            recorder.configure(
                streamer_visualizer.movie_filename,
                shared_fps,
                segment_duration_seconds=getattr(streamer_visualizer, "movie_segment_duration_seconds", None),
                segment_frame_limit=getattr(streamer_visualizer, "movie_segment_frame_limit", None),
            )
            recorder.start()
            self._executor_synced_streamer_recorder = recorder

    def _stop_executor_synced_recorders(self):
        if self._executor_synced_matrix_recorder is not None:
            try:
                self._executor_synced_matrix_recorder.stop()
            except Exception as e:
                logger.warning(f"Failed to stop executor-synced matrix recorder: {e}")
            self._executor_synced_matrix_recorder = None

        if self._executor_synced_streamer_recorder is not None:
            try:
                self._executor_synced_streamer_recorder.stop()
            except Exception as e:
                logger.warning(f"Failed to stop executor-synced streamer recorder: {e}")
            self._executor_synced_streamer_recorder = None

    def _stop_recording_visualizers(self):
        self._stop_executor_synced_recorders()

        if self.visualizer and self._owns_matrix_visualizer:
            try:
                if hasattr(self.visualizer, 'stop'):
                    self.visualizer.stop()
                    logger.info("Stopped matrix visualizer")
            except Exception as e:
                logger.warning(f"Failed to stop matrix visualizer: {e}")

        streamer_visualizer = self._get_streamer_visualizer()
        if (
            streamer_visualizer is not None
            and hasattr(streamer_visualizer, 'stop')
            and self._owns_streamer_visualizer
        ):
            try:
                streamer_visualizer.stop()
                logger.info("Stopped streamer visualizer")
            except Exception as e:
                logger.warning(f"Failed to stop streamer visualizer: {e}")

        self._owns_matrix_visualizer = False
        self._owns_streamer_visualizer = False

    def _is_visualizer_running(self, visualizer) -> bool:
        if visualizer is None:
            return False

        if hasattr(visualizer, "is_running"):
            try:
                return bool(visualizer.is_running())
            except Exception:
                pass

        for attr_name in ("capture_thread", "display_thread", "thread"):
            thread = getattr(visualizer, attr_name, None)
            if thread is not None and hasattr(thread, "is_alive") and thread.is_alive():
                return True
        return False

    def _normalize_save_paths(self, save_to_file):
        if not save_to_file:
            return []
        if isinstance(save_to_file, (str, bytes, os.PathLike)):
            return [os.fspath(save_to_file)]
        if isinstance(save_to_file, Iterable):
            paths = []
            for path in save_to_file:
                if path:
                    paths.append(os.fspath(path))
            return paths
        return [os.fspath(save_to_file)]

    def _build_save_payload(self):
        droplets_to_save = list(self.advanced_drop.droplets)
        # If droplets list is empty but plan has trajectories, reconstruct minimal Droplet objects.
        if not droplets_to_save and hasattr(self.current_plan, 'droplet_trajectories'):
            from .common import Droplet

            for d_id, traj in self.current_plan.droplet_trajectories.items():
                if traj:
                    origin = traj[0]
                    target = traj[-1]
                    droplet = Droplet(
                        id=d_id,
                        shape={(0, 0)},
                        origin_corner=origin,
                        target_corner=target,
                        priority=0,
                        vital_space=1,
                        electrode_count=1,
                    )
                    droplets_to_save.append(droplet)
        return {
            'plan': self.current_plan,
            'droplets': droplets_to_save,
        }

    def _save_plan_snapshot(self, paths):
        try:
            payload = self._build_save_payload()
        except Exception as e:
            logger.error(f"Failed to build plan save payload: {e}")
            return

        for path in paths:
            try:
                output_dir = os.path.dirname(os.path.abspath(path))
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                with open(path, 'wb') as f:
                    pickle.dump(payload, f)
                logger.info(f"Saved plan and droplets to {path}")
            except Exception as e:
                logger.error(f"Failed to save plan and droplets to {path}: {e}")

    def set_manual_stage_target(self, electrode_pos: Tuple[int, int]):
        """Override stage following with a user-selected electrode for one focus cycle."""
        with self.execution_lock:
            self.manual_stage_target = electrode_pos
            self.manual_stage_target_expires_at = self.state.current_frame + self.stage_focus_cycle_length
            self.manual_stage_command_id += 1
            command_id = self.manual_stage_command_id
            logger.info(
                f"Manual stage target set to {electrode_pos} until frame {self.manual_stage_target_expires_at}"
            )

        dispatcher = threading.Thread(
            target=self._dispatch_manual_stage_target,
            args=(command_id, electrode_pos),
            name=f"ManualStageTarget_{command_id}",
            daemon=True
        )
        dispatcher.start()

    def _dispatch_manual_stage_target(self, command_id: int, electrode_pos: Tuple[int, int]):
        """Move to a manual target as soon as the stage is free, without waiting for the next frame."""
        while not self.stop_event.is_set():
            with self.execution_lock:
                if command_id != self.manual_stage_command_id or self.manual_stage_target != electrode_pos:
                    return

            if self._is_stage_idle():
                break

            time.sleep(0.05)

        with self.execution_lock:
            if command_id != self.manual_stage_command_id or self.manual_stage_target != electrode_pos:
                return

            frame_idx = self.state.current_frame

        self._move_stage_to_target(frame_idx, "manual_immediate", electrode_pos)

    def _is_stage_idle(self) -> bool:
        """Return True when the XY stage is not currently moving."""
        if not hasattr(self.system, 'xy_stage') or self.system.xy_stage is None:
            return True

        try:
            return all(self.system.xy_stage.is_motion_complete(axis) for axis in ['X', 'Y', 'Z'])
        except Exception:
            return False

    def pause(self):
        """Pause the current execution."""
        with self.execution_lock:
            if self.state.is_executing:
                self.state.is_executing = False
                logger.info("Execution paused")

    def resume(self):
        """Resume paused execution."""
        with self.execution_lock:
            if not self.state.is_executing:
                # Reload plan from advanced_drop if available
                if self.advanced_drop.plan is not None:
                    self.current_plan = self.advanced_drop.plan
                    self.state.total_frames = len(self.current_plan.frames) if self.current_plan else 0
                    logger.info(f"Reloaded plan with {self.state.total_frames} frames")

                    # Update pkl file with new plan and droplets if save paths were set
                    if self.save_file_paths:
                        self._save_plan_snapshot(self.save_file_paths)

                if self.current_plan:
                    self.state.is_executing = True
                    # Clear breakpoint signal when resuming
                    self.breakpoint_reached.clear()
                    logger.info("Execution resumed")
                    
                    # If the executor thread died, restart it
                    if self.executor_thread is None or not self.executor_thread.is_alive():
                        logger.warning("Executor thread was dead, restarting it.")
                        self.stop_event.clear()
                        self.executor_thread = threading.Thread(
                            target=self._execution_loop,
                            name="PlanExecutor",
                            daemon=True
                        )
                        self.executor_thread.start()
                else:
                    logger.error("No plan available to resume execution")

    def status(self) -> Dict[str, Any]:
        """Get current execution status."""
        with self.execution_lock:
            return {
                'is_executing': self.state.is_executing,
                'current_frame': self.state.current_frame,
                'total_frames': self.state.total_frames,
                'frames_executed': self.state.frames_executed,
                'execution_time': self.state.execution_time,
                'progress': (self.state.frames_executed / self.state.total_frames * 100) if self.state.total_frames > 0 else 0,
                'last_update': self.state.last_update,
                'breakpoints': list(self.breakpoints),
                'breakpoint_reached': self.breakpoint_reached.is_set()
            }

    def _start_keyboard_listener(self):
        """Start the keyboard listener thread."""
        if self.keyboard_thread and self.keyboard_thread.is_alive():
            return

        self.keyboard_stop_event.clear()
        self.keyboard_thread = threading.Thread(
            target=self._keyboard_listener_loop,
            name="KeyboardListener",
            daemon=True
        )
        self.keyboard_thread.start()
        logger.info("Started keyboard listener (press SPACE to pause)")

    def _stop_keyboard_listener(self):
        """Stop the keyboard listener thread."""
        if self.keyboard_thread:
            self.keyboard_stop_event.set()
            if self.keyboard_thread.is_alive():
                self.keyboard_thread.join(timeout=1.0)
            self.keyboard_thread = None
            logger.info("Stopped keyboard listener")

    def _keyboard_listener_loop(self):
        """Keyboard listener loop running in separate thread."""
        try:
            while not self.keyboard_stop_event.is_set():
                if msvcrt and msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key == b' ':  # Space bar
                        with self.execution_lock:
                            if self.state.is_executing:
                                self.pause()
                                logger.info("Execution paused by user (SPACE key)")
                                logger.warning("\n*** EXECUTION PAUSED *** Press SPACE again to resume, or 'q' to quit")
                                
                                # Wait for resume or quit
                                while not self.keyboard_stop_event.is_set():
                                    if msvcrt.kbhit():
                                        key = msvcrt.getch()
                                        if key == b' ':  # Space to resume
                                            self.resume()
                                            logger.info("Execution resumed by user (SPACE key)")
                                            logger.warning("*** EXECUTION RESUMED ***")
                                            break
                                        elif key == b'q':  # q to quit
                                            self.stop()
                                            logger.info("Execution stopped by user (q key)")
                                            print("*** EXECUTION STOPPED ***")
                                            return
                                    time.sleep(0.1)
                            else:
                                # If paused, space resumes
                                self.resume()
                                logger.info("Execution resumed by user (SPACE key)")
                                logger.warning("*** EXECUTION RESUMED ***")
                time.sleep(0.05)  # Poll every 50ms
        except Exception as e:
            logger.error(f"Keyboard listener error: {e}")

    def get_droplet_position(self, droplet_id: int) -> Optional[Tuple[int, int]]:
        """
        Get the last executed position of a droplet during execution.

        Args:
            droplet_id: ID of the droplet

        Returns:
            Last executed position as (row, col) tuple, or None if not found or not executed
        """
        with self.execution_lock:
            if not self.current_plan or not hasattr(self.current_plan, 'droplet_trajectories'):
                return None

            trajectories = self.current_plan.droplet_trajectories
            if droplet_id not in trajectories:
                return None

            trajectory = trajectories[droplet_id]
            # Return position at the last executed frame (current_frame is the next frame to execute)
            executed_frame = self.state.current_frame - 1

            if executed_frame >= 0 and executed_frame < len(trajectory):
                return trajectory[executed_frame]

            return None

    def add_breakpoint(self, frame_number: int):
        """Add a breakpoint at the specified frame number."""
        self.breakpoints.add(frame_number)
        logger.info(f"Added breakpoint at frame {frame_number}")

    def remove_breakpoint(self, frame_number: int):
        """Remove a breakpoint at the specified frame number."""
        self.breakpoints.discard(frame_number)
        logger.info(f"Removed breakpoint at frame {frame_number}")

    def clear_breakpoints(self):
        """Clear all breakpoints."""
        self.breakpoints.clear()
        logger.info("Cleared all breakpoints")

    def update_plan(self, new_plan):
        """Update the execution plan dynamically."""
        with self.execution_lock:
            if not self.current_plan:
                logger.warning("No current plan to update")
                return

            # Merge new frames with existing plan
            if hasattr(new_plan, 'frames') and new_plan.frames:
                self.current_plan.frames.extend(new_plan.frames)
                self.state.total_frames = len(self.current_plan.frames)

                # Update trajectories if available
                if hasattr(new_plan, 'droplet_trajectories'):
                    for droplet_id, trajectory in new_plan.droplet_trajectories.items():
                        if droplet_id in self.current_plan.droplet_trajectories:
                            self.current_plan.droplet_trajectories[droplet_id].extend(trajectory)
                        else:
                            self.current_plan.droplet_trajectories[droplet_id] = trajectory.copy()

                logger.info(f"Plan updated: +{len(new_plan.frames)} frames")

    def _resolve_target_frame(self) -> int:
        """Resolve the frame we expect to reach for the current breakpoint wait."""
        with self.execution_lock:
            pending_breakpoints = sorted(int(frame) for frame in self.breakpoints)
            if pending_breakpoints:
                return pending_breakpoints[-1]

            total_frames = len(self.current_plan.frames) if self.current_plan and self.current_plan.frames else 0
            return max(total_frames - 1, 0)

    def estimate_breakpoint_timeout(self, target_frame: int = None) -> float:
        """Estimate a conservative timeout for waiting on the current breakpoint."""
        if target_frame is None:
            target_frame = self._resolve_target_frame()

        status = self.status()
        current_frame = int(status.get('current_frame', 0))
        remaining_frames = max(0, target_frame - current_frame) + 1
        frame_delay = max(float(self.frame_delay or 0.0), 0.01)

        frame_budget = remaining_frames * max(1.0, frame_delay * self.breakpoint_wait_per_frame_multiplier)
        extra_seconds = float(self.breakpoint_wait_extra_seconds)

        current_drive = os.path.splitdrive(os.path.abspath(os.getcwd()))[0].upper()
        for path in self.save_file_paths or []:
            try:
                path_drive = os.path.splitdrive(os.path.abspath(os.fspath(path)))[0].upper()
            except Exception:
                path_drive = ""
            if path_drive not in ("", current_drive):
                extra_seconds += float(self.breakpoint_wait_remote_save_penalty)
                break

        return max(float(self.breakpoint_wait_min_timeout), frame_budget + extra_seconds)

    def get_diagnostics(self, label: str = None, target_frame: int = None,
                        timeout_seconds: float = None, elapsed_seconds: float = None) -> Dict[str, Any]:
        """Collect a diagnostic snapshot for stalled or unexpected executor states."""
        if target_frame is None:
            target_frame = self._resolve_target_frame()

        report = {
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'label': label,
            'target_frame': target_frame,
            'timeout_seconds': timeout_seconds,
            'elapsed_seconds': round(elapsed_seconds, 2) if elapsed_seconds is not None else None,
            'executor_status': self.status(),
            'executor_thread_alive': bool(self.executor_thread and self.executor_thread.is_alive()),
            'pending_breakpoints': sorted(int(frame) for frame in self.breakpoints),
            'save_file_paths': list(self.save_file_paths or []),
        }

        try:
            if hasattr(self.system, 'get_queue_status'):
                report['queue_status'] = self.system.get_queue_status()
        except Exception as e:
            report['queue_status_error'] = str(e)

        try:
            if hasattr(self.system, 'state'):
                report['xy_stage_state'] = self.system.state.get('xy_stage', {})
        except Exception as e:
            report['xy_stage_state_error'] = str(e)

        return report

    def _get_diagnostics_dir(self) -> str:
        """Resolve where timeout diagnostics should be written."""
        if self.save_file_paths:
            first_path = os.fspath(self.save_file_paths[0])
            parent = os.path.dirname(os.path.abspath(first_path))
            if parent:
                return parent
        return os.getcwd()

    def _write_timeout_report(self, report: Dict[str, Any]) -> str:
        """Append a timeout diagnostic report to disk."""
        diagnostics_dir = self._get_diagnostics_dir()
        os.makedirs(diagnostics_dir, exist_ok=True)
        report_path = os.path.join(diagnostics_dir, self.breakpoint_timeout_report_filename)
        with open(report_path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(report, sort_keys=True, default=str) + '\n')
        return report_path

    def execute_until_breakpoint(self, timeout_seconds: float = None, resume_if_paused: bool = True) -> bool:
        """
        Blocks the calling thread until the executor completes its current plan,
        pauses at a breakpoint, or stops.
        
        Args:
            timeout_seconds: Optional timeout in seconds to wait before returning.
                If None, blocks indefinitely until the executor resolves.
            resume_if_paused: If True, automatically resumes execution if it was paused but 
                has more frames remaining.
                
        Returns:
            bool: True if the executor is no longer executing (finished/paused),
                  False if the timeout was reached while still executing.
        """
        # Automatically resume if execution stopped from a previous breakpoint 
        # but the plan has been expanded with new frames (e.g. after a move() command)
        if resume_if_paused:
            with self.execution_lock:
                if not self.state.is_executing and self.current_plan and self.state.current_frame < self.state.total_frames:
                    needs_resume = True
                else:
                    needs_resume = False
            
            if needs_resume:
                self.resume()

        start_wait = time.time()
        
        # Loop while we are executing and have not hit the breakpoint event 
        # (covering all definitions of "is executing" before reaching the pausing state)
        while self.state.is_executing and not self.breakpoint_reached.is_set():
            if timeout_seconds and (time.time() - start_wait) > timeout_seconds:
                return False
            time.sleep(0.05)
            
        return True

    def execute_until_breakpoint_or_raise(self, timeout_seconds: float = None,
                                          resume_if_paused: bool = True,
                                          label: str = None) -> bool:
        """
        Wait for breakpoint/plan completion and raise with diagnostics on timeout or early stop.
        """
        target_frame = self._resolve_target_frame()
        if timeout_seconds is None:
            timeout_seconds = self.estimate_breakpoint_timeout(target_frame=target_frame)

        start_wait = time.time()
        completed = self.execute_until_breakpoint(
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
        )
        elapsed_seconds = time.time() - start_wait
        status = self.status()
        reached_target = bool(status.get('breakpoint_reached')) or int(status.get('current_frame', -1)) >= target_frame

        if completed and not status.get('is_executing', False) and reached_target:
            return True

        report = self.get_diagnostics(
            label=label,
            target_frame=target_frame,
            timeout_seconds=timeout_seconds,
            elapsed_seconds=elapsed_seconds,
        )
        report_path = self._write_timeout_report(report)
        descriptor = f" during '{label}'" if label else ""
        logger.error(f"Executor wait timed out or stalled{descriptor}. Diagnostics written to {report_path}: {report}")
        raise ExecutionTimeoutError(
            f"Executor stalled{descriptor} after {elapsed_seconds:.1f}s. "
            f"Diagnostics saved to {report_path}."
        )

    def _execution_loop(self):
        """Main execution loop running in separate thread."""
        start_time = time.time()
        
        try:
            while not self.stop_event.is_set():
                
                with self.execution_lock:
                    if not self.state.is_executing:
                        paused = True
                    else:
                        paused = False
                        # logger.info("Execution loop step started")
                        
                        # Check if we've reached the end
                        if self.state.current_frame >= self.state.total_frames:
                            logger.info("Execution completed - reached end of plan")
                            self.state.is_executing = False
                            break

                        # Execute current frame
                        # _frame_start_time = time.time()
                        self._execute_frame(self.state.current_frame)
                        # print(f"Frame {self.state.current_frame} executed in {(time.time() - _frame_start_time) * 1000:.2f} ms")
                        
                        # Check for breakpoints after executing frame (so droplet is at final position)
                        if self.state.current_frame in self.breakpoints:
                            logger.info(f"Breakpoint reached at frame {self.state.current_frame}")
                            self.breakpoint_reached.set()
                            self.state.is_executing = False
                            # Remove the breakpoint after it's hit (one-time breakpoint)
                            self.breakpoints.discard(self.state.current_frame)
                            # Don't increment frame counter - stay at breakpoint frame for visualization
                            self.state.last_update = time.time()
                            paused = True
                        else:
                            # Update state
                            self.state.frames_executed = self.state.current_frame + 1
                            self.state.current_frame += 1
                            self.state.last_update = time.time()
                
                if paused:
                    time.sleep(0.1)
                    continue

                # Wait before next frame (but allow interruption)
                if self.frame_delay > 0:
                    # Sleep in small increments to allow for interruption
                    remaining_delay = self.frame_delay
                    while remaining_delay > 0 and not self.stop_event.is_set():
                        sleep_time = min(0.1, remaining_delay)  # Sleep in 100ms chunks
                        time.sleep(sleep_time)
                        remaining_delay -= sleep_time

        except Exception as e:
            logger.error(f"Execution error: {e}")
            self.state.is_executing = False
        finally:
            self.state.execution_time = time.time() - start_time
            
            logger.info(f"Execution loop ended after {self.state.execution_time:.2f}s")

    def _execute_frame(self, frame_idx: int):
        """Execute a single frame."""
        
        try:
            # _t0 = time.time()
            
            # Determine active droplets for this frame
            active_droplets = []
            if (hasattr(self.current_plan, 'active_droplets_per_frame') and
                self.current_plan.active_droplets_per_frame and
                any(ids for ids in self.current_plan.active_droplets_per_frame)):
                # Use active_droplets_per_frame if meaningfully populated
                if frame_idx < len(self.current_plan.active_droplets_per_frame):
                    active_ids = self.current_plan.active_droplets_per_frame[frame_idx]
                    active_droplets = [d for d in self.advanced_drop.droplets if d.id in active_ids]
                else:
                    # For frames beyond the list, use all droplets with trajectories
                    active_droplets = [d for d in self.advanced_drop.droplets
                                     if d.id in self.current_plan.droplet_trajectories]
            else:
                # Fallback: use all droplets that have trajectories
                active_droplets = [d for d in self.advanced_drop.droplets
                                 if d.id in self.current_plan.droplet_trajectories]

            # _t1 = time.time()
            # print(f"  [Time] Active droplets init: {(_t1 - _t0)*1000:.2f} ms")

            # Process events for this frame
            self._process_events(frame_idx)
            
            # _t2 = time.time()
            # print(f"  [Time] Process events: {(_t2 - _t1)*1000:.2f} ms")

            # Get frame matrix
            if frame_idx >= len(self.current_plan.frames):
                logger.warning(f"Frame {frame_idx} not available")
                return

            frame_matrix = self.current_plan.frames[frame_idx]

            # Apply frame to hardware
            self.system.update_state("electrode_matrix.matrix", frame_matrix)
            
            # _t3 = time.time()
            # print(f"  [Time] Matrix/Hardware update: {(_t3 - _t2)*1000:.2f} ms")

            # Handle stage movements for active droplets
            self._handle_stage_movements(frame_idx, active_droplets)
            
            # _t4 = time.time()
            # print(f"  [Time] Stage movements: {(_t4 - _t3)*1000:.2f} ms")

            # Update droplet positions for active droplets only
            self._update_droplet_positions(frame_idx, active_droplets)

            # Handle visualization
            if self.visualizer and self.enable_visualizers:
                self._handle_visualization()

            self._record_executor_synced_visualizer_frames()
                   
            # _t5 = time.time()
            # print(f"  [Time] Vis & Pos updates: {(_t5 - _t4)*1000:.2f} ms")

            # Handle verification
            if self.validator and self.verify_positions:
                self._handle_verification(frame_idx)
                
            # _t6 = time.time()
            # print(f"  [Time] Verification: {(_t6 - _t5)*1000:.2f} ms")

            # Format active droplet IDs for logging
            active_ids = [d.id for d in active_droplets]
            if len(active_ids) <= 10:
                ids_str = str(active_ids)
            else:
                ids_str = f"{active_ids[:5]}...{active_ids[-5:]}"
            logger.debug(f"Executed frame {frame_idx} with {len(active_droplets)} active droplets: {ids_str}")

        except Exception as e:
            logger.error(f"Frame execution error at {frame_idx}: {e}")

    def _update_droplet_positions(self, frame_idx: int, active_droplets=None):
        """Update droplet positions based on current frame."""
        # NOTE: Executor no longer modifies droplet objects directly.
        # Positions are tracked via current_frame index and queried from plan trajectories when needed.
        # This prevents interference with planning operations and maintains clean separation of concerns.
        logger.debug(f"Frame {frame_idx} executed - positions tracked via plan trajectories")

    def _handle_visualization(self):
        """Handle visualizer setup and updates."""
        if self.visualizer and self.current_plan and hasattr(self.current_plan, 'droplet_trajectories'):
            # Set up paths if available
            if hasattr(self.visualizer, 'set_paths'):
                paths = list(self.current_plan.droplet_trajectories.values())
                self.visualizer.set_paths(paths)
                logger.debug(f"Set visualizer paths: {len(paths)} trajectories")

            # Set all breakpoint positions at the beginning (like paths)
            if hasattr(self.visualizer, 'set_breakpoint_positions') and not hasattr(self.visualizer, '_breakpoints_initialized'):
                all_breakpoint_positions = {}
                for frame_num in self.breakpoints:
                    frame_positions = []
                    for droplet_id, trajectory in self.current_plan.droplet_trajectories.items():
                        if frame_num < len(trajectory):
                            pos = trajectory[frame_num]
                            frame_positions.append(pos)
                    all_breakpoint_positions[frame_num] = frame_positions

                self.visualizer.set_breakpoint_positions(all_breakpoint_positions)
                self.visualizer._breakpoints_initialized = True
                logger.debug(f"Set all breakpoint positions: {len(all_breakpoint_positions)} frames with breakpoints")

            # Update current frame for breakpoint visualization
            if hasattr(self.visualizer, 'set_current_frame'):
                self.visualizer.set_current_frame(self.state.current_frame)

            # Visualizer lifecycle is handled in start()/stop(); this method only updates state.

    def _record_executor_synced_visualizer_frames(self):
        matrix_recorder = self._executor_synced_matrix_recorder
        if matrix_recorder is not None and self.visualizer is not None:
            try:
                frame = self.visualizer.get_snapshot_frame() if hasattr(self.visualizer, 'get_snapshot_frame') else None
                if frame is not None:
                    matrix_recorder.write_frame(frame)
            except Exception as e:
                logger.warning(f"Failed to write executor-synced matrix frame: {e}")

        streamer_recorder = self._executor_synced_streamer_recorder
        streamer_visualizer = self._get_streamer_visualizer()
        if streamer_recorder is not None and streamer_visualizer is not None:
            try:
                if hasattr(streamer_visualizer, 'get_snapshot_frame'):
                    frame = streamer_visualizer.get_snapshot_frame()
                elif hasattr(streamer_visualizer, 'get_processed_frame'):
                    frame = streamer_visualizer.get_processed_frame()
                elif hasattr(streamer_visualizer, 'get_raw_frame'):
                    frame = streamer_visualizer.get_raw_frame()
                else:
                    frame = None
                if frame is not None:
                    streamer_recorder.write_frame(frame)
            except Exception as e:
                logger.warning(f"Failed to write executor-synced streamer frame: {e}")

    def _handle_stage_movements(self, frame_idx: int, active_droplets):
        """Handle stage movements to follow active droplets that have moved since the previous frame."""
        # If we are paused at a breakpoint, do not interfere with manual stage targeting.
        if self.breakpoint_reached.is_set():
            return
            
        manual_target = None
        with self.execution_lock:
            if self.manual_stage_target is not None:
                if self.manual_stage_target_expires_at is None or frame_idx < self.manual_stage_target_expires_at:
                    manual_target = self.manual_stage_target
                else:
                    logger.debug(f"Manual stage target expired at frame {frame_idx}")
                    self.manual_stage_target = None
                    self.manual_stage_target_expires_at = None

        if manual_target is not None:
            self._move_stage_to_target(frame_idx, "manual", manual_target)
            return

        if not active_droplets:
            return

        # Get trajectories for active droplets
        trajectories = getattr(self.current_plan, 'droplet_trajectories', {})

        # Collect positions of active droplets that have moved since the previous frame
        moved_droplets = []
        for droplet in active_droplets:
            if droplet.id in trajectories:
                trajectory = trajectories[droplet.id]
                if frame_idx < len(trajectory):
                    current_pos = trajectory[frame_idx]
                    if frame_idx > 0 and frame_idx < len(trajectory):
                        prev_pos = trajectory[frame_idx - 1]
                        if current_pos != prev_pos:
                            moved_droplets.append((droplet.id, current_pos))
                        elif frame_idx == 0:
                        # For the first frame, consider all active droplets as "moved" (from initial state)
                            moved_droplets.append((droplet.id, current_pos))

        # If no droplets moved, select any active droplet to follow
        if not moved_droplets and active_droplets:
            # Select the first active droplet
            first_droplet = active_droplets[0]
            if first_droplet.id in trajectories:
                trajectory = trajectories[first_droplet.id]
                if frame_idx < len(trajectory):
                    target_position = trajectory[frame_idx]
                    moved_droplets.append((first_droplet.id, target_position))

        if not moved_droplets:
            return

        # If multiple droplets have moved, cycle through them
        # Each droplet gets 5 frames of stage focus before switching
        if len(moved_droplets) > 1:
            # Calculate which droplet should be followed based on frame number
            cycle_length = 5  # frames per droplet
            total_cycle_length = len(moved_droplets) * cycle_length
            cycle_position = frame_idx % total_cycle_length
            droplet_index = cycle_position // cycle_length

            target_droplet_id, target_position = moved_droplets[droplet_index]
        else:
            # Only one droplet moved, follow it
            target_droplet_id, target_position = moved_droplets[0]

        # Convert electrode position to stage coordinates
        self._move_stage_to_target(frame_idx, target_droplet_id, target_position)

    def _move_stage_to_target(self, frame_idx: int, target_id, target_position):
        """Move the stage to a selected target and wait for motion completion."""
        with self.stage_motion_lock:
            try:
                stage_position = self._electrode_to_stage_position(target_position)
                
                has_stage = hasattr(self.system, "xy_stage")
                is_mock = type(self.system).__name__ == "Simulator"
                
                if stage_position and has_stage:
                    if self.last_stage_target_position == stage_position and self._is_stage_idle():
                        logger.debug(
                            f"Frame {frame_idx}: Stage already at target {target_id} -> {stage_position}, skipping move"
                        )
                        return

                    # Move stage to follow the droplet if we aren't paused at a breakpoint
                    if not self.breakpoint_reached.is_set():
                        self.system.update_state("xy_stage.position", stage_position)
                        self.last_stage_target_position = stage_position.copy()

                        timeout = 10.0  # 10 second timeout
                        motion_complete = False

                        if is_mock:
                            motion_complete = True
                        else:
                            # Give hardware a fraction of a second to start the motion before asking if it is done
                            time.sleep(0.2)

                            # Wait for stage motion to complete with timeout
                            start_time = time.time()
                            while time.time() - start_time < timeout:
                                # Don't wait if a breakpoint was suddenly reached
                                if self.breakpoint_reached.is_set():
                                    break
                                motion_complete = all(self.system.xy_stage.is_motion_complete(axis) for axis in ['X', 'Y', 'Z'])
                                if motion_complete:
                                    break
                                time.sleep(0.1)  # Check every 100ms

                    if not motion_complete:
                        logger.warning(f"Stage motion timeout after {timeout}s for target {target_id}")
                    else:
                        if not is_mock:
                            # Additional wait scaled with frame_delay (no minimum for fast execution)
                            wait_time_after = min(0.5, self.frame_delay * 2)
                            if wait_time_after > 0:
                                time.sleep(wait_time_after)

                    logger.debug(f"Frame {frame_idx}: Stage following target {target_id} at electrode {target_position} -> stage {stage_position}")
            except Exception as e:
                logger.warning(f"Failed to move stage for target {target_id}: {e}")

    def _electrode_to_stage_position(self, electrode_pos):
        """Convert electrode position to stage coordinates."""
        row, col = electrode_pos

        # Get calibration data from system state
        try:
            state = self.system.state
            chip_origin = state.get('calibration', {}).get('chip_origin', {})
            electrode_mapping = state.get('calibration', {}).get('electrode_mapping', {})
            
            # Use inter_row_distance and inter_column_distance for X,Y (as before)
            inter_row_distance = state.get('inter_row_distance', {})
            inter_column_distance = state.get('inter_column_distance', {})

            # Calculate X,Y stage position using distance objects
            x_stage = chip_origin.get('X', 0) + row * inter_row_distance.get('X', 0) + col * inter_column_distance.get('X', 0)
            y_stage = chip_origin.get('Y', 0) + row * inter_row_distance.get('Y', 0) + col * inter_column_distance.get('Y', 0)
            
            # Calculate Z stage position using electrode_mapping arrays for proper centering
            inter_row = electrode_mapping.get('inter_row', [0, 0, 0])
            inter_column = electrode_mapping.get('inter_column', [0, 0, 0])
            offset_x = electrode_mapping.get('offset_x', 0)
            offset_y = electrode_mapping.get('offset_y', 0)
            
            # Z offset calculation: row * inter_row[2] + col * inter_column[2] + offsets
            z_offset = (row * inter_row[2] if len(inter_row) > 2 else 0) + \
                      (col * inter_column[2] if len(inter_column) > 2 else 0)
            
            z_stage = chip_origin.get('Z', 0) + z_offset

            return {'X': int(x_stage), 'Y': int(y_stage), 'Z': int(z_stage)}
        except Exception as e:
            logger.warning(f"Failed to convert electrode position {electrode_pos} to stage coordinates: {e}")
            return None

    def _handle_verification(self, frame_idx: int):
        """Handle position verification."""
        if self.validator and hasattr(self.validator, 'validate_sipp_frame'):
            try:
                verification = self.validator.validate_sipp_frame(frame_idx=frame_idx)
                logger.debug(f"Verification at frame {frame_idx}: {verification}")
            except Exception as e:
                logger.warning(f"Verification failed at frame {frame_idx}: {e}")

    def _process_events(self, frame_idx: int):
        """Process events for the current frame."""
        if not hasattr(self.current_plan, 'events'):
            return

        for event_frame, event_type, data in self.current_plan.events:
            if event_frame == frame_idx:
                if event_type == 'create_droplet':
                    # Add droplet to the list
                    self.advanced_drop.droplets.append(data)
                    logger.debug(f"Created droplet {data.id} at frame {frame_idx}")
                elif event_type == 'remove_droplet':
                    # Remove droplet from the list
                    droplet_id = data
                    self.advanced_drop.droplets = [d for d in self.advanced_drop.droplets if d.id != droplet_id]
                    logger.debug(f"Removed droplet {droplet_id} at frame {frame_idx}")
                elif event_type == 'update_droplet_position':
                    # Update droplet position
                    droplet_id, new_position = data
                    for droplet in self.advanced_drop.droplets:
                        if droplet.id == droplet_id:
                            droplet.origin_corner = new_position
                            break
                    logger.debug(f"Updated droplet {droplet_id} position to {new_position} at frame {frame_idx}")

    def __del__(self):
        """Cleanup on destruction."""
        self.stop()
