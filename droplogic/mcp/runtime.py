"""Runtime layer for the DropLogic MCP server.

This module owns the live DropSystem instance and exposes a JSON-safe API for
MCP tools. The MCP transport stays thin; hardware ownership, safety gates and
serialization live here.
"""

import base64
import copy
import hashlib
import inspect
import json
import logging
import os
import pickle
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from .context_store import DropLogicMCPContextStore
from droplogic.utils.drop_vision.imaging_capture import (
    capture_channel_frame,
    snapshot_capture_settings,
)
from droplogic.utils.window_manager import get_window_status


class DropLogicMCPError(RuntimeError):
    """Raised for user-facing MCP runtime errors."""


class DropLogicMCPRuntime:
    """Own a single DropLogic system for MCP-controlled sessions."""

    SYSTEM_METHODS = {
        "get_queue_status",
        "get_simulated_matrix",
        "get_simulated_voltage",
        "get_active_electrode_count",
        "get_electrode_state",
        "set_electrode_state",
        "activate_electrode_pattern",
        "print_matrix_summary",
    }

    ADVANCED_DROP_METHODS = {
        "remove_duplicates",
        "move",
        "reservoir_extraction",
        "isometric_split",
        "mix",
        "merge",
        "verify_droplets",
        "detect_condensates",
        "correct_droplet_position",
        "move_to_droplet_center",
        "clear",
        "get_droplet_position",
        "merge_sequential_events",
        "push_frame",
        "trim_plan_tail",
    }

    PLAN_MOVE_OPTION_KEYS = {
        "max_frames",
        "planning_timeout",
        "debug_visualization",
        "max_threads",
        "max_iterations",
        "retry_attempts",
        "ignore_vital_space_pairs",
        "all_active_droplets",
        "reserve_final_positions",
        "merge_hub",
        "hub_ignore_pairs",
        "hub_ignore_from_frame",
        "reservation_horizon",
        "max_path_frames",
        "add_events",
        "merge_on_failure",
        "return_full_result",
    }

    PLAN_PRIMITIVE_METHODS = {
        "move",
        "reservoir_extraction",
        "isometric_split",
        "mix",
        "merge",
    }

    MODULE_METHODS = {
        "capacitive_feedback": {
            "read_feedback",
        },
        "camera": {
            "enum_devices",
            "open_camera",
            "capture_image",
            "set_parameter",
            "set_exposure",
            "set_exposure_auto",
            "get_parameter",
            "get_exposure",
        },
        "electrode_matrix": {
            "set_voltage",
            "deactivate_all",
            "set_electrode",
            "set_chip",
            "set_droplet",
            "set_droplets",
        },
        "light": {
            "switch_light",
            "set_coaxial_light",
            "set_ring_light",
            "get_state",
        },
        "microscope": {
            "enum_devices",
            "capture_image",
            "set_parameter",
            "set_exposure",
            "set_exposure_auto",
            "set_channel",
            "get_parameter",
            "get_exposure",
        },
        "temperature": {
            "set_temperature",
            "get_temperature",
            "get_target_temperature",
            "set_default_pid",
            "get_all_temperatures",
            "get_mapping",
            "set_mapping",
            "set_per_channel_targets",
            "get_targets",
            "get_pid_and_regression_params",
        },
        "xy_stage": {
            "set_params",
            "move_axis_to_position",
            "home_axis",
            "is_homing_complete",
            "is_motion_complete",
            "get_position",
            "get_raw_position",
            "get_axis_error_reason",
            "clear_axis_error",
            "stop_and_clear_axis",
            "stop_motion",
            "get_home_switch",
            "get_positive_limit",
            "get_negative_limit",
            "start_continuous_movement",
            "stop_continuous_movement",
        },
    }

    UNSAFE_MODULE_METHODS = {
        ("electrode_matrix", "set_electrode"),
        ("electrode_matrix", "set_chip"),
        ("electrode_matrix", "set_droplet"),
        ("electrode_matrix", "set_droplets"),
        ("xy_stage", "start_continuous_movement"),
    }

    EXECUTOR_OWNED_MODULES = {
        "electrode_matrix",
        "xy_stage",
        "camera",
        "microscope",
    }

    SYSTEM_METHOD_MODULES = {
        "get_simulated_matrix": "electrode_matrix",
        "get_simulated_voltage": "electrode_matrix",
        "get_active_electrode_count": "electrode_matrix",
        "get_electrode_state": "electrode_matrix",
        "set_electrode_state": "electrode_matrix",
        "activate_electrode_pattern": "electrode_matrix",
        "print_matrix_summary": "electrode_matrix",
    }

    SYSTEM_BUSY_GATED_METHODS = {
        "set_electrode_state",
        "activate_electrode_pattern",
    }

    VISUALIZER_METHODS = {
        "matrix": {
            "bring_to_front",
            "is_running",
            "requires_main_thread_window",
            "set_matrix_rotation",
            "clear_paths",
            "save_snapshot",
        },
        "streamer": {
            "bring_to_front",
            "is_running",
            "requires_main_thread_window",
            "get_electrodes_in_fov",
            "enable_droplet_detection",
            "disable_droplet_detection",
            "enable_condensate_detection",
            "disable_condensate_detection",
            "set_detection_style",
            "set_condensate_detection_style",
        },
    }

    REAL_SYSTEMS = {"dmlite", "boxmini", "box_mini", "box_mini1"}
    ADVANCED_DROP_SYNC_MOVE_MAX_ACTIVE = 5
    ADVANCED_DROP_SYNC_MOVE_MAX_TIMEOUT = 45.0
    EXECUTE_SEGMENT_INLINE_WAIT_MAX_SECONDS = 75.0
    EXECUTE_SEGMENT_INLINE_WAIT_MARGIN_SECONDS = 8.0
    EXECUTION_WAIT_STATUS_MAX_WAIT_SECONDS = 30.0
    EXECUTION_WAIT_STATUS_MIN_WAIT_SECONDS = 2.0
    LARGE_STATE_PATHS = {
        "electrode_matrix.matrix",
    }

    def __init__(
        self,
        config_file: str = "config.json",
        log_level: str = "INFO",
        allow_real_hardware: bool = False,
        allow_unsafe_tools: bool = False,
        allow_large_state_tools: bool = False,
        snapshots_dir: Optional[str] = None,
        context_dir: Optional[str] = None,
    ):
        self.config_file = config_file
        self.log_level = log_level
        self.allow_real_hardware = allow_real_hardware
        self.allow_unsafe_tools = allow_unsafe_tools
        self.allow_large_state_tools = allow_large_state_tools
        self.snapshots_dir = os.path.abspath(
            snapshots_dir
            or os.path.join(tempfile.gettempdir(), "droplogic_mcp_snapshots")
        )
        self.session_id = uuid.uuid4().hex[:12]
        self._lock = threading.RLock()
        self.context_dir = context_dir
        self.context = DropLogicMCPContextStore(system_name="boxmini", context_dir=context_dir)
        self.system = None
        self.system_name = None
        self.loaded_at = None
        self.last_error = None
        self.last_visualizer_prepare_result = None
        self._temperature_routine_lock = threading.RLock()
        self._temperature_routine_status: Optional[Dict[str, Any]] = None
        self._temperature_routine_thread: Optional[threading.Thread] = None
        self._temperature_routine_stop_event = threading.Event()
        self._advanced_drop_job_lock = threading.RLock()
        self._advanced_drop_job_status: Optional[Dict[str, Any]] = None
        self._advanced_drop_job_thread: Optional[threading.Thread] = None
        self._advanced_drop_job_cancel_event = threading.Event()
        self._execution_wait_lock = threading.RLock()
        self._execution_wait_status: Optional[Dict[str, Any]] = None
        self._execution_wait_thread: Optional[threading.Thread] = None
        self._execution_wait_cancel_event = threading.Event()
        self._real_hardware_lock_handle = None
        self._real_hardware_lock_path: Optional[str] = None
        self._real_hardware_lock_system: Optional[str] = None
        self.dashboard_scene_path = os.environ.get("DROPLOGIC_DASHBOARD_SCENE_PATH")
        self._dashboard_scene_write_lock = threading.RLock()
        self._dashboard_timeline_cache_key: Optional[Tuple[Any, ...]] = None
        self._dashboard_timeline_cache: Optional[Dict[str, Any]] = None

    def _runtime_mode(self) -> Dict[str, Any]:
        cockpit_mode = str(os.environ.get("DROPLOGIC_COCKPIT_MODE", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        visualizer_headless = str(os.environ.get("DROPLOGIC_VISUALIZER_HEADLESS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return {
            "cockpit": cockpit_mode,
            "visualizer_windows": not (cockpit_mode or visualizer_headless),
            "visualizer_delivery": "cockpit_frames" if cockpit_mode else "opencv_windows",
            "agent_note": (
                "Cockpit mode is active: the browser renders matrix and streamer frames. "
                "Do not bring OpenCV visualizer windows to front unless the user explicitly asks."
                if cockpit_mode
                else None
            ),
        }

    # ---------------------------------------------------------------------
    # System lifecycle

    def load_system(
        self,
        system: str = "simulator",
        config_file: Optional[str] = None,
        log_level: Optional[str] = None,
        reset_matrix: bool = False,
    ) -> Dict[str, Any]:
        """Instantiate a DropLogic system under this runtime."""
        system_key = (system or "simulator").lower()
        config_file = config_file or self.config_file
        log_level = log_level or self.log_level

        if system_key in self.REAL_SYSTEMS and not self.allow_real_hardware:
            raise DropLogicMCPError(
                "Real hardware is disabled for this MCP server. Restart with "
                "--allow-real-hardware before loading DMLite or BOXMini."
            )

        with self._lock:
            if self.system is not None:
                self.close_system()

            self._acquire_real_hardware_lock(system_key)
            try:
                if system_key == "simulator":
                    from droplogic.hardware.simulator import Simulator

                    self.system = Simulator(
                        config_file=config_file,
                        log_level=log_level,
                        reset_matrix=reset_matrix,
                    )
                    self.system_name = "simulator"
                elif system_key == "dmlite":
                    from droplogic.hardware.DMLite import DMLite

                    self.system = DMLite(
                        config_file=config_file,
                        log_level=log_level,
                        reset_matrix=reset_matrix,
                    )
                    self.system_name = "dmlite"
                elif system_key in {"boxmini", "box_mini", "box_mini1"}:
                    from droplogic.hardware.box_mini1 import BOXMini

                    self.system = BOXMini(
                        config_file=config_file,
                        log_level=log_level,
                        reset_matrix=reset_matrix,
                    )
                    self.system_name = "boxmini"
                else:
                    raise DropLogicMCPError(
                        f"Unknown system '{system}'. Use simulator, dmlite, or boxmini."
                    )
            except Exception:
                self._release_real_hardware_lock()
                raise

            self._namespace_visualizer_windows(self.system)
            self._attach_dashboard_scene_writer(self.system)
            self._set_context_system(self.system_name)
            self.config_file = config_file
            self.log_level = log_level
            self.loaded_at = time.time()
            self.last_visualizer_prepare_result = None
            if self.system_name == "boxmini":
                try:
                    self.last_visualizer_prepare_result = self.prepare_visualizers(
                        start_matrix=True,
                        start_streamer=True,
                        streamer_source="microscope",
                        streamer_coordinates=False,
                        streamer_electrode_overlay=True,
                        bring_to_front=False,
                        warmup_seconds=1.0,
                    )
                except Exception as exc:
                    self._record_error("auto_prepare_visualizers", exc)
                    self.last_visualizer_prepare_result = {
                        "ok": False,
                        "error": self.to_jsonable(self.last_error),
                    }
            return self.status()

    def close_system(self) -> Dict[str, Any]:
        """Close the current DropSystem, if any."""
        with self._lock:
            self._temperature_routine_stop_event.set()
            self._execution_wait_cancel_event.set()
            temperature_thread = self._temperature_routine_thread
            if temperature_thread is not None and temperature_thread.is_alive():
                temperature_thread.join(timeout=2.0)
            execution_wait_thread = self._execution_wait_thread
            if execution_wait_thread is not None and execution_wait_thread.is_alive():
                execution_wait_thread.join(timeout=2.0)

            system = self.system
            if system is not None:
                self._detach_dashboard_scene_writer(system)
                for visualizer_name in ("streamer", "matrix"):
                    instance = self._get_visualizer_instance(system, visualizer_name)
                    stop = getattr(instance, "stop", None)
                    if stop is None:
                        continue
                    try:
                        stop()
                    except Exception as exc:
                        self._record_error(f"stop_visualizer:{visualizer_name}", exc)
                if hasattr(system, "close"):
                    system.close()
            self.system = None
            self.system_name = None
            self.loaded_at = None
            self.last_visualizer_prepare_result = None
            self._release_real_hardware_lock()
            return self.status()

    def require_system(self):
        if self.system is None:
            raise DropLogicMCPError("No system loaded. Call load_system() first.")
        return self.system

    def _set_context_system(self, system_name: Optional[str]) -> None:
        self.context = DropLogicMCPContextStore(
            system_name=system_name or "boxmini",
            context_dir=self.context_dir,
        )

    def require_advanced_drop(self):
        system = self.require_system()
        advanced_drop = getattr(system, "advanced_drop", None)
        if advanced_drop is None:
            raise DropLogicMCPError("Loaded system does not expose advanced_drop.")
        return advanced_drop

    def require_executor(self):
        advanced_drop = self.require_advanced_drop()
        executor = getattr(advanced_drop, "executor", None)
        if executor is None:
            raise DropLogicMCPError("Loaded system does not expose a PlanExecutor.")
        return executor

    def _attach_dashboard_scene_writer(self, system: Any) -> None:
        if not self.dashboard_scene_path:
            return
        executor = getattr(getattr(system, "advanced_drop", None), "executor", None)
        if executor is None:
            return

        def _write_scene(_event: Optional[Dict[str, Any]] = None) -> None:
            self.write_dashboard_scene_snapshot()

        try:
            executor.on_frame_applied = _write_scene
        except Exception:
            pass

    def _detach_dashboard_scene_writer(self, system: Any) -> None:
        executor = getattr(getattr(system, "advanced_drop", None), "executor", None)
        if executor is None:
            return
        try:
            if getattr(executor, "on_frame_applied", None) is not None:
                executor.on_frame_applied = None
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Read/observe

    def status(self, detail: str = "compact") -> Dict[str, Any]:
        """Return a compact runtime status."""
        detail = str(detail or "compact").lower()
        with self._lock:
            system = self.system
            system_status = {
                "loaded": system is not None,
                "system": self.system_name,
                "loaded_at": self.loaded_at,
            }
            if system is not None:
                system_status.update(
                    {
                        "name": getattr(system, "name", None),
                        "host_os": getattr(system, "host_os", None),
                        "host_platform": self.to_jsonable(
                            getattr(system, "host_platform", None)
                        ),
                    }
                )
                if detail == "full" and hasattr(system, "get_queue_status"):
                    system_status["queues"] = self.to_jsonable(system.get_queue_status())

            visualizer_status = None
            if system is not None:
                try:
                    visualizer_status = self.visualizer_status()
                except Exception as exc:
                    visualizer_status = {"error": str(exc)}

            executor_status = None
            plan_summary = None
            droplet_summary = None
            if system is not None and hasattr(system, "advanced_drop"):
                advanced_drop = system.advanced_drop
                executor = getattr(advanced_drop, "executor", None)
                if executor is not None:
                    executor_status = self.to_jsonable(executor.status())
                plan_summary = self.plan_summary(getattr(advanced_drop, "plan", None))
                droplets = getattr(advanced_drop, "droplets", None)
                if droplets is not None and hasattr(droplets, "get_droplets_summary"):
                    droplet_summary = self.to_jsonable(droplets.get_droplets_summary())

            status = {
                "session_id": self.session_id,
                "runtime_mode": self._runtime_mode(),
                "allow_real_hardware": self.allow_real_hardware,
                "allow_unsafe_tools": self.allow_unsafe_tools,
                "config_file": self.config_file,
                "context": self.context_status(),
                "last_error": self.to_jsonable(self.last_error),
                "system": system_status,
                "executor": executor_status,
                "plan": plan_summary,
                "droplets": droplet_summary,
                "visualizers": visualizer_status,
                "last_visualizer_prepare_result": self.to_jsonable(
                    self.last_visualizer_prepare_result
                ),
            }
            if detail != "full":
                status["executor"] = self._compact_executor_status(executor_status)
                status["plan"] = self._compact_plan_status(plan_summary)
                status["droplets"] = self._compact_droplets_status(droplet_summary)
                status["visualizers"] = self._compact_visualizer_status(visualizer_status)
                status.pop("last_visualizer_prepare_result", None)
            return status

    def _compact_executor_status(self, status: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(status, dict):
            return status
        last_frame = status.get("last_frame") if isinstance(status.get("last_frame"), dict) else {}
        last_applied = (
            status.get("last_applied_frame")
            if isinstance(status.get("last_applied_frame"), dict)
            else {}
        )
        return {
            "is_executing": status.get("is_executing"),
            "current_frame": status.get("current_frame"),
            "total_frames": status.get("total_frames"),
            "frames_executed": status.get("frames_executed"),
            "frame_delay": status.get("frame_delay"),
            "progress": status.get("progress"),
            "breakpoints": status.get("breakpoints"),
            "breakpoint_reached": status.get("breakpoint_reached"),
            "last_frame": {
                "index": last_frame.get("index"),
                "error": last_frame.get("error"),
                "duration_seconds": last_frame.get("duration_seconds"),
            },
            "last_applied_frame": {
                "index": last_applied.get("index"),
                "plan_frame_count": last_applied.get("plan_frame_count"),
                "active_droplet_ids": last_applied.get("active_droplet_ids"),
            },
        }

    def _compact_execution_wait_status(self, status: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(status, dict):
            return status
        compact = {
            "wait_id": status.get("wait_id"),
            "running": status.get("running"),
            "completed": status.get("completed"),
            "ok": status.get("ok"),
            "thread_alive": status.get("thread_alive"),
            "cancel_requested": status.get("cancel_requested"),
            "timeout_seconds": status.get("timeout_seconds"),
            "poll_interval_seconds": status.get("poll_interval_seconds"),
            "target_frame": status.get("target_frame"),
            "resume_if_paused": status.get("resume_if_paused"),
            "wait_mode": status.get("wait_mode"),
            "timed_out": status.get("timed_out"),
            "reason": status.get("reason"),
            "error": status.get("error"),
            "elapsed_seconds": status.get("elapsed_seconds"),
            "remaining_timeout_seconds": status.get("remaining_timeout_seconds"),
            "recommended_wait_seconds": status.get("recommended_wait_seconds"),
            "next_check_after_seconds": status.get("next_check_after_seconds"),
            "recommended_status_call": status.get("recommended_status_call"),
            "status_wait": status.get("status_wait"),
        }
        if compact.get("running"):
            recommended_wait_seconds = compact.get("recommended_wait_seconds")
            if recommended_wait_seconds is None:
                recommended_wait_seconds = self._execution_wait_recommended_wait_seconds(
                    status=compact
                )
            compact["recommended_wait_seconds"] = recommended_wait_seconds
            compact["next_check_after_seconds"] = recommended_wait_seconds
            compact["recommended_status_call"] = {
                "tool": "execution_wait_status",
                "arguments": {"wait_seconds": recommended_wait_seconds},
            }
        if "executor_status" in status:
            compact["executor_status"] = self._compact_executor_status(
                status.get("executor_status")
            )
        if "executor_status_error" in status:
            compact["executor_status_error"] = status.get("executor_status_error")
        return compact

    def _compact_plan_status(self, plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(plan, dict):
            return plan
        return {
            "available": plan.get("available"),
            "frame_count": plan.get("frame_count"),
            "planning_success": plan.get("planning_success"),
            "active_droplet_ids": plan.get("active_droplet_ids"),
            "targets_reached": plan.get("targets_reached"),
            "event_count": len(plan.get("events") or []),
            "trajectories": plan.get("trajectories"),
        }

    def _compact_droplets_status(self, droplets: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(droplets, dict):
            return droplets
        compact: Dict[str, Any] = {
            "total_droplets": droplets.get("total_droplets"),
            "active_droplet_ids": droplets.get("active_droplet_ids"),
            "has_plan": droplets.get("has_plan"),
        }
        entries = []
        for droplet in droplets.get("droplets") or []:
            if not isinstance(droplet, dict):
                entries.append(self._summarize_state_value(droplet))
                continue
            entries.append(
                {
                    key: droplet.get(key)
                    for key in (
                        "id",
                        "active",
                        "current_position",
                        "target_position",
                        "at_target",
                        "shape_size",
                        "priority",
                        "vital_space",
                    )
                    if key in droplet
                }
            )
        compact["droplets"] = entries
        return compact

    def _compact_visualizer_status(self, visualizers: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(visualizers, dict):
            return visualizers
        compact: Dict[str, Any] = {}
        for name, entry in visualizers.items():
            if not isinstance(entry, dict):
                compact[name] = entry
                continue
            compact[name] = {
                "available": entry.get("available"),
                "is_running": entry.get("is_running"),
                "window_enabled": entry.get("window_enabled"),
                "window_mode": entry.get("window_mode"),
                "headless_active": entry.get("headless_active"),
                "display_active": entry.get("display_active"),
                "source": entry.get("source"),
                "frame_sources": entry.get("frame_sources"),
                "last_exit_reason": entry.get("last_exit_reason"),
                "last_display_error": entry.get("last_display_error"),
            }
        return compact

    def health_check(self) -> Dict[str, Any]:
        """Return a health snapshot for agent supervision."""
        system = self.system
        queue_workers = {}
        if system is not None:
            workers = getattr(system, "_queue_workers", {}) or {}
            for priority, worker in workers.items():
                queue_workers[getattr(priority, "name", str(priority))] = {
                    "alive": bool(worker and worker.is_alive()),
                }

        workers_ok = all(item["alive"] for item in queue_workers.values()) if queue_workers else True
        return {
            "ok": system is not None and workers_ok,
            "session_id": self.session_id,
            "system": self.system_name,
            "system_loaded": system is not None,
            "queue_workers": queue_workers,
            "executor": self.to_jsonable(
                getattr(getattr(system, "advanced_drop", None), "executor", None).status()
                if system is not None
                and hasattr(system, "advanced_drop")
                and getattr(system.advanced_drop, "executor", None) is not None
                else None
            ),
            "modules": self.module_busy_status() if system is not None else {},
            "last_error": self.to_jsonable(self.last_error),
            "recommended_action": None
            if system is not None and workers_ok
            else "restart_system",
        }

    def restart_system(
        self,
        system: Optional[str] = None,
        config_file: Optional[str] = None,
        log_level: Optional[str] = None,
        reset_matrix: bool = False,
    ) -> Dict[str, Any]:
        """Close and re-load a system after an agent-observed failure."""
        target_system = system or self.system_name
        if not target_system:
            raise DropLogicMCPError("No system is loaded. Pass system='simulator', 'dmlite', or 'boxmini'.")

        with self._lock:
            self.close_system()
            return self.load_system(
                target_system,
                config_file=config_file or self.config_file,
                log_level=log_level or self.log_level,
                reset_matrix=reset_matrix,
            )

    def read_state(
        self,
        path: Optional[str] = None,
        include_large_values: bool = False,
    ) -> Dict[str, Any]:
        """Read a DropSystem state path, guarding raw large values by default."""
        system = self.require_system()
        state = system.state
        if not path:
            return {
                "path": None,
                "value": self._safe_state_for_agents(state),
                "large_values_omitted": True,
                "message": (
                    "Full raw state is guarded because it can include very large values "
                    "such as the 128 x 128 electrode matrix. Use state_summary(), "
                    "matrix_summary(), or read_state(path=...) for exact small paths."
                ),
            }

        normalized_path = self._normalize_state_path(path)
        if self._is_large_state_path(normalized_path) and not include_large_values:
            return {
                "path": path,
                "large_value_guarded": True,
                "message": (
                    f"Raw state path '{path}' is large and guarded for agent context safety. "
                    "Use matrix_summary() for exact compact active ranges, "
                    "state_summary(path='electrode_matrix.matrix') for a summary, or "
                    "read_large_state(path='electrode_matrix.matrix') only with large-state access enabled."
                ),
                "summary": self.matrix_summary(source="state", include_ranges=True),
            }
        if self._is_large_state_path(normalized_path):
            self._require_large_state_access(path)

        current = self._resolve_state_path(state, path)
        return {"path": path, "value": self.to_jsonable(current)}

    def state_summary(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Read DropSystem state with large arrays/lists summarized."""
        system = self.require_system()
        state = system.state
        current = state
        if path:
            current = self._resolve_state_path(state, path)

        return {
            "path": path,
            "value": self._summarize_state_value(current),
        }

    def read_large_state(self, path: str) -> Dict[str, Any]:
        """Read an explicitly large state value when large-state tools are enabled."""
        normalized_path = self._normalize_state_path(path)
        if not self._is_large_state_path(normalized_path):
            raise DropLogicMCPError(
                f"read_large_state is only for guarded large paths. Use read_state(path='{path}') instead."
            )
        self._require_large_state_access(path)
        system = self.require_system()
        current = self._resolve_state_path(system.state, path)
        return {
            "path": path,
            "large_state_access": True,
            "warning": (
                "This raw value can be very large and should not be sent back to an LLM context "
                "unless the user explicitly requested the literal data."
            ),
            "value": self.to_jsonable(current),
        }

    def matrix_summary(
        self,
        source: str = "state",
        include_ranges: bool = True,
        include_active_cells: bool = False,
        active_cells_limit: int = 512,
        include_hash: bool = True,
    ) -> Dict[str, Any]:
        """Return an exact compact representation of the latest electrode matrix."""
        matrix = self._get_matrix_for_summary(source)
        return self._matrix_compact_representation(
            matrix,
            source=source,
            include_ranges=include_ranges,
            include_active_cells=include_active_cells,
            active_cells_limit=active_cells_limit,
            include_hash=include_hash,
        )

    def set_matrix_cells(
        self,
        value: int,
        cells: Optional[List[List[int]]] = None,
        rectangles: Optional[List[Dict[str, int]]] = None,
        row_min: Optional[int] = None,
        row_max: Optional[int] = None,
        col_min: Optional[int] = None,
        col_max: Optional[int] = None,
        wait_for_queue: bool = False,
        queue_timeout_seconds: float = 5.0,
    ) -> Dict[str, Any]:
        """Set logical electrode matrix cells for planning/UI overlays.

        Values are -1 forbidden/not allowed, 0 clean/off, and 1 permanent ON.
        Hardware drivers receive their normal binary projection, where -1 stays off.
        """
        matrix_value = int(value)
        if matrix_value not in {-1, 0, 1}:
            raise DropLogicMCPError("value must be -1 (forbidden), 0 (clean), or 1 (active).")

        system = self.require_system()
        state = system.state
        matrix = (state.get("electrode_matrix") or {}).get("matrix")
        if matrix is None:
            raise DropLogicMCPError("No electrode_matrix.matrix found in system.state.")

        array = np.asarray(matrix).astype(int).copy()
        if array.ndim != 2:
            raise DropLogicMCPError("electrode_matrix.matrix must be 2-dimensional.")
        before = array.copy()
        rows, cols = array.shape

        normalized_rectangles: List[Dict[str, int]] = []
        raw_rectangles = list(rectangles or [])
        if None not in (row_min, row_max, col_min, col_max):
            raw_rectangles.append(
                {
                    "row_min": int(row_min),
                    "row_max": int(row_max),
                    "col_min": int(col_min),
                    "col_max": int(col_max),
                }
            )

        for rect in raw_rectangles:
            if not isinstance(rect, dict):
                continue
            r0 = int(rect.get("row_min", rect.get("row0", rect.get("r0", 0))))
            r1 = int(rect.get("row_max", rect.get("row1", rect.get("r1", r0))))
            c0 = int(rect.get("col_min", rect.get("col0", rect.get("c0", 0))))
            c1 = int(rect.get("col_max", rect.get("col1", rect.get("c1", c0))))
            r_start = max(0, min(rows - 1, min(r0, r1)))
            r_end = max(0, min(rows - 1, max(r0, r1)))
            c_start = max(0, min(cols - 1, min(c0, c1)))
            c_end = max(0, min(cols - 1, max(c0, c1)))
            if r_start > r_end or c_start > c_end:
                continue
            array[r_start : r_end + 1, c_start : c_end + 1] = matrix_value
            normalized_rectangles.append(
                {
                    "row_min": int(r_start),
                    "row_max": int(r_end),
                    "col_min": int(c_start),
                    "col_max": int(c_end),
                }
            )

        normalized_cells: List[List[int]] = []
        for cell in cells or []:
            if not isinstance(cell, (list, tuple)) or len(cell) < 2:
                continue
            row = int(cell[0])
            col = int(cell[1])
            if 0 <= row < rows and 0 <= col < cols:
                array[row, col] = matrix_value
                normalized_cells.append([int(row), int(col)])

        if not normalized_rectangles and not normalized_cells:
            raise DropLogicMCPError("Provide cells, rectangles, or row_min/row_max/col_min/col_max.")

        changed_cells = int(np.count_nonzero(array != before))
        result = system.update_state("electrode_matrix.matrix", array.tolist())
        persisted_runtime_state = False
        persistence_error = None
        try:
            persist_value = getattr(system, "_record_runtime_persistent_value", None)
            if callable(persist_value):
                persist_value("electrode_matrix.matrix", array.tolist())
                flush_state = getattr(system, "flush_state", None)
                if callable(flush_state):
                    flush_state()
                persisted_runtime_state = True
        except Exception as exc:
            persistence_error = str(exc)
        queue_wait = None
        if wait_for_queue:
            queue_wait = self._wait_for_hardware_queue_empty(
                timeout_seconds=queue_timeout_seconds,
                poll_interval=0.05,
            )

        return {
            "ok": True,
            "value": matrix_value,
            "changed_cells": changed_cells,
            "rectangles": normalized_rectangles,
            "cells": normalized_cells[:256],
            "cells_truncated": len(normalized_cells) > 256,
            "update_state": self.to_jsonable(result),
            "persisted_runtime_state": persisted_runtime_state,
            "persistence_error": persistence_error,
            "wait_for_hardware_queue": queue_wait,
            "matrix": self._matrix_compact_representation(
                array,
                source="state",
                include_ranges=True,
                include_active_cells=False,
                include_hash=True,
            ),
        }

    def set_calibration(self, calibration: Dict[str, Any]) -> Dict[str, Any]:
        """Update the loaded system's calibration mapping without enqueuing hardware."""
        if not isinstance(calibration, dict):
            raise DropLogicMCPError("calibration must be an object.")
        chip_origin = calibration.get("chip_origin")
        mapping = calibration.get("electrode_mapping")
        if not isinstance(chip_origin, dict) or not isinstance(mapping, dict):
            raise DropLogicMCPError("calibration needs chip_origin and electrode_mapping objects.")
        system = self.require_system()
        if hasattr(system, "set_cached_state"):
            result = system.set_cached_state("calibration", copy.deepcopy(calibration))
        else:
            with getattr(system, "_state_lock", threading.RLock()):
                system._state["calibration"] = copy.deepcopy(calibration)
            result = {"success": True, "key": "calibration", "cached_only": True}
        return {
            "ok": True,
            "result": self.to_jsonable(result),
            "calibration": self.to_jsonable(calibration),
        }

    def execution_status_summary(
        self,
        include_matrix: bool = True,
        include_plan: bool = True,
        include_droplets: bool = True,
        include_visualizers: bool = False,
        include_planning_job: bool = True,
        include_execution_wait: bool = True,
    ) -> Dict[str, Any]:
        """Return one compact status snapshot for normal agent decisions."""
        status = self.status(detail="compact")
        system_status = status.get("system") if isinstance(status, dict) else {}
        summary: Dict[str, Any] = {
            "surface": "execution_status_summary",
            "updated_at": time.time(),
            "runtime_mode": status.get("runtime_mode"),
            "last_error": status.get("last_error"),
            "system": system_status,
            "executor": status.get("executor"),
        }
        if include_plan:
            summary["plan"] = status.get("plan")
        if include_droplets:
            summary["droplets"] = status.get("droplets")
        if include_visualizers:
            summary["visualizers"] = status.get("visualizers")

        system_loaded = bool(
            isinstance(system_status, dict) and system_status.get("loaded")
        )
        if include_matrix:
            if system_loaded:
                try:
                    summary["matrix"] = self.matrix_summary(
                        source="state",
                        include_ranges=True,
                        include_active_cells=False,
                        include_hash=True,
                    )
                except Exception as exc:
                    summary["matrix"] = {"error": str(exc)}
            else:
                summary["matrix"] = {"available": False, "reason": "no_system_loaded"}

        if include_planning_job:
            try:
                planning_job = self.advanced_drop_job_status()
                summary["planning_job"] = self._compact_job_for_status_summary(
                    planning_job,
                    plan_included=include_plan,
                    droplets_included=include_droplets,
                )
            except Exception as exc:
                summary["planning_job"] = {"error": str(exc)}

        if include_execution_wait:
            try:
                summary["execution_wait"] = self.execution_wait_status()
            except Exception as exc:
                summary["execution_wait"] = {"error": str(exc)}

        return self.to_jsonable(summary)

    def _compact_job_for_status_summary(
        self,
        job: Optional[Dict[str, Any]],
        plan_included: bool = True,
        droplets_included: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Remove fields duplicated by execution_status_summary top-level sections."""
        if not isinstance(job, dict):
            return job
        compact = dict(job)
        if plan_included and "plan" in compact:
            compact.pop("plan", None)
            compact["plan_ref"] = "top_level_plan"
        if droplets_included and "droplets" in compact:
            compact.pop("droplets", None)
            compact["droplets_ref"] = "top_level_droplets"
        result = compact.get("result")
        if isinstance(result, dict):
            result = dict(result)
            if result.get("next_step") == compact.get("next_step"):
                result.pop("next_step", None)
            if result.get("visualizer_recovery") == {"needed": False}:
                result.pop("visualizer_recovery", None)
            compact["result"] = result
        if compact.get("completed") and compact.get("ok") and compact.get("result"):
            compact["result_ref"] = "planning_job_status"
            compact.pop("result", None)
        if compact.get("completed") and compact.get("ok") and compact.get("next_step"):
            compact["next_step"] = "execution complete; use top-level executor/plan/droplet state for the next decision."
        return compact

    def _resolve_state_path(self, state: Any, path: str) -> Any:
        """Resolve dotted dict keys, with numeric indexes for list-like values."""
        current = state
        full_path = str(path or "")
        for key in path.split("."):
            if isinstance(current, dict):
                if key not in current:
                    raise DropLogicMCPError(self._state_path_not_found_message(full_path, key))
                current = current[key]
                continue
            if isinstance(current, (list, tuple, np.ndarray)):
                try:
                    index = int(key)
                except ValueError as exc:
                    raise DropLogicMCPError(self._state_path_not_found_message(full_path, key)) from exc
                try:
                    current = current[index]
                except IndexError as exc:
                    raise DropLogicMCPError(f"State path index out of range: {path}") from exc
                continue
            raise DropLogicMCPError(self._state_path_not_found_message(full_path, key))
        return current

    def _state_path_not_found_message(self, path: str, missing_key: str) -> str:
        if path == "advanced_drop" or path.startswith("advanced_drop."):
            return (
                "State path not found: advanced_drop. AdvancedDrop is not part of system.state; "
                "use droplets_summary, plan_summary, executor_status, planning_job_status, "
                "or the planning primitive tools instead."
            )
        if missing_key == "advanced_drop":
            return (
                f"State path not found: {path}. AdvancedDrop is not exposed through read_state/state_summary; "
                "use droplets_summary, plan_summary, executor_status, or planning_job_status instead."
            )
        return f"State path not found: {path}"

    def _normalize_state_path(self, path: str) -> str:
        return ".".join(part for part in str(path or "").strip().split(".") if part)

    def _is_large_state_path(self, path: str) -> bool:
        return self._normalize_state_path(path) in self.LARGE_STATE_PATHS

    def _require_large_state_access(self, path: str) -> None:
        if self.allow_large_state_tools:
            return
        raise DropLogicMCPError(
            f"Raw access to large state path '{path}' is disabled. Restart the MCP server with "
            "--allow-large-state-tools only when the user explicitly needs the literal full matrix. "
            "Use matrix_summary() or state_summary(path='electrode_matrix.matrix') for normal agent work."
        )

    def _safe_state_for_agents(self, state: Dict[str, Any]) -> Dict[str, Any]:
        safe = {}
        for key, value in state.items():
            if key == "electrode_matrix" and isinstance(value, dict):
                matrix = value.get("matrix")
                safe_matrix = {
                    sub_key: self._summarize_state_value(sub_value)
                    for sub_key, sub_value in value.items()
                    if sub_key != "matrix"
                }
                if matrix is not None:
                    safe_matrix["matrix"] = self._matrix_compact_representation(
                        matrix,
                        source="state",
                        include_ranges=True,
                        include_active_cells=False,
                        include_hash=True,
                    )
                safe[key] = safe_matrix
                continue
            safe[str(key)] = self._summarize_state_value(value)
        return safe

    def _get_matrix_for_summary(self, source: str = "state") -> Any:
        source_key = (source or "state").strip().lower()
        system = self.require_system()
        if source_key in {"state", "current", "active"}:
            matrix = (system.state.get("electrode_matrix") or {}).get("matrix")
            if matrix is None:
                raise DropLogicMCPError("No electrode_matrix.matrix found in system.state.")
            return matrix
        if source_key in {"executor_last_frame", "last_frame"}:
            executor = self.require_executor()
            last_frame = getattr(executor, "last_frame", None)
            if isinstance(last_frame, dict):
                for key in ("matrix", "frame", "state"):
                    if last_frame.get(key) is not None:
                        return last_frame[key]
            if last_frame is not None and hasattr(last_frame, "matrix"):
                return getattr(last_frame, "matrix")
            raise DropLogicMCPError("Executor does not expose a last-frame matrix.")
        raise DropLogicMCPError("source must be 'state' or 'executor_last_frame'.")

    def _matrix_compact_representation(
        self,
        matrix: Any,
        source: str = "state",
        include_ranges: bool = True,
        include_active_cells: bool = False,
        active_cells_limit: int = 512,
        include_hash: bool = True,
    ) -> Dict[str, Any]:
        array = np.asarray(matrix)
        if array.ndim != 2:
            return {
                "type": "matrix_summary",
                "source": source,
                "shape": list(array.shape),
                "error": "matrix is not 2-dimensional",
            }

        active_mask = array != 0
        active_positions = np.argwhere(active_mask)
        active_count = int(active_positions.shape[0])
        result: Dict[str, Any] = {
            "type": "matrix_summary",
            "source": source,
            "shape": [int(array.shape[0]), int(array.shape[1])],
            "dtype": str(array.dtype),
            "active_count": active_count,
            "zero_count": int(array.size - active_count),
            "encoding": "active_ranges_by_row" if include_ranges else "summary",
            "zeros_are_implicit": True,
        }
        if include_hash:
            contiguous = np.ascontiguousarray(active_mask.astype(np.uint8))
            result["active_mask_sha256"] = hashlib.sha256(contiguous.tobytes()).hexdigest()
            try:
                value_bytes = np.ascontiguousarray(array).tobytes()
                result["matrix_values_sha256"] = hashlib.sha256(value_bytes).hexdigest()
            except Exception:
                pass

        if active_count == 0:
            if include_ranges:
                result["rows"] = {}
                result["values"] = {}
            if include_active_cells:
                result["active_cells"] = []
            return result

        rows = active_positions[:, 0]
        cols = active_positions[:, 1]
        result["active_bbox"] = {
            "row_min": int(rows.min()),
            "row_max": int(rows.max()),
            "col_min": int(cols.min()),
            "col_max": int(cols.max()),
        }

        if include_ranges:
            row_ranges: Dict[str, List[List[int]]] = {}
            for row_index in np.unique(rows):
                active_cols = np.flatnonzero(active_mask[int(row_index)])
                row_ranges[str(int(row_index))] = self._integer_ranges(active_cols)
            result["rows"] = row_ranges

            values: Dict[str, Dict[str, Any]] = {}
            value_counts: Dict[str, int] = {}
            for raw_value in np.unique(array[active_mask]):
                value_mask = array == raw_value
                positions = np.argwhere(value_mask)
                value_rows = positions[:, 0] if positions.size else []
                key = self._matrix_value_key(raw_value)
                value_counts[key] = int(positions.shape[0])
                ranges_by_row: Dict[str, List[List[int]]] = {}
                for row_index in np.unique(value_rows):
                    value_cols = np.flatnonzero(value_mask[int(row_index)])
                    ranges_by_row[str(int(row_index))] = self._integer_ranges(value_cols)
                values[key] = {
                    "count": int(positions.shape[0]),
                    "rows": ranges_by_row,
                }
            result["value_counts"] = value_counts
            result["values"] = values

        if include_active_cells:
            limit = max(0, int(active_cells_limit))
            cells = [[int(row), int(col)] for row, col in active_positions[:limit]]
            result["active_cells"] = cells
            result["active_cells_truncated"] = active_count > limit
            if active_count > limit:
                result["active_cells_total"] = active_count

        return result

    def _matrix_value_key(self, value: Any) -> str:
        try:
            number = float(value)
            if number.is_integer():
                return str(int(number))
        except Exception:
            pass
        return str(self.to_jsonable(value))

    def _integer_ranges(self, values: Iterable[int]) -> List[List[int]]:
        values = [int(value) for value in values]
        if not values:
            return []
        ranges: List[List[int]] = []
        start = previous = values[0]
        for value in values[1:]:
            if value == previous + 1:
                previous = value
                continue
            ranges.append([start, previous])
            start = previous = value
        ranges.append([start, previous])
        return ranges

    def context_status(self) -> Dict[str, Any]:
        """Return the active agent context summary."""
        status = self.context.status()
        status["runtime_mode"] = self._runtime_mode()
        return status

    def list_context_files(self) -> Dict[str, Any]:
        """Return the merged context file list."""
        return {
            "context": self.context.status(),
            "files": self.context.list_files(),
        }

    def read_context_file(self, path: str) -> Dict[str, Any]:
        """Read one agent context file."""
        return self.context.read_text(path)

    def capabilities(self) -> Dict[str, Any]:
        """Return the functions and observability surfaces available to agents."""
        system = self.system
        loaded_modules = {}
        if system is not None:
            for module_name, methods in sorted(self.MODULE_METHODS.items()):
                module = getattr(system, module_name, None)
                if module is None:
                    continue
                loaded_modules[module_name] = self._describe_methods(
                    module,
                    methods,
                    unsafe_pairs={
                        pair for pair in self.UNSAFE_MODULE_METHODS if pair[0] == module_name
                    },
                    module_name=module_name,
                )

        visualizers = {}
        if system is not None:
            for visualizer_name in ("matrix", "streamer"):
                instance = self._get_visualizer_instance(system, visualizer_name)
                visualizers[visualizer_name] = {
                    "available": instance is not None,
                    "methods": self._describe_methods(
                        instance,
                        self.VISUALIZER_METHODS.get(visualizer_name, set()),
                    ) if instance is not None else {},
                    "frame_sources": self._visualizer_frame_sources(instance),
                }

        return {
            "system_loaded": system is not None,
            "system": self.system_name,
            "runtime_mode": self._runtime_mode(),
            "context": self.context_status(),
            "advanced_drop": {
                "available": system is not None and hasattr(system, "advanced_drop"),
                "agent_interface": "planning_primitives",
                "raw_methods_exposed": bool(self.allow_unsafe_tools),
                "raw_methods": self.list_advanced_drop_methods()
                if (
                    self.allow_unsafe_tools
                    and system is not None
                    and hasattr(system, "advanced_drop")
                )
                else {},
            },
            "tool_categories": {
                "session": [
                    "load_system",
                    "close_system",
                    "restart_system",
                    "runtime_status",
                    "health_check",
                    "capabilities",
                    "emergency_stop",
                ],
                "context": [
                    "context_status",
                    "list_context_files",
                    "read_context_file",
                ],
                "state_observation": [
                    "state_summary",
                    "read_state",
                    "matrix_summary",
                    "execution_status_summary",
                    "execution_scene",
                ],
                "visualization": [
                    "prepare_visualizers",
                    "set_streamer_source",
                    "set_execution_view_mode",
                    "visualizer_status",
                    "start_visualizer",
                    "stop_visualizer",
                    "bring_visualizer_to_front",
                    "visualizer_frame",
                ],
                "stage_light_imaging": [
                    "move_stage",
                    "set_light_state",
                    "light_off",
                    "configure_microscope_imaging",
                    "capture_droplet_images",
                ],
                "temperature": [
                    "temperature_hold",
                    "start_temperature_routine",
                    "temperature_routine_status",
                    "cancel_temperature_routine",
                ],
                "droplets": [
                    "create_droplet",
                    "add_droplets",
                    "delete_droplet",
                    "update_droplet_target",
                    "update_droplet_targets",
                    "update_droplet_position",
                    "droplets_summary",
                ],
                "planning_primitives": [
                    "plan_activation_frame",
                    "plan_move",
                    "plan_reservoir_extraction",
                    "plan_isometric_split",
                    "plan_mix",
                    "plan_merge",
                    "planning_job_status",
                    "cancel_planning_job",
                    "plan_summary",
                    "save_protocol",
                ],
                "execution": [
                    "start_plan",
                    "set_execution_view_mode",
                    "pause_plan",
                    "resume_plan",
                    "stop_plan",
                    "executor_status",
                    "add_breakpoint",
                    "remove_breakpoint",
                    "clear_breakpoints",
                    "execute_segment_to_breakpoint",
                    "start_execute_until_breakpoint",
                    "execution_wait_status",
                    "cancel_execution_wait",
                ],
                "vision_feedback": [
                    "verify_droplets",
                    "detect_condensates",
                ],
                "low_level_debug": [
                    "list_system_modules",
                    "module_busy_status",
                    "module_call",
                ],
            },
            "planning_primitive_tools": [
                "plan_activation_frame",
                "plan_move",
                "plan_reservoir_extraction",
                "plan_isometric_split",
                "plan_mix",
                "plan_merge",
                "planning_job_status",
                "cancel_planning_job",
            ],
            "debug_tools": {
                "always_available": [
                    "list_system_modules",
                    "module_busy_status",
                    "module_call",
                ],
                "requires_allow_unsafe_tools": [
                    "set_system_state",
                    "system_call",
                    "list_advanced_drop_methods",
                    "advanced_drop_call",
                    "start_advanced_drop_call",
                    "advanced_drop_job_status",
                    "cancel_advanced_drop_job",
                ],
                "requires_allow_large_state_tools": [
                    "read_large_state",
                ],
            },
            "executor": {
                "available": system is not None and hasattr(getattr(system, "advanced_drop", None), "executor"),
                "methods": [
                    "start_plan",
                    "pause_plan",
                    "resume_plan",
                    "stop_plan",
                    "executor_status",
                    "add_breakpoint",
                    "remove_breakpoint",
                    "clear_breakpoints",
                    "execute_segment_to_breakpoint",
                    "start_execute_until_breakpoint",
                    "execution_wait_status",
                    "cancel_execution_wait",
                    "set_execution_view_mode",
                ],
            },
            "visualizers": visualizers,
            "visualizer_tools": [
                "prepare_visualizers",
                "set_streamer_source",
                "set_execution_view_mode",
                "visualizer_status",
                "start_visualizer",
                "stop_visualizer",
                "bring_visualizer_to_front",
                "visualizer_frame",
            ],
            "stage_tools": [
                "move_stage",
                "set_execution_view_mode",
            ],
            "imaging_tools": [
                "configure_microscope_imaging",
                "capture_droplet_images",
            ],
            "light_tools": [
                "set_light_state",
                "light_off",
            ],
            "temperature_tools": [
                "temperature_hold",
                "start_temperature_routine",
                "temperature_routine_status",
                "cancel_temperature_routine",
            ],
            "state_tools": {
                "safe_by_default": True,
                "large_state_paths_guarded": sorted(self.LARGE_STATE_PATHS),
                "tools": [
                    "state_summary",
                    "read_state",
                    "matrix_summary",
                    "execution_status_summary",
                    "execution_scene",
                ],
                "matrix_access": {
                    "default": "matrix_summary returns exact compact active_ranges_by_row",
                    "raw_requires_allow_large_state_tools": True,
                    "allow_large_state_tools": self.allow_large_state_tools,
                },
                "status_summary": {
                    "default": (
                        "execution_status_summary returns compact runtime, executor, "
                        "matrix, droplet, plan, planning-job, and execution-wait state "
                        "for normal agent decisions."
                    ),
                },
                "scene_access": {
                    "default": (
                        "execution_scene returns compact plan/executor/matrix/droplet state "
                        "for reasoning or external rendering; raw zeros are implicit."
                    ),
                    "dashboard_file_surface": bool(self.dashboard_scene_path),
                },
            },
            "system_methods": self._describe_methods(system, self.SYSTEM_METHODS)
            if system is not None
            else {},
            "modules": loaded_modules,
            "safety": {
                "allow_real_hardware": self.allow_real_hardware,
                "allow_unsafe_tools": self.allow_unsafe_tools,
                "allow_large_state_tools": self.allow_large_state_tools,
                "unsafe_module_methods_require_flag": [
                    f"{module}.{method}"
                    for module, method in sorted(self.UNSAFE_MODULE_METHODS)
                ],
                "not_exposed": [
                    "manufacturer/private hex command transport",
                    "electrode_matrix.send_ascii_command",
                ],
            },
        }

    def visualizer_snapshot(
        self,
        visualizer: str = "matrix",
        output_path: Optional[str] = None,
        image_format: str = "png",
        include_base64: bool = False,
    ) -> Dict[str, Any]:
        """Save and optionally return a visualizer snapshot."""
        system = self.require_system()
        frame = self._get_visualizer_frame(system, visualizer, "snapshot")
        if frame is None:
            raise DropLogicMCPError(f"No frame available for visualizer '{visualizer}'.")

        try:
            import cv2
        except Exception as exc:
            raise DropLogicMCPError("opencv-python is required for snapshots.") from exc

        image_format = (image_format or "png").lstrip(".").lower()
        if image_format not in {"png", "jpg", "jpeg"}:
            raise DropLogicMCPError("image_format must be png, jpg, or jpeg.")

        if output_path is None:
            os.makedirs(self.snapshots_dir, exist_ok=True)
            filename = (
                f"{self.session_id}_{visualizer}_{int(time.time() * 1000)}."
                f"{'jpg' if image_format == 'jpeg' else image_format}"
            )
            output_path = os.path.join(self.snapshots_dir, filename)
        else:
            output_path = os.path.abspath(os.fspath(output_path))
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

        ok = cv2.imwrite(output_path, frame)
        if not ok:
            raise DropLogicMCPError(f"Failed to write snapshot to {output_path}")

        result = {
            "visualizer": visualizer,
            "path": output_path,
            "shape": list(frame.shape),
            "format": image_format,
        }
        if include_base64:
            with open(output_path, "rb") as handle:
                result["base64"] = base64.b64encode(handle.read()).decode("ascii")
        return result

    def visualizer_frame(
        self,
        visualizer: str = "matrix",
        frame_source: str = "snapshot",
        image_format: str = "png",
        include_base64: bool = True,
        output_path: Optional[str] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a current visualizer frame as base64 and/or a saved image path."""
        system = self.require_system()
        frame = self._get_visualizer_frame(system, visualizer, frame_source)
        if frame is None:
            raise DropLogicMCPError(
                f"No {frame_source} frame available for visualizer '{visualizer}'."
            )

        try:
            import cv2
        except Exception as exc:
            raise DropLogicMCPError("opencv-python is required for frame encoding.") from exc

        frame = self._resize_frame(frame, max_width=max_width, max_height=max_height)
        image_format = (image_format or "png").lstrip(".").lower()
        if image_format not in {"png", "jpg", "jpeg"}:
            raise DropLogicMCPError("image_format must be png, jpg, or jpeg.")

        ext = "jpg" if image_format == "jpeg" else image_format
        encode_ext = f".{ext}"
        ok, encoded = cv2.imencode(encode_ext, frame)
        if not ok:
            raise DropLogicMCPError(f"Failed to encode visualizer frame as {ext}.")

        result = {
            "visualizer": visualizer,
            "frame_source": frame_source,
            "shape": list(frame.shape),
            "format": ext,
            "mime_type": "image/jpeg" if ext == "jpg" else "image/png",
        }

        if include_base64:
            result["base64"] = base64.b64encode(encoded.tobytes()).decode("ascii")

        if output_path:
            output_path = os.path.abspath(os.fspath(output_path))
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "wb") as handle:
                handle.write(encoded.tobytes())
            result["path"] = output_path

        return result

    def visualizer_status(self) -> Dict[str, Any]:
        """Return status for available visualizers."""
        system = self.require_system()
        status = {}
        for visualizer_name in ("matrix", "streamer"):
            instance = self._get_visualizer_instance(system, visualizer_name)
            if instance is None:
                status[visualizer_name] = {"available": False}
                continue
            item = {
                "available": True,
                "frame_sources": self._visualizer_frame_sources(instance),
                "window_name": getattr(instance, "window_name", None),
                "window_enabled": getattr(instance, "window_enabled", None),
                "window_mode": getattr(instance, "_window_mode", None),
                "headless_active": bool(getattr(instance, "_headless_active", False)),
                "display_active": bool(getattr(instance, "_display_active", False)),
                "last_exit_reason": getattr(instance, "last_exit_reason", None),
                "last_display_error": getattr(instance, "last_display_error", None),
            }
            window_name = item["window_name"]
            if window_name and item.get("window_enabled", True):
                item["os_window"] = get_window_status(window_name)
            for thread_name in ("thread", "capture_thread", "display_thread"):
                thread = getattr(instance, thread_name, None)
                if thread is not None and hasattr(thread, "is_alive"):
                    try:
                        item[f"{thread_name}_alive"] = bool(thread.is_alive())
                    except Exception as exc:
                        item[f"{thread_name}_alive"] = f"error: {exc}"
                else:
                    item[f"{thread_name}_alive"] = False
            for method_name in ("is_running", "requires_main_thread_window"):
                method = getattr(instance, method_name, None)
                if method is None:
                    continue
                try:
                    item[method_name] = bool(method())
                except Exception as exc:
                    item[method_name] = f"error: {exc}"
            if visualizer_name == "matrix":
                item["matrix_rotation"] = getattr(instance, "matrix_rotation_degrees", None)
                item["current_frame"] = getattr(instance, "current_frame", None)
            if visualizer_name == "streamer":
                item["source"] = self._streamer_source_name(system, instance)
                item["electrode_overlay"] = getattr(instance, "electrode_overlay", None)
                item["coordinates"] = getattr(instance, "coordinates", None)
                item["raw_frame_buffered"] = bool(getattr(instance, "raw_frame", None) is not None)
                item["processed_frame_buffered"] = bool(getattr(instance, "proc_frame", None) is not None)
                item["device"] = type(getattr(instance, "device", None)).__name__ if getattr(instance, "device", None) is not None else None
                item["droplet_detection_enabled"] = getattr(
                    instance, "droplet_detection_enabled", None
                )
                item["condensate_detection_enabled"] = getattr(
                    instance, "condensate_detection_enabled", None
                )
            status[visualizer_name] = self.to_jsonable(item)
        return status

    def prepare_visualizers(
        self,
        start_matrix: bool = True,
        start_streamer: bool = True,
        streamer_source: str = "microscope",
        streamer_coordinates: bool = False,
        streamer_electrode_overlay: bool = True,
        bring_to_front: bool = True,
        warmup_seconds: float = 1.0,
    ) -> Dict[str, Any]:
        """Configure and start run visualizers with BoxMini-safe defaults."""
        system = self.require_system()
        actions = []
        previous_auto_front = {}

        for visualizer_name in ("matrix", "streamer"):
            instance = self._get_visualizer_instance(system, visualizer_name)
            if instance is None or not hasattr(instance, "auto_bring_to_front"):
                continue
            previous_auto_front[visualizer_name] = instance.auto_bring_to_front
            instance.auto_bring_to_front = bool(bring_to_front)

        streamer = self._get_visualizer_instance(system, "streamer")
        try:
            if streamer is not None:
                source_name = self._normalize_streamer_source(streamer_source)
                device = None
                if source_name == "microscope":
                    device = getattr(system, "microscope", None)
                elif source_name == "camera":
                    device = getattr(system, "camera", None)

                if device is not None:
                    if hasattr(streamer, "set_device"):
                        streamer.set_device(device)
                    else:
                        streamer.device = device
                    actions.append(f"streamer_source={source_name}")
                else:
                    actions.append(f"streamer_source_missing={source_name}")

                try:
                    streamer.box = system
                except Exception:
                    pass
                if hasattr(streamer, "coordinates"):
                    streamer.coordinates = bool(streamer_coordinates)
                if hasattr(streamer, "electrode_overlay"):
                    streamer.electrode_overlay = bool(streamer_electrode_overlay)
                if hasattr(streamer, "record_movie"):
                    streamer.record_movie = False

            started = {}
            if start_matrix:
                try:
                    started["matrix"] = self.start_visualizer("matrix")
                except DropLogicMCPError as exc:
                    started["matrix"] = {"ok": False, "error": str(exc)}

            if start_streamer:
                try:
                    started["streamer"] = self.start_visualizer("streamer")
                except DropLogicMCPError as exc:
                    started["streamer"] = {"ok": False, "error": str(exc)}

            if warmup_seconds and warmup_seconds > 0:
                time.sleep(min(float(warmup_seconds), 5.0))

            brought_to_front = {}
            if bring_to_front:
                for visualizer_name in ("matrix", "streamer"):
                    try:
                        brought_to_front[visualizer_name] = self.bring_visualizer_to_front(
                            visualizer_name
                        )
                    except DropLogicMCPError as exc:
                        brought_to_front[visualizer_name] = {"ok": False, "error": str(exc)}

            return {
                "ok": True,
                "actions": actions,
                "started": started,
                "brought_to_front": brought_to_front,
                "status": self.visualizer_status(),
            }
        finally:
            for visualizer_name, auto_front in previous_auto_front.items():
                instance = self._get_visualizer_instance(system, visualizer_name)
                if instance is not None and hasattr(instance, "auto_bring_to_front"):
                    instance.auto_bring_to_front = auto_front

    def set_streamer_source(
        self,
        source: str = "microscope",
        electrode_overlay: Optional[bool] = None,
        coordinates: Optional[bool] = None,
        bring_to_front: bool = False,
    ) -> Dict[str, Any]:
        """Switch the live streamer visualizer between microscope and camera."""
        system = self.require_system()
        streamer = self._get_visualizer_instance(system, "streamer")
        if streamer is None:
            raise DropLogicMCPError("Streamer visualizer is not available.")

        source_name = self._normalize_streamer_source(source)
        device = getattr(system, source_name, None)
        if device is None:
            raise DropLogicMCPError(
                f"BoxMini {source_name} device is not available on the loaded system."
            )

        if hasattr(streamer, "set_device"):
            streamer.set_device(device)
        else:
            streamer.device = device


        try:
            streamer.box = system
        except Exception:
            pass

        if electrode_overlay is None:
            electrode_overlay = source_name == "microscope"
        if hasattr(streamer, "electrode_overlay"):
            streamer.electrode_overlay = bool(electrode_overlay)
        if coordinates is not None and hasattr(streamer, "coordinates"):
            streamer.coordinates = bool(coordinates)

        brought_to_front = None
        if bring_to_front:
            try:
                brought_to_front = self.bring_visualizer_to_front("streamer")
            except DropLogicMCPError as exc:
                brought_to_front = {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "visualizer": "streamer",
            "source": source_name,
            "electrode_overlay": getattr(streamer, "electrode_overlay", None),
            "coordinates": getattr(streamer, "coordinates", None),
            "brought_to_front": brought_to_front,
            "status": self.visualizer_status().get("streamer"),
        }

    def _validate_light_intensity(self, name: str, value: Any) -> int:
        try:
            intensity = int(value)
        except (TypeError, ValueError) as exc:
            raise DropLogicMCPError(f"{name} must be an integer from 0 to 99.") from exc
        if not 0 <= intensity <= 99:
            raise DropLogicMCPError(f"{name} must be between 0 and 99.")
        return intensity

    def _light_state_snapshot(self) -> Dict[str, Any]:
        system = self.require_system()
        state = getattr(system, "state", {}) or {}
        light_settings = state.get("light_settings", {}) if isinstance(state, dict) else {}
        module_state = None
        light = getattr(system, "light", None)
        get_state = getattr(light, "get_state", None)
        if get_state is not None:
            try:
                module_state = self.to_jsonable(get_state())
            except Exception as exc:
                module_state = {"error": str(exc)}
        return {
            "state": self.to_jsonable(light_settings),
            "module_state": module_state,
        }

    def set_light_state(
        self,
        light_on: Optional[bool] = None,
        coaxial_intensity: Optional[int] = None,
        ring_intensity: Optional[int] = None,
        wait_for_queue: bool = True,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Set BoxMini light master/coaxial/ring state through queued hardware paths."""
        system = self.require_system()
        state = getattr(system, "state", {}) or {}
        if not isinstance(state, dict) or "light_settings" not in state:
            raise DropLogicMCPError(
                "Loaded system has no light_settings state. Use this tool only on systems with a light module."
            )

        coaxial = None
        ring = None
        if coaxial_intensity is not None:
            coaxial = self._validate_light_intensity("coaxial_intensity", coaxial_intensity)
        if ring_intensity is not None:
            ring = self._validate_light_intensity("ring_intensity", ring_intensity)

        if light_on is None and ((coaxial is not None and coaxial > 0) or (ring is not None and ring > 0)):
            light_on = True
        if (
            light_on is None
            and coaxial is not None
            and ring is not None
            and coaxial == 0
            and ring == 0
        ):
            light_on = False
        if light_on is False:
            coaxial = 0
            ring = 0

        updates = []
        if light_on is True:
            updates.append(("light_settings.light_on", True))
        if coaxial is not None:
            updates.append(("light_settings.coaxial_intensity", coaxial))
        if ring is not None:
            updates.append(("light_settings.ring_intensity", ring))
        if light_on is False:
            updates.append(("light_settings.light_on", False))

        if not updates:
            return {
                "ok": True,
                "changed": False,
                "message": "No light settings were requested.",
                "light": self._light_state_snapshot(),
            }

        actions = []
        with self._lock:
            for path, value in updates:
                try:
                    result = system.update_state(path, value)
                    actions.append({
                        "path": path,
                        "value": value,
                        "ok": bool(result.get("success", True)) if isinstance(result, dict) else True,
                        "result": self.to_jsonable(result),
                    })
                except Exception as exc:
                    actions.append({
                        "path": path,
                        "value": value,
                        "ok": False,
                        "error": str(exc),
                    })

            queue_wait = None
            if wait_for_queue:
                queue_wait = self._wait_for_hardware_queue_empty(
                    timeout_seconds=queue_timeout_seconds,
                    poll_interval=0.05,
                )

        ok = all(action.get("ok", True) is not False for action in actions)
        if queue_wait is not None:
            ok = ok and bool(queue_wait.get("ok"))

        return {
            "ok": ok,
            "changed": True,
            "actions": actions,
            "wait_for_hardware_queue": queue_wait,
            "light": self._light_state_snapshot(),
        }

    def light_off(
        self,
        wait_for_queue: bool = True,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Turn all BoxMini illumination off: coaxial=0, ring=0, master=false."""
        return self.set_light_state(
            light_on=False,
            coaxial_intensity=0,
            ring_intensity=0,
            wait_for_queue=wait_for_queue,
            queue_timeout_seconds=queue_timeout_seconds,
        )

    def configure_microscope_imaging(
        self,
        channel: str = "Brightfield",
        exposure_time: int = 72000,
        gain: int = 0,
        coaxial_intensity: int = 4,
        ring_intensity: int = 0,
        auto_exposure: bool = False,
        restart_streamer: bool = True,
        bring_to_front: bool = False,
        stabilization_wait: float = 0.5,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Safely configure microscope channel, exposure, gain and light for live imaging."""
        system = self.require_system()
        actions = []
        streamer = self._get_visualizer_instance(system, "streamer")
        streamer_was_running = False

        if streamer is not None and hasattr(streamer, "is_running"):
            try:
                streamer_was_running = bool(streamer.is_running())
            except Exception:
                streamer_was_running = False

        if streamer_was_running and hasattr(streamer, "stop"):
            try:
                streamer.stop()
                actions.append({"stop_visualizer": "streamer", "ok": True})
            except Exception as exc:
                actions.append({"stop_visualizer": "streamer", "ok": False, "error": str(exc)})

        updates = []
        if int(coaxial_intensity) > 0 or int(ring_intensity) > 0:
            updates.append(("light_settings.light_on", True))
        updates.extend([
            ("microscope_settings.current_channel", channel),
            ("microscope_settings.auto_exposure", bool(auto_exposure)),
            ("microscope_settings.exposure_time", int(exposure_time)),
            ("microscope_settings.gain", int(gain)),
            ("light_settings.coaxial_intensity", int(coaxial_intensity)),
            ("light_settings.ring_intensity", int(ring_intensity)),
        ])
        for path, value in updates:
            try:
                actions.append({"update_state": path, "result": system.update_state(path, value)})
            except Exception as exc:
                actions.append({"update_state": path, "ok": False, "error": str(exc)})

        queue_wait = self._wait_for_hardware_queue_empty(
            timeout_seconds=queue_timeout_seconds,
            poll_interval=0.05,
        )
        actions.append({"wait_for_hardware_queue": queue_wait})

        if stabilization_wait and stabilization_wait > 0:
            time.sleep(min(float(stabilization_wait), 10.0))

        streamer_result = None
        if restart_streamer:
            try:
                streamer_result = self.set_streamer_source(
                    source="microscope",
                    electrode_overlay=True,
                    bring_to_front=bring_to_front,
                )
                actions.append({"set_streamer_source": streamer_result})
                if streamer_was_running or streamer is not None:
                    start_result = self.start_visualizer("streamer")
                    actions.append({"start_visualizer": start_result})
            except Exception as exc:
                actions.append({"restart_streamer": {"ok": False, "error": str(exc)}})

        return {
            "ok": all(action.get("ok", True) is not False for action in actions),
            "channel": channel,
            "exposure_time": int(exposure_time),
            "gain": int(gain),
            "coaxial_intensity": int(coaxial_intensity),
            "ring_intensity": int(ring_intensity),
            "auto_exposure": bool(auto_exposure),
            "streamer_was_running": streamer_was_running,
            "actions": self.to_jsonable(actions),
            "visualizers": self.visualizer_status(),
        }

    def configure_camera_imaging(
        self,
        exposure_time: int = 72000,
        gain: int = 0,
        auto_exposure: bool = False,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Safely configure the primary camera exposure/gain state."""
        system = self.require_system()
        actions = []
        updates = [
            ("camera_settings.auto_exposure", bool(auto_exposure)),
            ("camera_settings.exposure_time", int(exposure_time)),
            ("camera_settings.gain", int(gain)),
        ]
        for path, value in updates:
            try:
                actions.append({"update_state": path, "result": system.update_state(path, value)})
            except Exception as exc:
                actions.append({"update_state": path, "ok": False, "error": str(exc)})

        queue_wait = self._wait_for_hardware_queue_empty(
            timeout_seconds=queue_timeout_seconds,
            poll_interval=0.05,
        )
        actions.append({"wait_for_hardware_queue": queue_wait})
        return {
            "ok": all(action.get("ok", True) is not False for action in actions),
            "exposure_time": int(exposure_time),
            "gain": int(gain),
            "auto_exposure": bool(auto_exposure),
            "actions": self.to_jsonable(actions),
        }

    def capture_droplet_images(
        self,
        droplet_ids: Optional[List[int]] = None,
        channels: Optional[List[Any]] = None,
        output_dir: Optional[str] = None,
        temperature_label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        capture_source: str = "streamer",
        restart_streamer: bool = True,
        restore_low_light: bool = True,
        image_format: str = "png",
        wait_before_check: float = 0.5,
        wait_after_check: float = 0.5,
    ) -> Dict[str, Any]:
        """Move to droplets and save images for one or more channel profiles."""
        system = self.require_system()
        advanced_drop = self.require_advanced_drop()

        capture_source = (capture_source or "streamer").lower()
        if capture_source not in {"pause_streamer", "streamer"}:
            raise DropLogicMCPError("capture_source must be 'pause_streamer' or 'streamer'.")

        ext = (image_format or "png").lstrip(".").lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext not in {"png", "jpg"}:
            raise DropLogicMCPError("image_format must be png, jpg, or jpeg.")

        if droplet_ids is None:
            droplet_ids = [
                int(droplet.id)
                for droplet in advanced_drop.droplets
                if hasattr(droplet, "id")
            ]
        droplet_ids = [int(droplet_id) for droplet_id in droplet_ids]
        if not droplet_ids:
            raise DropLogicMCPError("capture_droplet_images requires at least one droplet id.")

        channel_profiles = self._normalize_imaging_channels(channels)
        if not channel_profiles:
            raise DropLogicMCPError("capture_droplet_images requires at least one channel.")

        if output_dir is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.abspath(os.path.join("results", f"droplet_imaging_{stamp}"))
        else:
            output_dir = os.path.abspath(os.fspath(output_dir))
        os.makedirs(output_dir, exist_ok=True)

        streamer = self._get_visualizer_instance(system, "streamer")
        streamer_was_running = False
        if streamer is not None and hasattr(streamer, "is_running"):
            try:
                streamer_was_running = bool(streamer.is_running())
            except Exception:
                streamer_was_running = False

        stopped_streamer = False
        if capture_source == "pause_streamer" and streamer is not None and hasattr(streamer, "stop"):
            try:
                streamer.stop()
                stopped_streamer = True
            except Exception as exc:
                raise DropLogicMCPError(
                    "Could not stop streamer before direct/full-resolution capture: "
                    f"{exc}"
                ) from exc
        elif capture_source == "streamer":
            try:
                self.set_streamer_source(
                    source="microscope",
                    electrode_overlay=True,
                    bring_to_front=False,
                )
                if streamer is not None:
                    self.start_visualizer("streamer")
            except Exception as exc:
                raise DropLogicMCPError(
                    "Could not prepare streamer before batch image capture: "
                    f"{exc}"
                ) from exc

        captures = []
        errors = []
        started_at = datetime.now().isoformat()
        try:
            for droplet_id in droplet_ids:
                droplet_entry = {
                    "droplet_id": droplet_id,
                    "moved": False,
                    "captures": [],
                    "errors": [],
                }
                try:
                    moved = advanced_drop.move_to_droplet_center(
                        droplet_id,
                        wait_before_check=wait_before_check,
                        wait_after_check=wait_after_check,
                    )
                    droplet_entry["moved"] = bool(moved)
                    if not moved:
                        droplet_entry["errors"].append("move_to_droplet_center returned false")
                except Exception as exc:
                    droplet_entry["errors"].append(f"move_to_droplet_center failed: {exc}")
                    errors.append({"droplet_id": droplet_id, "error": str(exc)})
                    captures.append(droplet_entry)
                    continue

                for profile in channel_profiles:
                    channel_name = profile["channel"]
                    safe_channel = "".join(
                        char if char.isalnum() or char in ("-", "_") else "_"
                        for char in channel_name
                    )
                    tag_parts = []
                    if temperature_label:
                        tag_parts.append(str(temperature_label))
                    if profile.get("label"):
                        tag_parts.append(str(profile["label"]))
                    tag = "_".join(tag_parts)
                    filename_parts = [f"droplet{droplet_id:03d}", safe_channel]
                    if tag:
                        filename_parts.append(tag)
                    filename_parts.append(datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
                    droplet_dir = os.path.join(output_dir, f"droplet{droplet_id:03d}", safe_channel)
                    os.makedirs(droplet_dir, exist_ok=True)
                    image_path = os.path.join(droplet_dir, "_".join(filename_parts) + f".{ext}")

                    try:
                        frame = capture_channel_frame(
                            system,
                            channel=channel_name,
                            exposure_time=int(profile["exposure_time"]),
                            gain=int(profile.get("gain", 12)),
                            coaxial_intensity=int(profile.get("coaxial_intensity", 0)),
                            ring_intensity=int(profile.get("ring_intensity", 0)),
                            frame_wait=float(profile.get("frame_wait", 0.2)),
                            timeout_per_frame=float(profile.get("timeout_per_frame", 10.0)),
                            mode=str(profile.get("mode", "brightfield")),
                            use_streamer=(capture_source == "streamer"),
                            queue_timeout=float(profile.get("queue_timeout", 10.0)),
                        )
                        if frame is None or getattr(frame, "size", 0) == 0:
                            raise RuntimeError("capture returned an empty frame")
                        settings_snapshot = snapshot_capture_settings(system)
                        ok = cv2.imwrite(image_path, frame)
                        if not ok:
                            raise RuntimeError(f"cv2.imwrite returned false for {image_path}")
                        droplet_entry["captures"].append(
                            {
                                "channel": channel_name,
                                "path": image_path,
                                "shape": list(getattr(frame, "shape", [])),
                                "profile": self.to_jsonable(profile),
                                "settings_snapshot": self.to_jsonable(settings_snapshot),
                            }
                        )
                    except Exception as exc:
                        error = {
                            "droplet_id": droplet_id,
                            "channel": channel_name,
                            "error": str(exc),
                        }
                        droplet_entry["errors"].append(error)
                        errors.append(error)

                if restore_low_light:
                    try:
                        system.update_state("light_settings.coaxial_intensity", 0)
                        system.update_state("light_settings.ring_intensity", 0)
                        system.update_state("light_settings.light_on", False)
                        self._wait_for_hardware_queue_empty(
                            timeout_seconds=10.0,
                            poll_interval=0.05,
                        )
                    except Exception:
                        pass

                captures.append(droplet_entry)
        finally:
            if restore_low_light:
                try:
                    system.update_state("light_settings.coaxial_intensity", 0)
                    system.update_state("light_settings.ring_intensity", 0)
                    system.update_state("light_settings.light_on", False)
                    self._wait_for_hardware_queue_empty(
                        timeout_seconds=10.0,
                        poll_interval=0.05,
                    )
                except Exception:
                    pass
            if restart_streamer and (streamer_was_running or stopped_streamer):
                try:
                    self.set_streamer_source(
                        source="microscope",
                        electrode_overlay=True,
                        bring_to_front=False,
                    )
                    self.start_visualizer("streamer")
                except Exception as exc:
                    errors.append({"scope": "restart_streamer", "error": str(exc)})

        payload = {
            "ok": not errors,
            "output_dir": output_dir,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "temperature_label": temperature_label,
            "metadata": self.to_jsonable(metadata or {}),
            "capture_source": capture_source,
            "streamer_was_running": streamer_was_running,
            "streamer_stopped_for_capture": stopped_streamer,
            "channels": self.to_jsonable(channel_profiles),
            "captures": self.to_jsonable(captures),
            "errors": self.to_jsonable(errors),
        }

        metadata_path = os.path.join(output_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        payload["metadata_path"] = metadata_path
        return payload

    def temperature_hold(
        self,
        target_c: float,
        hold_seconds: float,
        tolerance_c: float = 0.5,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = False,
        max_samples: int = 20,
    ) -> Dict[str, Any]:
        """Set temperature and optionally wait/hold with compact sampling."""
        result = self._temperature_hold_impl(
            target_c=target_c,
            hold_seconds=hold_seconds,
            tolerance_c=tolerance_c,
            settle_timeout_seconds=settle_timeout_seconds,
            sample_interval_seconds=sample_interval_seconds,
            require_settle=require_settle,
            max_samples=max_samples,
        )
        return self.to_jsonable(result)

    def temperature_sweep(
        self,
        steps: List[Dict[str, Any]],
        tolerance_c: float = 0.5,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = False,
        max_samples_per_step: int = 20,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Run a list of temperature hold steps with compact results."""
        if not isinstance(steps, list) or not steps:
            raise DropLogicMCPError("temperature_sweep expects a non-empty list of steps.")

        results = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                item = {"index": index, "ok": False, "error": "step must be an object"}
                results.append(item)
                if stop_on_error:
                    break
                continue

            target = step.get("target_c", step.get("target", step.get("temperature")))
            hold = step.get("hold_seconds", step.get("duration_seconds", step.get("hold", 0)))
            if target is None:
                item = {"index": index, "ok": False, "error": "missing target_c"}
                results.append(item)
                if stop_on_error:
                    break
                continue

            item = self._temperature_hold_impl(
                target_c=float(target),
                hold_seconds=float(hold or 0),
                tolerance_c=float(step.get("tolerance_c", tolerance_c)),
                settle_timeout_seconds=float(step.get("settle_timeout_seconds", settle_timeout_seconds)),
                sample_interval_seconds=float(step.get("sample_interval_seconds", sample_interval_seconds)),
                require_settle=bool(step.get("require_settle", require_settle)),
                max_samples=int(step.get("max_samples", max_samples_per_step)),
            )
            item["index"] = index
            results.append(item)
            if stop_on_error and not item.get("ok"):
                break

        return {
            "ok": all(item.get("ok") for item in results),
            "requested_steps": len(steps),
            "completed_steps": sum(1 for item in results if item.get("ok")),
            "results": self.to_jsonable(results),
        }

    def start_temperature_routine(
        self,
        steps: List[Dict[str, Any]],
        tolerance_c: float = 0.5,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = True,
        max_samples_per_step: int = 20,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Start a background temperature routine and return immediately."""
        normalized_steps = self._normalize_temperature_steps(
            steps=steps,
            tolerance_c=tolerance_c,
            settle_timeout_seconds=settle_timeout_seconds,
            sample_interval_seconds=sample_interval_seconds,
            require_settle=require_settle,
            max_samples_per_step=max_samples_per_step,
        )

        with self._temperature_routine_lock:
            if (
                self._temperature_routine_thread is not None
                and self._temperature_routine_thread.is_alive()
            ):
                status = self.temperature_routine_status()
                raise DropLogicMCPError(
                    "A temperature routine is already running. "
                    f"Current routine id: {status.get('routine_id')}. "
                    "Call temperature_routine_status() or cancel_temperature_routine()."
                )

            routine_id = uuid.uuid4().hex[:12]
            self._temperature_routine_stop_event.clear()
            self._temperature_routine_status = {
                "routine_id": routine_id,
                "running": True,
                "completed": False,
                "cancel_requested": False,
                "ok": None,
                "started_at": time.time(),
                "finished_at": None,
                "requested_steps": len(normalized_steps),
                "current_step_index": 0,
                "completed_steps": 0,
                "active_step": None,
                "results": [],
                "last_sample": None,
                "error": None,
            }
            self._temperature_routine_thread = threading.Thread(
                target=self._run_temperature_routine,
                args=(routine_id, normalized_steps, bool(stop_on_error)),
                name=f"DropLogicTemperatureRoutine-{routine_id}",
                daemon=True,
            )
            self._temperature_routine_thread.start()
            return self.temperature_routine_status()

    def temperature_routine_status(self) -> Dict[str, Any]:
        """Return compact status for the active or last temperature routine."""
        with self._temperature_routine_lock:
            status = dict(self._temperature_routine_status or {})
            if not status:
                return {
                    "running": False,
                    "completed": False,
                    "thread_alive": False,
                    "message": "No temperature routine has been started in this runtime.",
                }
            thread = self._temperature_routine_thread
            status["thread_alive"] = bool(thread is not None and thread.is_alive())
            return self.to_jsonable(status)

    def cancel_temperature_routine(self) -> Dict[str, Any]:
        """Ask the background temperature routine to stop after its current poll."""
        with self._temperature_routine_lock:
            if self._temperature_routine_status is None:
                return {
                    "ok": True,
                    "cancel_requested": False,
                    "message": "No temperature routine is active.",
                }
            self._temperature_routine_stop_event.set()
            self._temperature_routine_status["cancel_requested"] = True
            return self.temperature_routine_status()

    def visualizer_call(
        self,
        visualizer: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a whitelisted visualizer method."""
        visualizer_key = self._normalize_visualizer_name(visualizer)
        allowed_methods = self.VISUALIZER_METHODS.get(visualizer_key, set())
        if method not in allowed_methods:
            raise DropLogicMCPError(
                f"Visualizer method '{visualizer}.{method}' is not exposed through MCP. "
                f"Allowed methods: {sorted(allowed_methods)}"
            )
        instance = self._get_visualizer_instance(self.require_system(), visualizer_key)
        if instance is None:
            raise DropLogicMCPError(f"Visualizer '{visualizer}' is not available.")
        func = getattr(instance, method, None)
        if func is None:
            raise DropLogicMCPError(f"Visualizer '{visualizer}' has no method '{method}'.")
        result = func(**(arguments or {}))
        return {
            "visualizer": visualizer_key,
            "method": method,
            "result": self.to_jsonable(result),
            "status": self.visualizer_status().get(visualizer_key),
        }

    def start_visualizer(self, visualizer: str = "matrix") -> Dict[str, Any]:
        """Start a visualizer window when the host platform supports it."""
        instance = self._get_visualizer_instance(self.require_system(), visualizer)
        if instance is None or not hasattr(instance, "start"):
            raise DropLogicMCPError(f"Visualizer '{visualizer}' is not available.")
        previous_auto_front = getattr(instance, "auto_bring_to_front", None)
        if previous_auto_front is not None:
            instance.auto_bring_to_front = False
        try:
            instance.start()
        finally:
            if previous_auto_front is not None:
                instance.auto_bring_to_front = previous_auto_front
        return {
            "ok": True,
            "visualizer": self._normalize_visualizer_name(visualizer),
            "started": True,
            "status": self.visualizer_status().get(self._normalize_visualizer_name(visualizer)),
        }

    def stop_visualizer(self, visualizer: str = "matrix") -> Dict[str, Any]:
        """Stop a visualizer window."""
        instance = self._get_visualizer_instance(self.require_system(), visualizer)
        if instance is None or not hasattr(instance, "stop"):
            raise DropLogicMCPError(f"Visualizer '{visualizer}' is not available.")
        instance.stop()
        return {
            "ok": True,
            "visualizer": self._normalize_visualizer_name(visualizer),
            "stopped": True,
            "status": self.visualizer_status().get(self._normalize_visualizer_name(visualizer)),
        }

    def _visualizer_running_safely(self, visualizer: str) -> bool:
        try:
            instance = self._get_visualizer_instance(self.require_system(), visualizer)
            if instance is None:
                return False
            method = getattr(instance, "is_running", None)
            if method is not None:
                return bool(method())
            thread = getattr(instance, "thread", None)
            return bool(thread is not None and thread.is_alive())
        except Exception:
            return False

    def _recover_visualizer_if_needed(
        self,
        visualizer: str,
        was_running: bool,
    ) -> Optional[Dict[str, Any]]:
        if not was_running:
            return None
        if self._visualizer_running_safely(visualizer):
            return {"needed": False}
        try:
            restarted = self.start_visualizer(visualizer)
            return {
                "needed": True,
                "restarted": True,
                "status": restarted.get("status"),
            }
        except Exception as exc:
            return {
                "needed": True,
                "restarted": False,
                "error": str(exc),
            }

    def bring_visualizer_to_front(self, visualizer: str = "streamer") -> Dict[str, Any]:
        """Bring a visualizer window to the foreground when the host OS allows it."""
        visualizer_key = self._normalize_visualizer_name(visualizer)
        instance = self._get_visualizer_instance(self.require_system(), visualizer_key)
        if instance is None:
            raise DropLogicMCPError(f"Visualizer '{visualizer}' is not available.")

        func = getattr(instance, "bring_to_front", None) or getattr(
            instance, "_bring_to_front", None
        )
        if func is None:
            raise DropLogicMCPError(
                f"Visualizer '{visualizer}' does not support bring_to_front."
            )

        result = func()
        return {
            "ok": True,
            "visualizer": visualizer_key,
            "result": self.to_jsonable(result),
            "status": self.visualizer_status().get(visualizer_key),
        }

    # ---------------------------------------------------------------------
    # Droplet and planning API

    def create_droplet(
        self,
        droplet_id: int,
        origin: Iterable[int],
        target: Optional[Iterable[int]] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        shape: Optional[Iterable[Iterable[int]]] = None,
        priority: int = 0,
        vital_space: int = 1,
    ) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        origin_tuple = self._pair(origin, "origin")
        target_tuple = self._pair(target if target is not None else origin, "target")
        shape_value = self._shape(shape) if shape is not None else None

        with self._lock:
            droplet = advanced_drop.droplets.create_droplet(
                droplet_id=droplet_id,
                origin=origin_tuple,
                target=target_tuple,
                width=width,
                height=height,
                shape=shape_value,
                priority=priority,
                vital_space=vital_space,
            )
            return {
                "droplet": self.to_jsonable(droplet),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
                "plan": self.plan_summary(advanced_drop.plan),
            }

    def add_droplets(self, droplets: List[Dict[str, Any]]) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        normalized = []
        errors = []
        if not isinstance(droplets, list):
            raise DropLogicMCPError(
                "add_droplets expects a list of droplet objects. "
                "Each object needs id or droplet_id plus origin=[row, col]; "
                "include target=[row, col] for planned moves."
            )

        existing_ids = {
            int(droplet.id)
            for droplet in advanced_drop.droplets
            if hasattr(droplet, "id")
        }
        seen_ids = set()

        for index, item in enumerate(droplets):
            if not isinstance(item, dict):
                errors.append(
                    {
                        "index": index,
                        "error": "droplet entry must be an object",
                        "received_type": type(item).__name__,
                    }
                )
                continue

            payload = dict(item)
            if "id" not in payload:
                if "droplet_id" in payload:
                    payload["id"] = payload.pop("droplet_id")
                else:
                    errors.append(
                        {
                            "index": index,
                            "error": "missing required field 'id' or 'droplet_id'",
                        }
                    )
                    continue

            try:
                droplet_id = int(payload["id"])
            except Exception:
                errors.append(
                    {
                        "index": index,
                        "error": "id must be an integer",
                        "value": self.to_jsonable(payload.get("id")),
                    }
                )
                continue

            if droplet_id in existing_ids or droplet_id in seen_ids:
                errors.append(
                    {
                        "index": index,
                        "id": droplet_id,
                        "error": "duplicate droplet id",
                    }
                )
                continue

            if "origin" not in payload:
                errors.append(
                    {
                        "index": index,
                        "id": droplet_id,
                        "error": "missing required field 'origin'",
                    }
                )
                continue

            try:
                payload["id"] = droplet_id
                payload["origin"] = self._pair(payload["origin"], f"droplets[{index}].origin")
                target_value = payload["origin"] if payload.get("target") is None else payload["target"]
                payload["target"] = self._pair(
                    target_value,
                    f"droplets[{index}].target",
                )
                if payload.get("shape") is not None:
                    payload["shape"] = self._shape(payload["shape"])
                normalized.append(payload)
                seen_ids.add(droplet_id)
            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "id": droplet_id,
                        "error": str(exc),
                    }
                )

        if errors:
            raise DropLogicMCPError(
                "Invalid add_droplets payload: "
                + json.dumps(errors, ensure_ascii=False)
            )

        with self._lock:
            created = advanced_drop.droplets.add_droplets(normalized)
            if len(created) != len(normalized):
                created_ids = {
                    int(droplet.id)
                    for droplet in created
                    if hasattr(droplet, "id")
                }
                missing_ids = [
                    payload["id"]
                    for payload in normalized
                    if payload["id"] not in created_ids
                ]
                raise DropLogicMCPError(
                    "AdvancedDrop failed to create all requested droplets. "
                    f"requested={len(normalized)}, created={len(created)}, "
                    f"missing_ids={missing_ids}. Use id/droplet_id, origin, "
                    "target, width/height or shape."
                )
            return {
                "ok": True,
                "requested_count": len(normalized),
                "created_count": len(created),
                "created_ids": [droplet.id for droplet in created],
                "created": self.to_jsonable(created),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
                "plan": self.plan_summary(advanced_drop.plan),
            }

    def delete_droplet(
        self,
        droplet_id: int,
        persist_electrodes: bool = False,
    ) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        with self._lock:
            deleted = advanced_drop.droplets.delete_droplet(
                droplet_id,
                persist_electrodes=bool(persist_electrodes),
            )
            return {
                "deleted": bool(deleted),
                "persist_electrodes": bool(persist_electrodes),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
                "plan": self.plan_summary(advanced_drop.plan),
            }

    def update_droplet_target(
        self, droplet_id: int, target: Iterable[int]
    ) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        with self._lock:
            updated = advanced_drop.droplets.update_droplet_target(
                droplet_id, self._pair(target, "target")
            )
            return {
                "updated": bool(updated),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
            }

    def update_droplet_targets(
        self,
        targets: Any,
        include_summary: bool = False,
    ) -> Dict[str, Any]:
        """Update many droplet targets in one compact MCP response."""
        advanced_drop = self.require_advanced_drop()
        normalized = []
        errors = []

        if isinstance(targets, dict):
            iterator = targets.items()
            for raw_id, raw_target in iterator:
                try:
                    normalized.append(
                        {
                            "droplet_id": int(raw_id),
                            "target": self._pair(raw_target, f"target for droplet {raw_id}"),
                        }
                    )
                except Exception as exc:
                    errors.append(
                        {
                            "droplet_id": self.to_jsonable(raw_id),
                            "error": str(exc),
                        }
                    )
        elif isinstance(targets, list):
            for index, item in enumerate(targets):
                if not isinstance(item, dict):
                    errors.append(
                        {
                            "index": index,
                            "error": "target entry must be an object with id/droplet_id and target",
                        }
                    )
                    continue
                raw_id = item.get("id", item.get("droplet_id"))
                raw_target = item.get("target")
                if raw_id is None:
                    errors.append({"index": index, "error": "missing id or droplet_id"})
                    continue
                if raw_target is None:
                    errors.append({"index": index, "droplet_id": raw_id, "error": "missing target"})
                    continue
                try:
                    normalized.append(
                        {
                            "droplet_id": int(raw_id),
                            "target": self._pair(raw_target, f"target for droplet {raw_id}"),
                        }
                    )
                except Exception as exc:
                    errors.append(
                        {
                            "index": index,
                            "droplet_id": self.to_jsonable(raw_id),
                            "error": str(exc),
                        }
                    )
        else:
            raise DropLogicMCPError(
                "update_droplet_targets expects either a list of "
                "{id|droplet_id, target} objects or a mapping of id -> target."
            )

        updated = []
        not_found = []
        with self._lock:
            for item in normalized:
                droplet_id = item["droplet_id"]
                target = item["target"]
                ok = advanced_drop.droplets.update_droplet_target(droplet_id, target)
                if ok:
                    updated.append({"id": droplet_id, "target": target})
                else:
                    not_found.append(droplet_id)

            result = {
                "ok": not errors and not not_found,
                "requested_count": len(normalized) + len(errors),
                "valid_count": len(normalized),
                "updated_count": len(updated),
                "updated_ids": [item["id"] for item in updated],
                "not_found_ids": not_found,
                "errors": errors,
            }
            if include_summary:
                summary = advanced_drop.droplets.get_droplets_summary()
                result["droplets"] = {
                    "total_droplets": summary.get("total_droplets"),
                    "has_plan": summary.get("has_plan"),
                }
                result["plan"] = self.plan_summary(advanced_drop.plan)
            return self.to_jsonable(result)

    def update_droplet_position(
        self, droplet_id: int, position: Iterable[int]
    ) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        position_pair = self._pair(position, "position")
        with self._lock:
            if hasattr(advanced_drop, "correct_droplet_position"):
                advanced_drop.correct_droplet_position(int(droplet_id), position_pair)
                droplet = advanced_drop.droplets.get_droplet(int(droplet_id))
                updated = droplet is not None and tuple(getattr(droplet, "origin_corner", ())) == tuple(position_pair)
            else:
                updated = advanced_drop.droplets.update_droplet_position(
                    droplet_id, position_pair
                )
            if updated:
                try:
                    self.write_dashboard_scene_snapshot()
                except Exception:
                    pass
            return {
                "updated": bool(updated),
                "position": self.to_jsonable(position_pair),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
                "plan": self.plan_summary(advanced_drop.plan),
            }

    def trim_plan_tail(self, keep_frames: int) -> Dict[str, Any]:
        """Delete planned frames after keep_frames without crossing executed frames."""
        advanced_drop = self.require_advanced_drop()

        with self._lock:
            try:
                result = advanced_drop.trim_plan_tail(int(keep_frames))
            except (ValueError, RuntimeError) as exc:
                raise DropLogicMCPError(str(exc)) from exc
            plan = result.get("plan", getattr(advanced_drop, "plan", None))
            executor_status = self.to_jsonable(result.get("executor_status") or {})
            try:
                self.write_dashboard_scene_snapshot()
            except Exception:
                pass

            return {
                "ok": True,
                "trimmed": bool(result.get("trimmed")),
                "keep_frames": int(result.get("keep_frames") or 0),
                "removed_frames": int(result.get("removed_frames") or 0),
                "protected_frames": int(result.get("protected_frames") or 0),
                "plan": self.plan_summary(plan),
                "executor": self._compact_executor_status(executor_status),
            }

    def droplets_summary(self) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        return self.to_jsonable(advanced_drop.droplets.get_droplets_summary())

    def _plan_advanced_drop_primitive(
        self,
        primitive: str,
        arguments: Optional[Dict[str, Any]] = None,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan one named AdvancedDrop primitive without executing hardware."""
        arguments = dict(arguments or {})
        arguments.pop("background", None)
        if background:
            result = self.start_advanced_drop_call(primitive, arguments)
            result["primitive"] = primitive
            result["background"] = True
            return result

        result = self.advanced_drop_call(primitive, arguments)
        result["primitive"] = primitive
        result["background"] = False
        return result

    def plan_activation_frame(
        self,
        event_type: str = "activation",
        event_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append one activation frame for current droplets; does not execute hardware."""
        return self._plan_advanced_drop_primitive(
            "push_frame",
            {
                "event_type": event_type,
                "event_data": event_data or {},
            },
            background=False,
        )

    def plan_move(
        self,
        mode: str = "sipp",
        remove_duplicate_frames: bool = False,
        planning_timeout: Optional[float] = None,
        background: bool = False,
        allow_long_sync: bool = False,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Plan movement for current droplet targets; does not execute hardware."""
        planner_options, ignored_options = self._sanitize_plan_move_options(
            options=options,
            extra=kwargs,
        )
        arguments = {
            "mode": mode,
            "remove_duplicate_frames": bool(remove_duplicate_frames),
            "allow_long_sync": bool(allow_long_sync),
            **planner_options,
        }
        if planning_timeout is not None:
            arguments["planning_timeout"] = planning_timeout
        result = self._plan_advanced_drop_primitive(
            "move",
            arguments,
            background=background,
        )
        if ignored_options:
            note = (
                "Ignored plan_move options that are metadata or not documented "
                "AdvancedDrop.move planner options."
            )
            result["ignored_options"] = ignored_options
            result["option_note"] = note
            job_id = result.get("job_id")
            if background and job_id:
                self._update_advanced_drop_job_status(
                    str(job_id),
                    ignored_options=ignored_options,
                    option_note=note,
                )
        return result

    def _sanitize_plan_move_options(
        self,
        options: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Keep only documented planner options and report ignored metadata."""
        planner_options: Dict[str, Any] = {}
        ignored_options: Dict[str, Any] = {}
        for source_name, source in (("options", options), ("kwargs", extra)):
            if source is None:
                continue
            if not isinstance(source, dict):
                ignored_options[source_name] = self.to_jsonable(source)
                continue
            for raw_key, value in source.items():
                key = str(raw_key)
                if key in self.PLAN_MOVE_OPTION_KEYS:
                    planner_options[key] = value
                else:
                    ignored_options[key] = self.to_jsonable(value)
        return planner_options, ignored_options

    def plan_reservoir_extraction(
        self,
        reservoir_droplet_id: int,
        split_mode: str = "linear",
        steps: Optional[Iterable[int]] = None,
        split_size: Optional[Any] = None,
        new_droplet_id: Optional[int] = None,
        halo_size: int = 0,
        separation_steps: int = 3,
        linear_drops_number: Optional[int] = None,
        linear_offset: Optional[int] = None,
        linear_space_per_col: Optional[int] = None,
        linear_space_per_row: Optional[int] = None,
        linear_drop_shape: Optional[Any] = None,
        linear_direction: Optional[Iterable[int]] = None,
        linear_vital_space: Optional[int] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Plan extraction from a reservoir; does not execute hardware."""
        arguments = {
            "reservoir_droplet_id": int(reservoir_droplet_id),
            "split_mode": split_mode,
            "steps": steps,
            "split_size": split_size,
            "new_droplet_id": new_droplet_id,
            "halo_size": int(halo_size),
            "separation_steps": int(separation_steps),
            "linear_drops_number": linear_drops_number,
            "linear_offset": linear_offset,
            "linear_space_per_col": linear_space_per_col,
            "linear_space_per_row": linear_space_per_row,
            "linear_drop_shape": linear_drop_shape,
            "linear_direction": linear_direction,
            "linear_vital_space": linear_vital_space,
            "remove_duplicate_frames": bool(remove_duplicate_frames),
            **kwargs,
        }
        return self._plan_advanced_drop_primitive(
            "reservoir_extraction",
            arguments,
            background=background,
        )

    def plan_isometric_split(
        self,
        droplet_id: int,
        steps: Iterable[Iterable[int]],
        simultaneous: bool = True,
        new_droplet_id: Optional[int] = None,
        event_id: Optional[str] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan an isometric split; does not execute hardware."""
        return self._plan_advanced_drop_primitive(
            "isometric_split",
            {
                "droplet_id": int(droplet_id),
                "steps": steps,
                "simultaneous": bool(simultaneous),
                "new_droplet_id": new_droplet_id,
                "event_id": event_id,
                "remove_duplicate_frames": bool(remove_duplicate_frames),
            },
            background=background,
        )

    def plan_mix(
        self,
        droplet_id: int,
        mode: str = "split_recombine",
        split_area: Optional[Iterable[Iterable[int]]] = None,
        mixing_area_size: Optional[int] = None,
        cycles: int = 5,
        event_id: Optional[str] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan droplet mixing; does not execute hardware."""
        return self._plan_advanced_drop_primitive(
            "mix",
            {
                "droplet_id": int(droplet_id),
                "mode": mode,
                "split_area": split_area,
                "mixing_area_size": mixing_area_size,
                "cycles": int(cycles),
                "event_id": event_id,
                "remove_duplicate_frames": bool(remove_duplicate_frames),
            },
            background=background,
        )

    def plan_merge(
        self,
        droplet_ids: Any,
        target: Any,
        forced_width: Optional[int] = None,
        forced_height: Optional[int] = None,
        hold_final_position: bool = False,
        event_id: Optional[str] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan merging droplets into one target; does not execute hardware."""
        arguments = {
            "droplet_ids": droplet_ids,
            "target": target,
            "forced_width": forced_width,
            "forced_height": forced_height,
            "hold_final_position": bool(hold_final_position),
            "event_id": event_id,
            "remove_duplicate_frames": bool(remove_duplicate_frames),
        }
        return self._plan_advanced_drop_primitive(
            "merge",
            arguments,
            background=background,
        )

    def list_advanced_drop_methods(self) -> Dict[str, Any]:
        """List public AdvancedDrop methods exposed through advanced_drop_call."""
        advanced_drop = self.require_advanced_drop()
        methods = {}
        for name in sorted(self.ADVANCED_DROP_METHODS):
            func = getattr(advanced_drop, name, None)
            if func is None:
                continue
            methods[name] = {
                "signature": str(inspect.signature(func)),
                "doc": inspect.getdoc(func) or "",
            }
        return methods

    def advanced_drop_call(
        self, method: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Call a whitelisted AdvancedDrop public method with JSON arguments."""
        method, arguments = self._prepare_advanced_drop_call(method, arguments)
        self._guard_sync_advanced_drop_call(method, arguments)
        return self._execute_advanced_drop_call(method, arguments)

    def start_advanced_drop_call(
        self, method: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Start a whitelisted AdvancedDrop call in a background worker."""
        method, arguments = self._prepare_advanced_drop_call(method, arguments)

        with self._advanced_drop_job_lock:
            if (
                self._advanced_drop_job_thread is not None
                and self._advanced_drop_job_thread.is_alive()
            ):
                status = self.advanced_drop_job_status()
                raise DropLogicMCPError(
                    "An AdvancedDrop background job is already running. "
                    f"Current job id: {status.get('job_id')}. "
                    "Poll advanced_drop_job_status() or request "
                    "cancel_advanced_drop_job()."
                )

            job_id = uuid.uuid4().hex[:12]
            self._advanced_drop_job_cancel_event.clear()
            self._advanced_drop_job_status = {
                "job_id": job_id,
                "method": method,
                "arguments": self.to_jsonable(arguments),
                "running": True,
                "completed": False,
                "cancel_requested": False,
                "ok": None,
                "started_at": time.time(),
                "finished_at": None,
                "result": None,
                "error": None,
                "plan": None,
                "droplets": None,
            }
            self._advanced_drop_job_thread = threading.Thread(
                target=self._run_advanced_drop_job,
                args=(job_id, method, arguments),
                name=f"DropLogicAdvancedDropJob-{job_id}",
                daemon=True,
            )
            self._advanced_drop_job_thread.start()
            return self.advanced_drop_job_status()

    def advanced_drop_job_status(self) -> Dict[str, Any]:
        """Return compact status for the active or last AdvancedDrop background job."""
        with self._advanced_drop_job_lock:
            status = dict(self._advanced_drop_job_status or {})
            if not status:
                return {
                    "running": False,
                    "completed": False,
                    "thread_alive": False,
                    "message": "No AdvancedDrop background job has been started.",
                }
            thread = self._advanced_drop_job_thread
            status["thread_alive"] = bool(thread is not None and thread.is_alive())
        return self.to_jsonable(self._compact_advanced_drop_job_status(status))

    def _compact_advanced_drop_job_status(
        self,
        status: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(status, dict):
            return status
        method = status.get("method")
        result = status.get("result")
        result_plan = result.get("plan") if isinstance(result, dict) else None
        result_droplets = result.get("droplets") if isinstance(result, dict) else None
        compact: Dict[str, Any] = {
            "job_id": status.get("job_id"),
            "method": method,
            "running": status.get("running"),
            "completed": status.get("completed"),
            "cancel_requested": status.get("cancel_requested"),
            "ok": status.get("ok"),
            "thread_alive": status.get("thread_alive"),
            "started_at": status.get("started_at"),
            "finished_at": status.get("finished_at"),
            "error": status.get("error"),
            "arguments": self._compact_advanced_drop_arguments(
                method,
                status.get("arguments"),
            ),
            "plan": self._compact_plan_status(status.get("plan") or result_plan),
            "droplets": self._compact_droplets_status(
                status.get("droplets") or result_droplets
            ),
        }
        if status.get("ignored_options"):
            compact["ignored_options"] = status.get("ignored_options")
        if status.get("option_note"):
            compact["option_note"] = status.get("option_note")
        if status.get("notes"):
            compact["notes"] = status.get("notes")
        if status.get("next_step"):
            compact["next_step"] = status.get("next_step")
        elif isinstance(result, dict) and result.get("next_step"):
            compact["next_step"] = result.get("next_step")
        if isinstance(result, dict):
            compact["result"] = self._compact_advanced_drop_job_result(result)
        elif result is not None:
            compact["result"] = self._summarize_state_value(result)
        return compact

    def _compact_advanced_drop_arguments(
        self,
        method: Any,
        arguments: Any,
    ) -> Any:
        if not isinstance(arguments, dict):
            return self._summarize_state_value(arguments)
        compact: Dict[str, Any] = {}
        preferred_keys = (
            "mode",
            "remove_duplicate_frames",
            "planning_timeout",
            "allow_long_sync",
            "merge_on_failure",
            "max_frames",
            "max_threads",
            "max_iterations",
            "retry_attempts",
            "reserve_final_positions",
            "reservation_horizon",
            "max_path_frames",
            "add_events",
        )
        for key in preferred_keys:
            if key in arguments:
                compact[key] = self._summarize_state_value(arguments.get(key))
        for key, value in arguments.items():
            key = str(key)
            if key in compact:
                continue
            compact[key] = self._summarize_state_value(value)
        return compact

    def _compact_advanced_drop_job_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        compact: Dict[str, Any] = {}
        for key in (
            "method",
            "ok",
            "result_compact",
            "next_step",
            "move_validation",
        ):
            if key in result:
                compact[key] = self._summarize_state_value(result.get(key))
        visualizer_recovery = result.get("visualizer_recovery")
        if visualizer_recovery != {"needed": False}:
            compact["visualizer_recovery"] = self._summarize_state_value(
                visualizer_recovery
            )
        if "result" in result:
            compact["result"] = self._compact_advanced_drop_job_result_value(
                result.get("result")
            )
        if "plan" in result:
            compact["plan_ref"] = "top_level_plan"
        if "droplets" in result:
            compact["droplets_ref"] = "top_level_droplets"
        return compact

    def _compact_advanced_drop_job_result_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return [
                self._compact_advanced_drop_job_result_value(item)
                for item in value[:10]
            ]
        if not isinstance(value, dict):
            return self._summarize_state_value(value)
        compact: Dict[str, Any] = {}
        for key, item in value.items():
            key = str(key)
            if key == "plan":
                compact["plan_ref"] = "top_level_plan"
                continue
            if key == "note":
                continue
            if key in {"frames", "droplet_trajectories", "active_droplets_per_frame"}:
                compact[key] = self._summarize_state_value(item)
                continue
            compact[key] = self._summarize_state_value(item)
        return compact

    def cancel_advanced_drop_job(self) -> Dict[str, Any]:
        """Request cancellation of the active AdvancedDrop background job."""
        with self._advanced_drop_job_lock:
            if self._advanced_drop_job_status is None:
                return {
                    "ok": True,
                    "cancel_requested": False,
                    "message": "No AdvancedDrop background job is active.",
                }
            self._advanced_drop_job_cancel_event.set()
            self._advanced_drop_job_status["cancel_requested"] = True
            self._advanced_drop_job_status["notes"] = (
                "Cancellation is cooperative; CPU-bound planning may only stop "
                "after the current AdvancedDrop method returns."
            )
            return self.advanced_drop_job_status()

    def _prepare_advanced_drop_call(
        self, method: str, arguments: Optional[Dict[str, Any]] = None
    ):
        if method not in self.ADVANCED_DROP_METHODS:
            raise DropLogicMCPError(
                f"AdvancedDrop method '{method}' is not exposed through MCP. "
                f"Allowed methods: {sorted(self.ADVANCED_DROP_METHODS)}"
            )

        advanced_drop = self.require_advanced_drop()
        func = getattr(advanced_drop, method, None)
        if func is None:
            raise DropLogicMCPError(f"AdvancedDrop has no method '{method}'.")

        arguments = self._normalize_advanced_drop_arguments(method, arguments or {})
        return method, arguments

    def _execute_advanced_drop_call(
        self,
        method: str,
        arguments: Dict[str, Any],
        compact_result: bool = True,
        allow_full_result_override: bool = True,
    ) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        func = getattr(advanced_drop, method, None)
        if func is None:
            raise DropLogicMCPError(f"AdvancedDrop has no method '{method}'.")
        with self._lock:
            matrix_was_running = self._visualizer_running_safely("matrix")
            rollback_on_invalid_plan = method in self.PLAN_PRIMITIVE_METHODS
            plan_snapshot = None
            droplets_snapshot = None
            if rollback_on_invalid_plan:
                plan_snapshot = copy.deepcopy(getattr(advanced_drop, "plan", None))
                droplets_snapshot = [
                    copy.deepcopy(droplet)
                    for droplet in list(getattr(advanced_drop, "droplets", []) or [])
                ]
            call_arguments = dict(arguments)
            call_arguments.pop("allow_long_sync", None)
            return_full_result = bool(call_arguments.pop("return_full_result", False))
            if return_full_result and allow_full_result_override:
                compact_result = False
            try:
                result = func(**call_arguments)
            except Exception:
                if rollback_on_invalid_plan:
                    self._restore_advanced_drop_planning_snapshot(
                        advanced_drop,
                        plan_snapshot,
                        droplets_snapshot,
                    )
                raise
            visualizer_recovery = self._recover_visualizer_if_needed(
                "matrix",
                was_running=matrix_was_running,
            )
            result_plan = result if self._looks_like_droplet_plan(result) else advanced_drop.plan
            plan_summary = self.plan_summary(result_plan)
            droplets_summary = self.to_jsonable(
                advanced_drop.droplets.get_droplets_summary()
            )
            response = {
                "method": method,
                "result": self._compact_advanced_drop_result(method, result)
                if compact_result
                else self.to_jsonable(result),
                "result_compact": bool(compact_result),
                "visualizer_recovery": visualizer_recovery,
                "droplets": droplets_summary,
                "plan": plan_summary,
            }
            if method == "move":
                move_validation = self._validate_move_result(
                    droplets_summary,
                    plan_summary,
                )
                response["ok"] = bool(move_validation.get("ok"))
                response["move_validation"] = move_validation
            elif method in self.PLAN_PRIMITIVE_METHODS:
                primitive_validation = self._validate_planning_primitive_result(
                    method,
                    response.get("result"),
                    plan_summary,
                )
                response["ok"] = bool(primitive_validation.get("ok"))
                response["primitive_validation"] = primitive_validation
            if rollback_on_invalid_plan and response.get("ok") is False:
                self._restore_advanced_drop_planning_snapshot(
                    advanced_drop,
                    plan_snapshot,
                    droplets_snapshot,
                )
                response["rolled_back_failed_plan"] = True
                response["failed_plan"] = plan_summary
                response["plan"] = self.plan_summary(getattr(advanced_drop, "plan", None))
                response["droplets"] = self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                )
            next_step = (
                self._planning_next_step(method, plan_summary)
                if response.get("ok", True)
                else None
            )
            if next_step:
                response["next_step"] = next_step
            return response

    def _restore_advanced_drop_planning_snapshot(
        self,
        advanced_drop: Any,
        plan_snapshot: Any,
        droplets_snapshot: Optional[List[Any]],
    ) -> None:
        advanced_drop.plan = plan_snapshot
        if droplets_snapshot is not None and hasattr(advanced_drop, "droplets"):
            advanced_drop.droplets.clear()
            advanced_drop.droplets.extend(droplets_snapshot)

    def _update_advanced_drop_job_status(self, job_id: str, **updates: Any) -> None:
        with self._advanced_drop_job_lock:
            if not self._advanced_drop_job_status:
                return
            if self._advanced_drop_job_status.get("job_id") != job_id:
                return
            self._advanced_drop_job_status.update(self.to_jsonable(updates))

    def _guard_sync_advanced_drop_call(
        self, method: str, arguments: Dict[str, Any]
    ) -> None:
        if method != "move":
            return
        allow_long = bool(arguments.pop("allow_long_sync", False))
        if allow_long:
            return

        active_count = self._advanced_drop_active_move_count()
        if "planning_timeout" not in arguments:
            arguments["planning_timeout"] = self.ADVANCED_DROP_SYNC_MOVE_MAX_TIMEOUT
        planning_timeout = float(arguments["planning_timeout"])
        if (
            active_count > self.ADVANCED_DROP_SYNC_MOVE_MAX_ACTIVE
            or planning_timeout > self.ADVANCED_DROP_SYNC_MOVE_MAX_TIMEOUT
        ):
            raise DropLogicMCPError(
                "Refusing blocking AdvancedDrop move because it may exceed the "
                "MCP client request timeout and restart the server. Use "
                "plan_move(..., background=true) and poll planning_job_status(). "
                f"active_moving_droplets={active_count}, "
                f"planning_timeout={planning_timeout:g}s, "
                f"sync_limits={self.ADVANCED_DROP_SYNC_MOVE_MAX_ACTIVE} droplets/"
                f"{self.ADVANCED_DROP_SYNC_MOVE_MAX_TIMEOUT:g}s. "
                "For an intentional local debug-only blocking run, pass "
                "allow_long_sync=true."
            )

    def _advanced_drop_active_move_count(self) -> int:
        try:
            droplets = self.require_advanced_drop().droplets
            return sum(
                1
                for droplet in droplets
                if getattr(droplet, "origin_corner", None)
                != getattr(droplet, "target_corner", None)
            )
        except Exception:
            return 0

    def _validate_move_result(
        self,
        droplets_summary: Optional[Dict[str, Any]],
        plan_summary: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        droplets = []
        if isinstance(droplets_summary, dict):
            droplets = [
                item
                for item in droplets_summary.get("droplets") or []
                if isinstance(item, dict)
            ]
        plan = plan_summary if isinstance(plan_summary, dict) else {}
        targets_reached = plan.get("targets_reached") if isinstance(plan, dict) else {}
        if not isinstance(targets_reached, dict):
            targets_reached = {}
        trajectories = plan.get("trajectories") if isinstance(plan, dict) else {}
        if not isinstance(trajectories, dict):
            trajectories = {}
        active_ids = set()
        active_ids_known = "active_droplet_ids" in plan
        for item in plan.get("active_droplet_ids") or []:
            try:
                active_ids.add(int(item))
            except Exception:
                continue

        pending = [
            droplet
            for droplet in droplets
            if droplet.get("current_position") is not None
            and droplet.get("target_position") is not None
            and droplet.get("current_position") != droplet.get("target_position")
        ]
        moving = []
        for droplet in droplets:
            try:
                droplet_id = int(droplet.get("id"))
            except Exception:
                droplet_id = None
            if active_ids_known and droplet_id not in active_ids:
                continue
            if (
                droplet.get("current_position") is not None
                and droplet.get("target_position") is not None
                and droplet.get("current_position") != droplet.get("target_position")
            ):
                moving.append(droplet)
        moving_ids = [droplet.get("id") for droplet in moving]
        pending_ids = [droplet.get("id") for droplet in pending]
        failed_targets = [
            key for key, reached in targets_reached.items() if reached is False
        ]
        reached_targets = [
            key for key, reached in targets_reached.items() if reached is True
        ]
        stationary_unreached = []
        for droplet in moving:
            droplet_id = droplet.get("id")
            trajectory = trajectories.get(str(droplet_id)) or trajectories.get(droplet_id)
            if not isinstance(trajectory, dict):
                continue
            if (
                int(trajectory.get("length") or 0) <= 1
                or trajectory.get("start") == trajectory.get("end")
            ):
                stationary_unreached.append(droplet_id)

        planning_success = plan.get("planning_success")
        no_active_plan_for_pending_targets = bool(active_ids_known and not active_ids and pending)
        no_reported_target_results_for_pending_targets = bool(not targets_reached and pending)
        if no_active_plan_for_pending_targets or no_reported_target_results_for_pending_targets:
            return {
                "ok": False,
                "reason": "move_appended_no_target_progress",
                "message": (
                    "AdvancedDrop move returned no target progress while droplets still "
                    "have pending targets; treat this planned move as failed and do not execute it."
                ),
                "unreached_droplet_ids": pending_ids,
                "failed_target_ids": failed_targets,
                "stationary_unreached_droplet_ids": pending_ids,
                "reached_target_ids": reached_targets,
                "planning_success": planning_success,
            }
        if not moving and planning_success is not False:
            return {
                "ok": True,
                "reason": "all_droplets_at_target",
                "unreached_droplet_ids": [],
                "stationary_unreached_droplet_ids": [],
                "reached_target_ids": reached_targets,
            }

        if planning_success is False or moving:
            reason = (
                "planning_success_false"
                if planning_success is False
                else "droplets_still_not_at_target"
            )
            message = (
                "AdvancedDrop move did not reach all active droplet targets; treat "
                "this planned move as failed and do not execute it as a successful segment."
            )
            return {
                "ok": False,
                "reason": reason,
                "message": message,
                "unreached_droplet_ids": moving_ids,
                "failed_target_ids": failed_targets,
                "stationary_unreached_droplet_ids": stationary_unreached,
                "reached_target_ids": reached_targets,
                "planning_success": planning_success,
            }

        return {
            "ok": True,
            "reason": "targets_reached",
            "unreached_droplet_ids": [],
            "stationary_unreached_droplet_ids": [],
            "reached_target_ids": reached_targets,
        }

    def _validate_planning_primitive_result(
        self,
        method: str,
        result: Any,
        plan_summary: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        plan = plan_summary if isinstance(plan_summary, dict) else {}
        planning_success = plan.get("planning_success")
        targets_reached = plan.get("targets_reached")
        failed_targets = []
        reached_targets = []
        if isinstance(targets_reached, dict):
            failed_targets = [
                key for key, reached in targets_reached.items() if reached is False
            ]
            reached_targets = [
                key for key, reached in targets_reached.items() if reached is True
            ]

        if planning_success is False:
            return {
                "ok": False,
                "reason": "planning_success_false",
                "message": (
                    f"AdvancedDrop {method} produced planning_success=false; "
                    "treat this planned primitive as failed and do not execute it "
                    "or use it as goal-completion evidence."
                ),
                "failed_target_ids": failed_targets,
                "reached_target_ids": reached_targets,
                "planning_success": planning_success,
            }

        if method == "merge" and result is None:
            return {
                "ok": False,
                "reason": "merge_returned_no_product",
                "message": (
                    "AdvancedDrop merge did not produce a merged droplet id; "
                    "treat this merge as failed and choose a different merge "
                    "target or stage blockers away first."
                ),
                "failed_target_ids": failed_targets,
                "reached_target_ids": reached_targets,
                "planning_success": planning_success,
            }

        return {
            "ok": True,
            "reason": "primitive_plan_valid",
            "failed_target_ids": failed_targets,
            "reached_target_ids": reached_targets,
            "planning_success": planning_success,
        }

    def _compact_advanced_drop_result(self, method: str, result: Any) -> Any:
        if self._looks_like_droplet_plan(result):
            return {
                "type": type(result).__name__,
                "method": method,
                "plan": self.plan_summary(result),
                "note": (
                    "Full plan frames are stored in AdvancedDrop runtime; "
                    "background job status returns a compact summary only."
                ),
            }
        if isinstance(result, tuple):
            return [
                self._compact_advanced_drop_result(method, item)
                for item in result
            ]
        if isinstance(result, dict):
            compact = {}
            for key, value in result.items():
                if self._looks_like_droplet_plan(value):
                    compact[str(key)] = {
                        "type": type(value).__name__,
                        "plan": self.plan_summary(value),
                    }
                else:
                    compact[str(key)] = self._summarize_state_value(value)
            return compact
        return self._summarize_state_value(result)

    def _looks_like_droplet_plan(self, value: Any) -> bool:
        return all(
            hasattr(value, attr)
            for attr in (
                "frames",
                "droplet_trajectories",
                "planning_success",
                "targets_reached",
            )
        )

    def _run_advanced_drop_job(
        self, job_id: str, method: str, arguments: Dict[str, Any]
    ) -> None:
        ok = False
        error = None
        result = None
        try:
            if self._advanced_drop_job_cancel_event.is_set():
                raise DropLogicMCPError("AdvancedDrop job cancelled before start.")
            result = self._execute_advanced_drop_call(
                method,
                arguments,
                compact_result=True,
                allow_full_result_override=False,
            )
            if method == "move" and isinstance(result, dict):
                move_validation = result.get("move_validation")
                if isinstance(move_validation, dict) and not move_validation.get("ok", True):
                    raise DropLogicMCPError(
                        str(
                            move_validation.get("message")
                            or "AdvancedDrop move did not reach all droplet targets."
                        )
                    )
            elif method in self.PLAN_PRIMITIVE_METHODS and isinstance(result, dict):
                primitive_validation = result.get("primitive_validation")
                if isinstance(primitive_validation, dict) and not primitive_validation.get("ok", True):
                    raise DropLogicMCPError(
                        str(
                            primitive_validation.get("message")
                            or f"AdvancedDrop {method} primitive planning failed."
                        )
                    )
            ok = True
        except Exception as exc:
            error = self.to_jsonable(
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            if isinstance(result, dict) and result.get("move_validation"):
                error["move_validation"] = self.to_jsonable(
                    result.get("move_validation")
                )
            if isinstance(result, dict) and result.get("primitive_validation"):
                error["primitive_validation"] = self.to_jsonable(
                    result.get("primitive_validation")
                )
            self._record_error(f"advanced_drop_job:{method}", exc)
        finally:
            plan = None
            droplets = None
            try:
                advanced_drop = self.require_advanced_drop()
                if isinstance(result, dict) and isinstance(result.get("plan"), dict):
                    plan = result.get("plan")
                else:
                    plan = self.plan_summary(getattr(advanced_drop, "plan", None))
                droplets = self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                )
            except Exception:
                pass
            self._update_advanced_drop_job_status(
                job_id,
                running=False,
                completed=True,
                ok=ok,
                finished_at=time.time(),
                result=result,
                error=error,
                plan=plan,
                droplets=droplets,
                next_step=self._planning_next_step(method, plan) if ok else None,
            )

    def _planning_next_step(self, method: str, plan_summary: Optional[Dict[str, Any]]) -> Optional[str]:
        if method not in {"push_frame", "move", "reservoir_extraction", "isometric_split", "mix", "merge"}:
            return None
        if not isinstance(plan_summary, dict) or not plan_summary.get("available"):
            return None
        if plan_summary.get("planning_success") is False:
            return "Planning did not fully succeed; inspect plan_summary and fix the plan before executing."
        frame_count = plan_summary.get("frame_count")
        frame_text = f"frame {int(frame_count) - 1}" if isinstance(frame_count, int) and frame_count > 0 else "the segment target frame"
        return (
            "For real hardware/dry electrode tests, add a breakpoint at "
            f"{frame_text}, execute this planned segment, wait until it stops, "
            "and inspect before retargeting or planning the next segment."
        )

    def verify_droplets(
        self,
        frame_idx: int,
        droplet_ids: Optional[List[int]] = None,
        save_frames_path: Optional[str] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """Run AdvancedDrop droplet verification."""
        result = self.require_advanced_drop().verify_droplets(
            frame_idx=frame_idx,
            droplet_ids=droplet_ids,
            save_frames_path=save_frames_path,
            debug=debug,
        )
        return {
            "frame_idx": frame_idx,
            "result": self.to_jsonable(result),
        }

    def detect_condensates(
        self,
        crop_droplet: bool = True,
        crop_padding: int = 50,
        confidence_threshold: float = 0.25,
        return_annotated: bool = False,
        save_image_path: Optional[str] = None,
        save_debug_images: bool = False,
        debug_output_dir: Optional[str] = None,
        debug_prefix: Optional[str] = None,
        debug: bool = False,
        fluo_exposure: int = 2000000,
        fluo_light: int = 99,
        brightfield_exposure: int = 3600,
        brightfield_light: int = 30,
    ) -> Dict[str, Any]:
        """Run condensate detection through AdvancedDrop."""
        result = self.require_advanced_drop().detect_condensates(
            crop_droplet=crop_droplet,
            crop_padding=crop_padding,
            confidence_threshold=confidence_threshold,
            return_annotated=return_annotated,
            save_image_path=save_image_path,
            save_debug_images=save_debug_images,
            debug_output_dir=debug_output_dir,
            debug_prefix=debug_prefix,
            debug=debug,
            fluo_exposure=fluo_exposure,
            fluo_light=fluo_light,
            brightfield_exposure=brightfield_exposure,
            brightfield_light=brightfield_light,
        )
        return {
            "result": self.to_jsonable(result),
            "save_image_path": save_image_path,
            "debug_output_dir": debug_output_dir,
        }

    def system_call(
        self,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
        wait_if_busy: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Call a whitelisted DropSystem method."""
        if method not in self.SYSTEM_METHODS:
            raise DropLogicMCPError(
                f"System method '{method}' is not exposed through MCP. "
                f"Allowed methods: {sorted(self.SYSTEM_METHODS)}"
            )
        system = self.require_system()
        func = getattr(system, method, None)
        if func is None:
            raise DropLogicMCPError(f"Loaded system has no method '{method}'.")

        module_key = self.SYSTEM_METHOD_MODULES.get(method)
        if module_key is not None and method in self.SYSTEM_BUSY_GATED_METHODS:
            wait_result = self._wait_or_report_busy(
                module_key,
                wait_if_busy=wait_if_busy,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
            if wait_result is not None:
                return {
                    "ok": False,
                    "busy": True,
                    "method": method,
                    "module": module_key,
                    **wait_result,
                }

        try:
            if module_key == "xy_stage" and method in {
                "move_axis_to_position",
                "home_axis",
                "stop_motion",
                "stop_and_clear_axis",
                "start_continuous_movement",
                "stop_continuous_movement",
            }:
                pass
            result = func(**(arguments or {}))
            return {
                "ok": True,
                "busy": False,
                "method": method,
                "module": module_key,
                "result": self.to_jsonable(result),
            }
        except Exception as exc:
            self._record_error(f"system_call:{method}", exc)
            return {
                "ok": False,
                "busy": False,
                "method": method,
                "module": module_key,
                "error": self.to_jsonable(self.last_error),
            }

    def list_system_modules(self) -> Dict[str, Any]:
        """List loaded hardware modules and whitelisted methods."""
        system = self.require_system()
        modules = {}
        for module_name, methods in sorted(self.MODULE_METHODS.items()):
            module = getattr(system, module_name, None)
            modules[module_name] = {
                "available": module is not None,
                "methods": self._describe_methods(
                    module,
                    methods,
                    unsafe_pairs={
                        pair for pair in self.UNSAFE_MODULE_METHODS if pair[0] == module_name
                    },
                    module_name=module_name,
                )
                if module is not None
                else {},
            }
        return modules

    def module_busy_status(self, module: Optional[str] = None) -> Dict[str, Any]:
        """Return busy/free state for one module or all known modules."""
        self.require_system()
        if module is not None:
            module_key = module.lower()
            return {module_key: self._module_busy_status(module_key)}

        statuses = {}
        for module_name in sorted(self.MODULE_METHODS):
            statuses[module_name] = self._module_busy_status(module_name)
        return statuses

    def wait_for_module_free(
        self,
        module: str,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Wait until a module appears free, or return a timeout status."""
        module_key = module.lower()
        deadline = time.time() + max(0.0, float(timeout_seconds))
        poll_interval = max(0.02, float(poll_interval))

        while True:
            status = self._module_busy_status(module_key)
            if not status["busy"]:
                return {
                    "ok": True,
                    "module": module_key,
                    "timed_out": False,
                    "status": status,
                }

            if time.time() >= deadline:
                return {
                    "ok": False,
                    "module": module_key,
                    "timed_out": True,
                    "status": status,
                }

            time.sleep(poll_interval)

    def module_call(
        self,
        module: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
        wait_if_busy: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Call a whitelisted method on a loaded hardware module."""
        module_key = module.lower()
        allowed_methods = self.MODULE_METHODS.get(module_key)
        if allowed_methods is None:
            raise DropLogicMCPError(
                f"Unknown module '{module}'. Known modules: {sorted(self.MODULE_METHODS)}"
            )
        if method not in allowed_methods:
            hint = ""
            if module_key == "xy_stage":
                hint = (
                    " The XY stage has no generic move_to/move method in MCP. "
                    "Use top-level move_stage(preset=... or position=...) for stage moves, "
                    "set_execution_view_mode(...) for whole-chip/follow-droplet viewing, "
                    "or module_call(module='xy_stage', method='move_axis_to_position', "
                    "arguments={'axis': 'Y', 'target_position': 47000}) only as a low-level fallback."
                )
            raise DropLogicMCPError(
                f"Module method '{module}.{method}' is not exposed through MCP. "
                f"Allowed methods: {sorted(allowed_methods)}.{hint}"
            )
        if (module_key, method) in self.UNSAFE_MODULE_METHODS and not self.allow_unsafe_tools:
            raise DropLogicMCPError(
                f"{module}.{method} is a raw/unsafe module operation. Restart with "
                "--allow-unsafe-tools if you intentionally want to expose it."
            )

        system = self.require_system()
        module_instance = getattr(system, module_key, None)
        if module_instance is None:
            raise DropLogicMCPError(f"Loaded system has no module '{module}'.")
        func = getattr(module_instance, method, None)
        if func is None:
            raise DropLogicMCPError(f"Module '{module}' has no method '{method}'.")

        wait_result = self._wait_or_report_busy(
            module_key,
            wait_if_busy=wait_if_busy,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
        )
        if wait_result is not None:
            return {
                "ok": False,
                "busy": True,
                "module": module_key,
                "method": method,
                **wait_result,
            }

        try:
            result = func(**(arguments or {}))
            if module_key == "temperature" and method == "get_temperature" and result is None:
                return {
                    "ok": False,
                    "busy": False,
                    "module": module_key,
                    "method": method,
                    "result": None,
                    "read_failed": True,
                    "error": "temperature.get_temperature returned no valid reading",
                }
            if module_key == "temperature" and method == "get_temperature" and result is not None:
                try:
                    if hasattr(system, "set_cached_state"):
                        system.set_cached_state("temperature.current", result)
                except Exception:
                    pass
            return {
                "ok": True,
                "busy": False,
                "module": module_key,
                "method": method,
                "result": self.to_jsonable(result),
            }
        except Exception as exc:
            self._record_error(f"module_call:{module_key}.{method}", exc)
            return {
                "ok": False,
                "busy": False,
                "module": module_key,
                "method": method,
                "error": self.to_jsonable(self.last_error),
            }

    # ---------------------------------------------------------------------
    # PlanExecutor API

    def start_plan(
        self,
        frame_delay: float = 1.0,
        verify_positions: bool = False,
        enable_visualizers: bool = False,
        save_to_file: Optional[Any] = None,
        record_matrix: bool = False,
        record_streamer: bool = False,
        matrix_filename: Optional[str] = None,
        streamer_filename: Optional[str] = None,
        execution_view_mode: str = "follow_droplets",
        fixed_stage_position: Optional[Any] = None,
        prepare_execution_view: bool = True,
        execution_view_timeout_seconds: float = 60.0,
        restart_from_beginning: bool = False,
        allow_failed_plan: bool = False,
    ) -> Dict[str, Any]:
        executor = self.require_executor()
        with self._lock:
            executor_status = executor.status()
            current_frame = int(executor_status.get("current_frame") or 0)
            if current_frame > 0 and not restart_from_beginning:
                raise DropLogicMCPError(
                    "start_plan would restart execution from frame 0, but the "
                    f"executor is already at frame {current_frame}. Use "
                    "resume_plan() plus start_execute_until_breakpoint() to "
                    "continue from the current frame, or call start_plan("
                    "restart_from_beginning=true) only when the user explicitly "
                    "wants to replay the plan from the beginning."
                )

            plan_summary = self.plan_summary(getattr(self.system.advanced_drop, "plan", None))
            if plan_summary.get("planning_success") is False and not allow_failed_plan:
                raise DropLogicMCPError(
                    "The current plan is marked planning_success=false. "
                    "Do not execute it yet. Inspect the failed planning result, "
                    "reduce the batch size or add waypoints, then replan. "
                    "Use allow_failed_plan=true only for explicit supervised "
                    "debugging."
                )

            view_mode = self._normalize_execution_view_mode(execution_view_mode)
            view_result = None
            view_ready = {"ready": True, "reason": None, "view_mode": view_mode}
            if prepare_execution_view:
                view_result = self.set_execution_view_mode(
                    mode=view_mode,
                    fixed_stage_position=fixed_stage_position,
                    move_now=view_mode != "follow_droplets",
                    bring_to_front=False,
                    wait_timeout_seconds=execution_view_timeout_seconds,
                )
                view_ready = self._execution_view_ready_status(view_mode, view_result)
                if not view_ready.get("ready", False):
                    return {
                        "started": False,
                        "is_executing": False,
                        "reason": "execution_view_not_ready",
                        "execution_view_ready": self.to_jsonable(view_ready),
                        "execution_view": self.to_jsonable(view_result),
                        "executor_status": self.to_jsonable(executor.status()),
                    }

            stage_tracking_mode, resolved_stage_position = self._executor_stage_mode_for_view(
                view_mode,
                fixed_stage_position=fixed_stage_position,
            )
            notes = []
            effective_verify_positions = bool(verify_positions)
            if stage_tracking_mode == "fixed_stage" and effective_verify_positions:
                effective_verify_positions = False
                notes.append(
                    "verify_positions was disabled because fixed-stage/whole-chip "
                    "execution must not run microscope droplet verification during "
                    "the segment. Pause at a breakpoint and verify deliberately."
                )

            executor.start(
                frame_delay=frame_delay,
                verify_positions=effective_verify_positions,
                enable_visualizers=enable_visualizers,
                save_to_file=save_to_file,
                record_matrix=record_matrix,
                record_streamer=record_streamer,
                matrix_filename=matrix_filename,
                streamer_filename=streamer_filename,
                stage_tracking_mode=stage_tracking_mode,
                fixed_stage_position=resolved_stage_position,
                fixed_stage_ready=(
                    stage_tracking_mode == "fixed_stage"
                    and prepare_execution_view
                    and bool(view_ready.get("ready"))
                ),
            )
            status = self.to_jsonable(executor.status())
            if view_result is not None:
                status["execution_view"] = self.to_jsonable(view_result)
                status["execution_view_ready"] = self.to_jsonable(view_ready)
            status["requested_verify_positions"] = bool(verify_positions)
            status["effective_verify_positions"] = effective_verify_positions
            if notes:
                status["notes"] = notes
            return status

    def set_execution_view_mode(
        self,
        mode: str = "follow_droplets",
        fixed_stage_position: Optional[Any] = None,
        move_now: bool = True,
        bring_to_front: bool = False,
        wait_timeout_seconds: float = 20.0,
    ) -> Dict[str, Any]:
        """Configure PlanExecutor stage tracking and the live view mode."""
        system = self.require_system()
        executor = self.require_executor()
        view_mode = self._normalize_execution_view_mode(mode)
        actions = []

        if view_mode == "follow_droplets":
            executor.configure_stage_tracking("follow_droplets")
            try:
                streamer_result = self.set_streamer_source(
                    source="microscope",
                    electrode_overlay=True,
                    bring_to_front=bring_to_front,
                )
                actions.append({"set_streamer_source": streamer_result})
            except DropLogicMCPError as exc:
                actions.append({"set_streamer_source": {"ok": False, "error": str(exc)}})
            return {
                "ok": self._actions_ok(actions),
                "mode": "follow_droplets",
                "stage_tracking_mode": "follow_droplets",
                "fixed_stage_position": None,
                "actions": self.to_jsonable(actions),
                "executor_status": self.to_jsonable(executor.status()),
                "visualizers": self.visualizer_status(),
            }

        if view_mode == "whole_chip_camera":
            preset = self._get_named_preset("imaging", "whole_chip_camera")
            position = self._normalize_stage_position(
                fixed_stage_position or preset.get("position")
            )
            streamer_source = preset.get("streamer_source", "camera")

            try:
                streamer_result = self.set_streamer_source(
                    source=streamer_source,
                    electrode_overlay=False,
                    bring_to_front=bring_to_front,
                )
                actions.append({"set_streamer_source": streamer_result})
            except DropLogicMCPError as exc:
                actions.append({"set_streamer_source": {"ok": False, "error": str(exc)}})
            actions.extend(self._apply_whole_chip_camera_preset(system, preset))

            executor.configure_stage_tracking(
                "fixed_stage",
                fixed_stage_position=position,
                move_now=False,
            )
            if move_now:
                actions.append(
                    {
                        "move_stage": self._move_stage_to_position(
                            position,
                            wait_timeout_seconds=wait_timeout_seconds,
                            source="runtime.execution_view.whole_chip_camera",
                        )
                    }
                )

            return {
                "ok": self._actions_ok(actions),
                "mode": "whole_chip_camera",
                "stage_tracking_mode": "fixed_stage",
                "fixed_stage_position": position,
                "preset": self.to_jsonable(preset),
                "actions": self.to_jsonable(actions),
                "executor_status": self.to_jsonable(executor.status()),
                "visualizers": self.visualizer_status(),
            }

        stage_position = self._normalize_stage_position(fixed_stage_position)
        executor.configure_stage_tracking(
            "fixed_stage",
            fixed_stage_position=stage_position,
            move_now=False,
        )
        if move_now:
            actions.append(
                {
                    "move_stage": self._move_stage_to_position(
                        stage_position,
                        wait_timeout_seconds=wait_timeout_seconds,
                        source="runtime.execution_view.fixed_stage",
                    )
                }
            )

        return {
            "ok": self._actions_ok(actions),
            "mode": "fixed_stage",
            "stage_tracking_mode": "fixed_stage",
            "fixed_stage_position": stage_position,
            "actions": self.to_jsonable(actions),
            "executor_status": self.to_jsonable(executor.status()),
            "visualizers": self.visualizer_status(),
        }

    def move_stage(
        self,
        position: Optional[Any] = None,
        preset: Optional[str] = None,
        wait_timeout_seconds: float = 20.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Move the XY stage using a named preset or explicit X/Y/Z axis values."""
        system = self.require_system()
        if position is not None and preset is not None:
            raise DropLogicMCPError("Use either position or preset, not both.")

        resolved_preset = None
        if preset is not None:
            resolved_preset = self._get_stage_move_preset(preset)
            position = resolved_preset.get("position")

        target_position = self._normalize_stage_axis_update(position)
        xy_stage = getattr(system, "xy_stage", None)
        actual_before = self._read_stage_position(xy_stage)
        stage_idle = True
        if xy_stage is not None and hasattr(xy_stage, "is_motion_complete"):
            try:
                stage_idle = all(xy_stage.is_motion_complete(axis) for axis in ("X", "Y", "Z"))
            except Exception:
                stage_idle = False

        if (
            xy_stage is not None
            and stage_idle
            and self._stage_positions_close(target_position, actual_before)
        ):
            queue_summary = self._hardware_queue_summary()
            return {
                "ok": True,
                "preset": preset,
                "resolved_preset": self.to_jsonable(resolved_preset),
                "target_position": target_position,
                "actual_position": actual_before,
                "motion_complete": True,
                "skipped": "already_at_target",
                "queue_wait": {
                    "ok": True,
                    "timed_out": False,
                    "pending_commands": queue_summary.get("pending_commands", 0),
                    "queues": queue_summary.get("queues", {}),
                },
            }

        result = system.update_state("xy_stage.position", dict(target_position))
        queue_wait = self._wait_for_hardware_queue_empty(
            timeout_seconds=max(float(wait_timeout_seconds), 1.0),
            poll_interval=0.05,
        )

        if xy_stage is None or type(system).__name__ == "Simulator":
            actual_position = self._read_stage_position(xy_stage) or target_position
            return {
                "ok": bool(queue_wait.get("ok", True)),
                "preset": preset,
                "resolved_preset": self.to_jsonable(resolved_preset),
                "target_position": target_position,
                "actual_position": actual_position,
                "update_result": self.to_jsonable(result),
                "queue_wait": queue_wait,
                "motion_complete": True,
            }

        deadline = time.time() + max(0.0, float(wait_timeout_seconds))
        time.sleep(0.2)
        while time.time() < deadline:
            try:
                if all(xy_stage.is_motion_complete(axis) for axis in ("X", "Y", "Z")):
                    actual_position = self._read_stage_position(xy_stage)
                    ok = bool(queue_wait.get("ok", True)) and self._stage_positions_close(
                        target_position,
                        actual_position,
                    )
                    return {
                        "ok": ok,
                        "preset": preset,
                        "resolved_preset": self.to_jsonable(resolved_preset),
                        "target_position": target_position,
                        "actual_position": actual_position,
                        "update_result": self.to_jsonable(result),
                        "queue_wait": queue_wait,
                        "motion_complete": True,
                    }
            except Exception as exc:
                actual_position = self._read_stage_position(xy_stage)
                return {
                    "ok": False,
                    "preset": preset,
                    "resolved_preset": self.to_jsonable(resolved_preset),
                    "target_position": target_position,
                    "actual_position": actual_position,
                    "update_result": self.to_jsonable(result),
                    "queue_wait": queue_wait,
                    "motion_complete": False,
                    "error": str(exc),
                }
            time.sleep(max(0.02, float(poll_interval)))

        actual_position = self._read_stage_position(xy_stage)
        return {
            "ok": False,
            "preset": preset,
            "resolved_preset": self.to_jsonable(resolved_preset),
            "target_position": target_position,
            "actual_position": actual_position,
            "update_result": self.to_jsonable(result),
            "queue_wait": queue_wait,
            "motion_complete": False,
            "timed_out": True,
        }

    def pause_plan(self) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.pause()
        return self.to_jsonable(executor.status())

    def resume_plan(self, allow_failed_plan: bool = False) -> Dict[str, Any]:
        executor = self.require_executor()
        plan_summary = self.plan_summary(getattr(self.system.advanced_drop, "plan", None))
        if plan_summary.get("planning_success") is False and not allow_failed_plan:
            raise DropLogicMCPError(
                "The current plan is marked planning_success=false. "
                "Do not resume execution. Inspect the failed planning result, "
                "reduce the batch size or add waypoints, then replan. "
                "Use allow_failed_plan=true only for explicit supervised debugging."
            )
        executor.resume()
        return self.to_jsonable(executor.status())

    def stop_plan(self) -> Dict[str, Any]:
        executor = self.require_executor()
        before = self.to_jsonable(executor.status())
        executor.stop()
        after = self.to_jsonable(executor.status())
        after["already_stopped"] = not bool(before.get("is_executing"))
        after["was_executing"] = bool(before.get("is_executing"))
        return after

    def executor_status(self) -> Dict[str, Any]:
        return self.to_jsonable(self.require_executor().status())

    def add_breakpoint(self, frame_number: int) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.add_breakpoint(frame_number)
        return self.to_jsonable(executor.status())

    def remove_breakpoint(self, frame_number: int) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.remove_breakpoint(frame_number)
        return self.to_jsonable(executor.status())

    def clear_breakpoints(self) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.clear_breakpoints()
        return self.to_jsonable(executor.status())

    def execute_segment_to_breakpoint(
        self,
        frame_number: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        poll_interval_seconds: float = 0.25,
        resume_if_paused: bool = True,
        clear_existing_breakpoints: bool = True,
        allow_failed_plan: bool = False,
        frame_delay: float = 1.0,
        verify_positions: bool = False,
        enable_visualizers: bool = False,
        execution_view_mode: str = "follow_droplets",
        fixed_stage_position: Optional[Any] = None,
        prepare_execution_view: bool = True,
        execution_view_timeout_seconds: float = 60.0,
        wait_mode: str = "auto",
        inline_wait_max_seconds: Optional[float] = None,
        inline_wait_margin_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Arm a breakpoint, execute, and wait inline for short segments."""
        wait_mode = self._normalize_execute_segment_wait_mode(wait_mode)
        executor = self.require_executor()
        with self._execution_wait_lock:
            if (
                self._execution_wait_thread is not None
                and self._execution_wait_thread.is_alive()
            ):
                status = self.execution_wait_status()
                raise DropLogicMCPError(
                    "An execution wait job is already running. "
                    f"Current wait id: {status.get('wait_id')}. "
                    "Call execution_wait_status(wait_seconds=...) or cancel_execution_wait() "
                    "before executing another segment."
                )

        plan_summary = self.plan_summary(getattr(self.system.advanced_drop, "plan", None))
        if not plan_summary.get("available"):
            raise DropLogicMCPError("No plan is available to execute.")
        if plan_summary.get("planning_success") is False and not allow_failed_plan:
            raise DropLogicMCPError(
                "The current plan is marked planning_success=false. "
                "Do not execute it yet. Inspect the failed planning result, "
                "reduce the batch size or add waypoints, then replan. "
                "Use allow_failed_plan=true only for explicit supervised debugging."
            )

        frame_count = int(plan_summary.get("frame_count") or 0)
        if frame_count <= 0:
            raise DropLogicMCPError("The current plan has no frames to execute.")
        target_frame = frame_count - 1 if frame_number is None else int(frame_number)
        if target_frame < 0 or target_frame >= frame_count:
            raise DropLogicMCPError(
                f"Breakpoint frame {target_frame} is outside the current plan "
                f"range 0..{frame_count - 1}."
            )

        initial_status = self.to_jsonable(executor.status())
        current_frame = int(initial_status.get("current_frame") or 0)
        total_frames = int(initial_status.get("total_frames") or 0)
        if current_frame >= frame_count:
            return {
                "ok": True,
                "started_wait": False,
                "reason": "plan_already_complete",
                "breakpoint_frame": target_frame,
                "plan": self._compact_plan_status(plan_summary),
                "initial_executor_status": self._compact_executor_status(initial_status),
                "executor_status": self._compact_executor_status(
                    self.to_jsonable(executor.status())
                ),
                "next": "Plan is already complete; inspect/verify before planning another segment.",
            }
        if current_frame > target_frame:
            raise DropLogicMCPError(
                f"The executor is already at frame {current_frame}, past requested "
                f"breakpoint frame {target_frame}. Inspect executor_status before "
                "choosing another breakpoint."
            )

        if clear_existing_breakpoints:
            executor.clear_breakpoints()
        executor.add_breakpoint(target_frame)
        breakpoint_status = self.to_jsonable(executor.status())

        action = "start_plan"
        if current_frame == 0 and total_frames == 0:
            execution_result = self.start_plan(
                frame_delay=frame_delay,
                verify_positions=verify_positions,
                enable_visualizers=enable_visualizers,
                execution_view_mode=execution_view_mode,
                fixed_stage_position=fixed_stage_position,
                prepare_execution_view=prepare_execution_view,
                execution_view_timeout_seconds=execution_view_timeout_seconds,
                restart_from_beginning=False,
                allow_failed_plan=allow_failed_plan,
            )
            if execution_result.get("started") is False:
                return {
                    "ok": False,
                    "action": action,
                    "started_wait": False,
                    "breakpoint_frame": target_frame,
                    "plan": self._compact_plan_status(plan_summary),
                    "initial_executor_status": self._compact_executor_status(initial_status),
                    "breakpoint_status": self._compact_executor_status(breakpoint_status),
                    "execution_status": self._compact_executor_status(
                        self.to_jsonable(execution_result)
                    ),
                    "reason": execution_result.get("reason") or "start_plan_failed",
                    "execution_result": self.to_jsonable(execution_result),
                    "next": "Resolve the execution start failure before waiting or planning another segment.",
                }
        else:
            action = "resume_plan"
            self._set_executor_frame_delay(executor, frame_delay)
            if resume_if_paused:
                execution_result = self.resume_plan(allow_failed_plan=allow_failed_plan)
            else:
                execution_result = self.to_jsonable(executor.status())

        wait_timeout_seconds, wait_estimate = self._execute_segment_wait_timeout_seconds(
            executor=executor,
            target_frame=target_frame,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            inline_wait_margin_seconds=inline_wait_margin_seconds,
        )
        inline_limit = (
            self.EXECUTE_SEGMENT_INLINE_WAIT_MAX_SECONDS
            if inline_wait_max_seconds is None
            else max(0.0, float(inline_wait_max_seconds))
        )
        inline_wait = wait_mode == "inline" or (
            wait_mode == "auto" and wait_timeout_seconds <= inline_limit
        )

        if inline_wait:
            wait_status = self._execute_segment_inline_wait(
                timeout_seconds=wait_timeout_seconds,
                resume_if_paused=resume_if_paused,
                poll_interval_seconds=poll_interval_seconds,
                target_frame=target_frame,
            )
            ok = bool(wait_status.get("ok"))
            return {
                "ok": ok,
                "action": action,
                "wait_mode": "inline",
                "background_wait_started": False,
                "started_wait": False,
                "breakpoint_frame": target_frame,
                "plan": self._compact_plan_status(plan_summary),
                "initial_executor_status": self._compact_executor_status(initial_status),
                "breakpoint_status": self._compact_executor_status(breakpoint_status),
                "execution_status": self._compact_executor_status(
                    self.to_jsonable(execution_result)
                ),
                "wait_estimate": wait_estimate,
                "wait_status": self._compact_execution_wait_status(wait_status),
                "next": (
                    "Execution reached the segment target; inspect/verify before planning the next segment."
                    if ok
                    else "Execution did not reach the segment target; inspect wait_status before planning another segment."
                ),
            }

        wait_status = self.start_execute_until_breakpoint(
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
            poll_interval_seconds=poll_interval_seconds,
        )
        recommended_wait_seconds = self._execution_wait_recommended_wait_seconds(
            wait_estimate=wait_estimate
        )
        compact_wait_status = self._compact_execution_wait_status(wait_status)

        return {
            "ok": True,
            "action": action,
            "wait_mode": "background",
            "background_wait_started": True,
            "started_wait": True,
            "recommended_wait_seconds": recommended_wait_seconds,
            "next_check_after_seconds": recommended_wait_seconds,
            "recommended_status_call": {
                "tool": "execution_wait_status",
                "arguments": {"wait_seconds": recommended_wait_seconds},
            },
            "breakpoint_frame": target_frame,
            "plan": self._compact_plan_status(plan_summary),
            "initial_executor_status": self._compact_executor_status(initial_status),
            "breakpoint_status": self._compact_executor_status(breakpoint_status),
            "execution_status": self._compact_executor_status(
                self.to_jsonable(execution_result)
            ),
            "wait_estimate": wait_estimate,
            "wait_status": compact_wait_status,
            "next": (
                "Background wait is running; call execution_wait_status(wait_seconds="
                f"{recommended_wait_seconds}) once. If it still returns running=true, "
                "repeat with the returned recommended_wait_seconds instead of immediate polling."
            ),
        }

    def _normalize_execute_segment_wait_mode(self, wait_mode: str) -> str:
        mode = str(wait_mode or "auto").strip().lower()
        if mode not in {"auto", "inline", "background"}:
            raise DropLogicMCPError(
                "wait_mode must be 'auto', 'inline', or 'background'."
            )
        return mode

    def _set_executor_frame_delay(self, executor: Any, frame_delay: float) -> None:
        try:
            executor.frame_delay = float(frame_delay)
            sync = getattr(executor, "_sync_recording_fps_to_frame_delay", None)
            if callable(sync):
                sync()
        except Exception as exc:
            raise DropLogicMCPError(f"Could not set executor frame_delay={frame_delay}: {exc}")

    def _execute_segment_wait_timeout_seconds(
        self,
        executor: Any,
        target_frame: int,
        timeout_seconds: Optional[float],
        poll_interval_seconds: float,
        inline_wait_margin_seconds: Optional[float],
    ) -> Tuple[float, Dict[str, Any]]:
        status = self.to_jsonable(executor.status())
        current_frame = int(status.get("current_frame") or 0)
        remaining_frames = max(0, int(target_frame) - current_frame + 1)
        frame_delay = max(float(getattr(executor, "frame_delay", 1.0) or 0.0), 0.01)
        margin = (
            self.EXECUTE_SEGMENT_INLINE_WAIT_MARGIN_SECONDS
            if inline_wait_margin_seconds is None
            else max(0.0, float(inline_wait_margin_seconds))
        )
        estimated_seconds = (
            remaining_frames * max(frame_delay, float(poll_interval_seconds), 0.05)
            + margin
        )
        if timeout_seconds is None:
            timeout = estimated_seconds
        else:
            timeout = max(0.05, float(timeout_seconds))
        return timeout, {
            "timeout_seconds": timeout,
            "estimated_seconds": round(float(estimated_seconds), 3),
            "remaining_frames": remaining_frames,
            "frame_delay": frame_delay,
            "margin_seconds": margin,
            "target_frame": int(target_frame),
            "current_frame": current_frame,
        }

    def _execution_wait_recommended_wait_seconds(
        self,
        wait_estimate: Optional[Dict[str, Any]] = None,
        status: Optional[Dict[str, Any]] = None,
    ) -> float:
        candidates: List[float] = []
        for container, keys in (
            (wait_estimate, ("estimated_seconds", "timeout_seconds")),
            (status, ("remaining_timeout_seconds", "timeout_seconds")),
        ):
            if not isinstance(container, dict):
                continue
            for key in keys:
                try:
                    value = float(container.get(key))
                except (TypeError, ValueError):
                    continue
                if np.isfinite(value):
                    candidates.append(max(0.0, value))

        seconds = min(candidates) if candidates else self.EXECUTION_WAIT_STATUS_MAX_WAIT_SECONDS
        max_wait = max(0.25, float(self.EXECUTION_WAIT_STATUS_MAX_WAIT_SECONDS))
        min_wait = max(0.25, float(self.EXECUTION_WAIT_STATUS_MIN_WAIT_SECONDS))
        if seconds <= 0.0:
            return round(min_wait, 3)
        if seconds < min_wait:
            return round(seconds, 3)
        return round(min(max_wait, max(min_wait, seconds)), 3)

    def _execute_segment_inline_wait(
        self,
        timeout_seconds: float,
        resume_if_paused: bool,
        poll_interval_seconds: float,
        target_frame: int,
    ) -> Dict[str, Any]:
        executor = self.require_executor()
        initial_status = self.to_jsonable(executor.status())
        wait_id = uuid.uuid4().hex[:12]
        with self._execution_wait_lock:
            self._execution_wait_cancel_event.clear()
            self._execution_wait_status = {
                "wait_id": wait_id,
                "running": True,
                "completed": False,
                "ok": None,
                "cancel_requested": False,
                "started_at": time.time(),
                "finished_at": None,
                "timeout_seconds": float(timeout_seconds),
                "poll_interval_seconds": max(0.05, float(poll_interval_seconds)),
                "target_frame": target_frame,
                "resume_if_paused": bool(resume_if_paused),
                "wait_mode": "inline",
                "timed_out": False,
                "reason": None,
                "error": None,
                "executor_status": initial_status,
            }
        self._run_execution_wait_job(
            wait_id,
            float(timeout_seconds),
            bool(resume_if_paused),
            max(0.05, float(poll_interval_seconds)),
            target_frame,
        )
        return self.execution_wait_status()

    def execute_until_breakpoint(
        self, timeout_seconds: Optional[float] = None, resume_if_paused: bool = True
    ) -> Dict[str, Any]:
        executor = self.require_executor()
        completed = executor.execute_until_breakpoint(
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
        )
        return {
            "completed": bool(completed),
            "status": self.to_jsonable(executor.status()),
        }

    def start_execute_until_breakpoint(
        self,
        timeout_seconds: Optional[float] = None,
        resume_if_paused: bool = True,
        poll_interval_seconds: float = 0.25,
    ) -> Dict[str, Any]:
        """Start a non-blocking wait for the next breakpoint or plan completion."""
        executor = self.require_executor()
        initial_status = self.to_jsonable(executor.status())
        target_frame = None
        try:
            target_frame = executor._resolve_expected_breakpoint_frame()
        except Exception:
            breakpoints = initial_status.get("breakpoints") or []
            if breakpoints:
                target_frame = max(int(frame) for frame in breakpoints)

        if timeout_seconds is None:
            try:
                timeout_seconds = executor.estimate_breakpoint_timeout(
                    target_frame=target_frame
                )
            except Exception:
                timeout_seconds = 300.0

        with self._execution_wait_lock:
            if (
                self._execution_wait_thread is not None
                and self._execution_wait_thread.is_alive()
            ):
                status = self.execution_wait_status()
                raise DropLogicMCPError(
                    "An execution wait job is already running. "
                    f"Current wait id: {status.get('wait_id')}. "
                    "Call execution_wait_status(wait_seconds=...) or cancel_execution_wait()."
                )

            wait_id = uuid.uuid4().hex[:12]
            self._execution_wait_cancel_event.clear()
            self._execution_wait_status = {
                "wait_id": wait_id,
                "running": True,
                "completed": False,
                "ok": None,
                "cancel_requested": False,
                "started_at": time.time(),
                "finished_at": None,
                "timeout_seconds": float(timeout_seconds),
                "poll_interval_seconds": max(0.05, float(poll_interval_seconds)),
                "target_frame": target_frame,
                "resume_if_paused": bool(resume_if_paused),
                "wait_mode": "background",
                "timed_out": False,
                "reason": None,
                "error": None,
                "executor_status": initial_status,
            }
            self._execution_wait_thread = threading.Thread(
                target=self._run_execution_wait_job,
                args=(
                    wait_id,
                    float(timeout_seconds),
                    bool(resume_if_paused),
                    max(0.05, float(poll_interval_seconds)),
                    target_frame,
                ),
                name=f"DropLogicExecutionWait-{wait_id}",
                daemon=True,
            )
            self._execution_wait_thread.start()
            return self.execution_wait_status()

    def execution_wait_status(
        self,
        wait_seconds: float = 0.0,
        poll_interval_seconds: float = 0.25,
    ) -> Dict[str, Any]:
        """Return compact status for the active or last execution wait job."""
        wait_started_at = time.monotonic()
        status_wait = self._execution_wait_status_timer_wait(
            wait_seconds=wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        status = self._execution_wait_status_snapshot()
        if status_wait is not None:
            status_wait["elapsed_seconds"] = round(
                max(0.0, time.monotonic() - wait_started_at),
                3,
            )
            status_wait["running_after_wait"] = bool(status.get("running"))
            if not status_wait.get("started_running"):
                status_wait["return_reason"] = "no_running_wait"
            elif status.get("running"):
                status_wait["return_reason"] = "timer_elapsed"
            else:
                status_wait["return_reason"] = "wait_completed"
            status["status_wait"] = status_wait
        return self._compact_execution_wait_status(status)

    def _execution_wait_status_timer_wait(
        self,
        wait_seconds: float,
        poll_interval_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        try:
            requested_seconds = float(wait_seconds or 0.0)
        except (TypeError, ValueError):
            raise DropLogicMCPError("wait_seconds must be a finite number.")
        if not np.isfinite(requested_seconds):
            raise DropLogicMCPError("wait_seconds must be a finite number.")

        max_wait_seconds = max(0.25, float(self.EXECUTION_WAIT_STATUS_MAX_WAIT_SECONDS))
        effective_seconds = min(max(0.0, requested_seconds), max_wait_seconds)
        if effective_seconds <= 0.0:
            return None

        try:
            fallback_sleep_seconds = float(poll_interval_seconds or 0.25)
        except (TypeError, ValueError):
            fallback_sleep_seconds = 0.25
        if not np.isfinite(fallback_sleep_seconds):
            fallback_sleep_seconds = 0.25
        fallback_sleep_seconds = min(
            effective_seconds,
            max(0.05, fallback_sleep_seconds),
        )

        with self._execution_wait_lock:
            status = dict(self._execution_wait_status or {})
            thread = self._execution_wait_thread
            started_running = bool(status.get("running"))
            wait_id = status.get("wait_id")

        used_thread_join = False
        if started_running:
            if thread is not None and thread.is_alive():
                used_thread_join = True
                thread.join(timeout=effective_seconds)
            else:
                time.sleep(fallback_sleep_seconds)

        return {
            "wait_id": wait_id,
            "requested_seconds": round(max(0.0, requested_seconds), 3),
            "effective_seconds": round(effective_seconds, 3),
            "max_wait_seconds": round(max_wait_seconds, 3),
            "started_running": started_running,
            "used_thread_join": used_thread_join,
        }

    def _execution_wait_status_snapshot(self) -> Dict[str, Any]:
        with self._execution_wait_lock:
            status = dict(self._execution_wait_status or {})
            if not status:
                return {
                    "running": False,
                    "completed": False,
                    "thread_alive": False,
                    "message": "No execution wait job has been started.",
                }
            thread = self._execution_wait_thread
            status["thread_alive"] = bool(thread is not None and thread.is_alive())
            try:
                started_at = float(status.get("started_at"))
            except (TypeError, ValueError):
                started_at = None
            if started_at is not None and np.isfinite(started_at):
                try:
                    finished_at = float(status.get("finished_at"))
                except (TypeError, ValueError):
                    finished_at = None
                if finished_at is None or not np.isfinite(finished_at):
                    finished_at = time.time()
                elapsed_seconds = max(0.0, finished_at - started_at)
                status["elapsed_seconds"] = round(elapsed_seconds, 3)
                try:
                    timeout_seconds = float(status.get("timeout_seconds"))
                except (TypeError, ValueError):
                    timeout_seconds = None
                if timeout_seconds is not None and np.isfinite(timeout_seconds):
                    status["remaining_timeout_seconds"] = round(
                        max(0.0, timeout_seconds - elapsed_seconds),
                        3,
                    )
            if status.get("running"):
                recommended_wait_seconds = self._execution_wait_recommended_wait_seconds(
                    status=status
                )
                status["recommended_wait_seconds"] = recommended_wait_seconds
                status["next_check_after_seconds"] = recommended_wait_seconds
                status["recommended_status_call"] = {
                    "tool": "execution_wait_status",
                    "arguments": {"wait_seconds": recommended_wait_seconds},
                }
            try:
                status["executor_status"] = self.to_jsonable(
                    self.require_executor().status()
                )
            except Exception as exc:
                status["executor_status_error"] = str(exc)
            return self.to_jsonable(status)

    def cancel_execution_wait(self) -> Dict[str, Any]:
        """Cancel the background wait only; it does not stop plan execution."""
        with self._execution_wait_lock:
            if self._execution_wait_status is None:
                return {
                    "ok": True,
                    "cancel_requested": False,
                    "message": "No execution wait job is active.",
                }
            self._execution_wait_cancel_event.set()
            self._execution_wait_status["cancel_requested"] = True
            self._execution_wait_status["notes"] = (
                "This cancels only the MCP wait job. Use pause_plan() or "
                "stop_plan() to affect physical execution."
            )
            return self.execution_wait_status()

    def _update_execution_wait_status(self, wait_id: str, **updates: Any) -> None:
        with self._execution_wait_lock:
            if not self._execution_wait_status:
                return
            if self._execution_wait_status.get("wait_id") != wait_id:
                return
            self._execution_wait_status.update(self.to_jsonable(updates))

    def _run_execution_wait_job(
        self,
        wait_id: str,
        timeout_seconds: float,
        resume_if_paused: bool,
        poll_interval_seconds: float,
        target_frame: Optional[int],
    ) -> None:
        ok = False
        timed_out = False
        reason = None
        error = None
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        try:
            executor = self.require_executor()
            if resume_if_paused:
                status = executor.status()
                if (
                    not status.get("is_executing")
                    and not status.get("breakpoint_reached")
                    and int(status.get("current_frame") or 0)
                    < int(status.get("total_frames") or 0)
                ):
                    executor.resume()

            while not self._execution_wait_cancel_event.is_set():
                status = self.to_jsonable(executor.status())
                self._update_execution_wait_status(
                    wait_id,
                    executor_status=status,
                )
                current_frame = int(status.get("current_frame") or 0)
                total_frames = int(status.get("total_frames") or 0)
                if status.get("breakpoint_reached"):
                    ok = True
                    reason = "breakpoint_reached"
                    break
                if target_frame is not None and current_frame > int(target_frame):
                    ok = True
                    reason = "target_frame_reached"
                    break
                if total_frames > 0 and current_frame >= total_frames:
                    ok = True
                    reason = "plan_complete"
                    break
                if not status.get("is_executing"):
                    reason = "executor_stopped"
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    reason = "timeout"
                    break
                time.sleep(max(0.05, float(poll_interval_seconds)))

            if self._execution_wait_cancel_event.is_set() and reason is None:
                reason = "cancelled"
        except Exception as exc:
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            self._record_error("execution_wait", exc)
        finally:
            final_status = None
            try:
                final_status = self.to_jsonable(self.require_executor().status())
            except Exception:
                pass
            self._update_execution_wait_status(
                wait_id,
                running=False,
                completed=True,
                ok=ok,
                timed_out=timed_out,
                reason=reason,
                error=error,
                finished_at=time.time(),
                executor_status=final_status,
            )

    def plan_summary(self, plan=None) -> Dict[str, Any]:
        if plan is None and self.system is not None and hasattr(self.system, "advanced_drop"):
            plan = getattr(self.system.advanced_drop, "plan", None)

        if plan is None:
            return {
                "available": False,
                "frame_count": 0,
                "planning_success": None,
            }

        events = []
        for event in getattr(plan, "events", []) or []:
            events.append(self.to_jsonable(event))

        trajectories = {}
        for droplet_id, trajectory in (
            getattr(plan, "droplet_trajectories", {}) or {}
        ).items():
            if not trajectory:
                trajectories[str(droplet_id)] = {"length": 0, "start": None, "end": None}
            else:
                trajectories[str(droplet_id)] = {
                    "length": len(trajectory),
                    "start": self.to_jsonable(trajectory[0]),
                    "end": self.to_jsonable(trajectory[-1]),
                }

        active_frames = getattr(plan, "active_droplets_per_frame", []) or []
        active_droplet_ids = []
        if active_frames:
            for item in active_frames[-1] or []:
                try:
                    active_droplet_ids.append(int(item))
                except Exception:
                    continue

        return {
            "available": True,
            "frame_count": len(getattr(plan, "frames", []) or []),
            "planning_success": bool(getattr(plan, "planning_success", False)),
            "active_droplet_ids": active_droplet_ids,
            "events": events,
            "targets_reached": self.to_jsonable(
                getattr(plan, "targets_reached", {}) or {}
            ),
            "trajectories": trajectories,
            "conflicts_resolved": self.to_jsonable(
                getattr(plan, "conflicts_resolved", []) or []
            ),
        }

    def execution_scene(
        self,
        max_path_points: int = 64,
        max_droplet_cells: int = 0,
        include_droplet_cells: bool = False,
        include_paths: bool = True,
        include_action_paths: bool = False,
    ) -> Dict[str, Any]:
        """Return a compact structured scene for plan/executor visual inspection."""
        system = self.system
        if system is None:
            return {
                "available": False,
                "reason": "no_system_loaded",
                "system_loaded": False,
                "scene_mode": "none",
            }

        coordinate_mapping = self._execution_scene_coordinate_mapping(system)
        matrix_summary = None
        try:
            matrix_summary = self.matrix_summary(
                source="state",
                include_ranges=True,
                include_active_cells=False,
                include_hash=True,
            )
        except Exception as exc:
            matrix_summary = {"error": str(exc)}

        advanced_drop = getattr(system, "advanced_drop", None)
        if advanced_drop is None:
            return {
                "available": False,
                "reason": "no_advanced_drop",
                "system_loaded": True,
                "scene_mode": "matrix",
                "matrix": matrix_summary,
                "coordinate_mapping": coordinate_mapping,
                "updated_at": time.time(),
            }

        executor = getattr(advanced_drop, "executor", None)
        executor_status = self.to_jsonable(executor.status()) if executor is not None else None
        executor_plan = getattr(executor, "current_plan", None) if executor is not None else None
        plan = getattr(advanced_drop, "plan", None)
        if plan is None:
            plan = executor_plan
        applied_plan = getattr(executor, "last_applied_frame_plan", None) if executor is not None else None
        frame_plan = applied_plan if applied_plan is not None else plan

        frames = list(getattr(frame_plan, "frames", []) or []) if frame_plan is not None else []
        frame_count = len(frames)
        frame_index, frame_matrix, frame_source = self._execution_scene_frame_source(
            executor,
            executor_status,
            frames,
            matrix_summary,
        )
        frame_summary = None
        if frame_matrix is not None:
            try:
                frame_summary = self._matrix_compact_representation(
                    frame_matrix,
                    source=frame_source,
                    include_ranges=True,
                    include_active_cells=False,
                    include_hash=True,
                )
            except Exception as exc:
                frame_summary = {"error": str(exc), "index": frame_index, "source": frame_source}

        droplets = self._execution_scene_droplets(
            advanced_drop=advanced_drop,
            plan=applied_plan,
            frame_index=frame_index,
            executed_frame=frame_source == "executor_last_applied_frame",
            max_path_points=max_path_points,
            max_droplet_cells=max_droplet_cells,
            include_droplet_cells=include_droplet_cells,
            include_paths=include_paths,
        )
        current_event = self._execution_scene_current_event(applied_plan, frame_index)
        action_paths = (
            self._execution_scene_action_paths(plan, max_path_points=max_path_points)
            if include_paths and include_action_paths
            else []
        )
        plan_summary = self.plan_summary(plan)
        revision_payload = {
            "system": self.system_name,
            "matrix_hash": (
                (matrix_summary or {}).get("matrix_values_sha256")
                or (matrix_summary or {}).get("active_mask_sha256")
            )
            if isinstance(matrix_summary, dict)
            else None,
            "frame_hash": (
                (frame_summary or {}).get("matrix_values_sha256")
                or (frame_summary or {}).get("active_mask_sha256")
            )
            if isinstance(frame_summary, dict)
            else None,
            "frame_index": frame_index,
            "frame_count": frame_count,
            "executor_frame": (executor_status or {}).get("current_frame")
            if isinstance(executor_status, dict)
            else None,
            "droplets": [
                {
                    "id": droplet.get("id"),
                    "position": droplet.get("position"),
                    "target": droplet.get("target"),
                    "bbox": droplet.get("bbox"),
                }
                for droplet in droplets
            ],
            "coordinate_mapping": coordinate_mapping,
            "actions": [
                {
                    "id": action.get("id"),
                    "type": action.get("type"),
                    "frame_span": action.get("frame_span"),
                    "path_count": len(action.get("paths") or []),
                }
                for action in action_paths
            ],
        }
        revision = hashlib.sha256(
            json.dumps(
                self.to_jsonable(revision_payload),
                sort_keys=True,
                ensure_ascii=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:16]

        plan_payload = {
            "available": bool(plan_summary.get("available")),
            "planning_success": plan_summary.get("planning_success"),
            "frame_count": plan_summary.get("frame_count"),
            "targets_reached": plan_summary.get("targets_reached"),
            "trajectory_count": len(plan_summary.get("trajectories") or {}),
            "event_count": len(getattr(plan, "events", []) or []) if plan is not None else 0,
            "current_event": current_event,
            "scene_plan_source": "current_plan",
            "frame_plan_source": "executor_last_applied_plan" if applied_plan is not None else "current_plan",
            "droplets_source": "executor_last_applied_frame"
            if frame_source == "executor_last_applied_frame"
            else "none",
        }
        if include_action_paths:
            plan_payload["actions"] = action_paths

        return {
            "available": True,
            "surface": "execution_scene",
            "system_loaded": True,
            "system": self.system_name,
            "scene_mode": "advanced_drop",
            "updated_at": time.time(),
            "revision": revision,
            "matrix": matrix_summary,
            "coordinate_mapping": coordinate_mapping,
            "frame": {
                "index": frame_index,
                "count": frame_count,
                "source": frame_source,
                "synced_to_executor": frame_source == "executor_last_applied_frame",
                "summary": frame_summary,
            },
            "executor": executor_status,
            "plan": plan_payload,
            "droplets": droplets,
        }

    def _execution_scene_coordinate_mapping(self, system: Any) -> Optional[Dict[str, Any]]:
        """Return the electrode-to-stage affine calibration used by the dashboard."""
        try:
            state = getattr(system, "state", None)
        except Exception:
            return None
        if not isinstance(state, dict):
            return None

        calibration = state.get("calibration")
        if not isinstance(calibration, dict):
            return None
        raw_mapping = calibration.get("electrode_mapping")
        chip_origin = calibration.get("chip_origin")
        if not isinstance(raw_mapping, dict) or not isinstance(chip_origin, dict):
            return None

        def number(value: Any, default: Optional[float] = None) -> Optional[Any]:
            if value is None:
                return default
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return default
            if not np.isfinite(parsed):
                return default
            return int(parsed) if parsed.is_integer() else parsed

        def vector(values: Any) -> List[Any]:
            if not isinstance(values, (list, tuple)):
                return []
            parsed_values: List[Any] = []
            for item in values:
                parsed = number(item)
                if parsed is None:
                    return []
                parsed_values.append(parsed)
            return parsed_values

        origin: Dict[str, Any] = {}
        for axis in ("X", "Y", "Z"):
            parsed = number(chip_origin.get(axis, chip_origin.get(axis.lower())))
            if parsed is not None:
                origin[axis] = parsed
        if "X" not in origin or "Y" not in origin:
            return None

        inter_row = vector(raw_mapping.get("inter_row"))
        inter_column = vector(raw_mapping.get("inter_column"))
        if len(inter_row) < 2 or len(inter_column) < 2:
            return None

        offset: Dict[str, Any] = {
            "X": number(raw_mapping.get("offset_x"), 0),
            "Y": number(raw_mapping.get("offset_y"), 0),
        }
        offset_z = number(raw_mapping.get("offset_z"))
        if offset_z is not None:
            offset["Z"] = offset_z

        electrode_config = state.get("electrode_matrix", {})
        matrix_shape = None
        if isinstance(electrode_config, dict):
            rows = number(electrode_config.get("rows"))
            columns = number(electrode_config.get("columns"))
            if rows is not None and columns is not None:
                matrix_shape = [int(rows), int(columns)]

        return {
            "kind": "electrode_to_stage_affine",
            "units": "stage_steps",
            "origin_electrode": [0, 0],
            "matrix_shape": matrix_shape,
            "chip_origin": origin,
            "offset": offset,
            "inter_row": inter_row,
            "inter_column": inter_column,
        }

    def dashboard_scene(
        self,
        max_path_points: int = 256,
        max_droplet_cells: int = 1024,
    ) -> Dict[str, Any]:
        """Return the internal dashboard scene, using the shared execution scene builder."""
        scene = self.execution_scene(
            max_path_points=max_path_points,
            max_droplet_cells=max_droplet_cells,
            include_droplet_cells=True,
            include_paths=True,
            include_action_paths=True,
        )
        scene["surface"] = "dashboard_internal"
        scene["agent_visible"] = False
        try:
            scene["timeline"] = self._dashboard_scene_timeline()
        except Exception as exc:
            scene["timeline"] = {
                "available": False,
                "reason": "timeline_error",
                "error": str(exc),
            }
        return scene

    def _dashboard_scene_timeline(self) -> Dict[str, Any]:
        """Return frame-indexed plan data for the browser timeline scrubber."""
        system = self.system
        advanced_drop = getattr(system, "advanced_drop", None) if system is not None else None
        executor = getattr(advanced_drop, "executor", None) if advanced_drop is not None else None
        plan = getattr(advanced_drop, "plan", None) if advanced_drop is not None else None
        if plan is None and executor is not None:
            plan = getattr(executor, "current_plan", None)
        if plan is None and executor is not None:
            plan = getattr(executor, "last_applied_frame_plan", None)
        if plan is None:
            return {"available": False, "reason": "no_plan"}

        frames = list(getattr(plan, "frames", []) or [])
        frame_count = len(frames)
        if frame_count <= 0:
            return {"available": False, "reason": "empty_plan", "frame_count": 0}

        events = list(getattr(plan, "events", []) or [])
        event_ids_by_frame = list(getattr(plan, "event_id_per_frame", []) or [])
        active_by_frame = list(getattr(plan, "active_droplets_per_frame", []) or [])
        trajectories = getattr(plan, "droplet_trajectories", {}) or {}
        droplets = list(getattr(advanced_drop, "droplets", []) or [])
        cache_key = self._dashboard_scene_timeline_cache_key(
            plan,
            frames,
            events,
            event_ids_by_frame,
            active_by_frame,
            droplets,
            trajectories,
        )
        if self._dashboard_timeline_cache_key == cache_key and self._dashboard_timeline_cache is not None:
            return self._dashboard_timeline_cache

        event_type_by_id: Dict[str, str] = {}
        timeline_events: List[Dict[str, Any]] = []

        for index, event in enumerate(events):
            if not isinstance(event, (list, tuple)) or len(event) < 2:
                continue
            try:
                event_frame = int(event[0])
            except Exception:
                event_frame = 0
            event_type = str(event[1] or "action")
            data = event[2] if len(event) >= 3 and isinstance(event[2], dict) else {}
            event_id = data.get("event_id")
            if event_id is not None:
                event_type_by_id[str(event_id)] = event_type
            span = self._execution_scene_event_span(
                data=data,
                event_frame=event_frame,
                event_id=event_id,
                event_ids_by_frame=event_ids_by_frame,
                frame_count=frame_count,
            )
            if span is None:
                continue
            start, end = span
            event_key = str(event_id) if event_id is not None else f"{index + 1}:{event_type}:{start}-{end}"
            timeline_events.append(
                {
                    "id": event_key,
                    "event_id": self.to_jsonable(event_id),
                    "index": index,
                    "type": event_type,
                    "label": f"{index + 1}. {event_type}",
                    "frame_span": [start, end],
                    "frame_count": end - start + 1,
                    "droplet_ids": self._execution_scene_event_droplet_ids(data),
                    "data": self._execution_scene_compact_event_data(data),
                }
            )

        timeline_frames = []
        for frame_index, frame_matrix in enumerate(frames):
            event_id = event_ids_by_frame[frame_index] if frame_index < len(event_ids_by_frame) else None
            active_ids: List[int] = []
            if frame_index < len(active_by_frame):
                for raw_id in active_by_frame[frame_index] or []:
                    try:
                        active_ids.append(int(raw_id))
                    except Exception:
                        continue
            try:
                summary = self._matrix_compact_representation(
                    frame_matrix,
                    source="timeline_frame",
                    include_ranges=True,
                    include_active_cells=False,
                    include_hash=False,
                )
                summary = self._dashboard_scene_timeline_summary(summary)
            except Exception as exc:
                summary = {"source": "timeline_frame", "error": str(exc)}
            timeline_frames.append(
                {
                    "index": frame_index,
                    "event_id": self.to_jsonable(event_id),
                    "event_type": event_type_by_id.get(str(event_id), None) if event_id is not None else None,
                    "active_droplet_ids": sorted(set(active_ids)),
                    "droplets": self._dashboard_scene_timeline_frame_droplets(
                        droplets=droplets,
                        trajectories=trajectories,
                        active_ids=sorted(set(active_ids)),
                        frame_index=frame_index,
                    ),
                    "summary": summary,
                }
            )

        payload = {
            "available": True,
            "frame_count": frame_count,
            "event_count": len(timeline_events),
            "events": timeline_events,
            "frames": timeline_frames,
            "encoding": "per_frame_active_ranges",
        }
        self._dashboard_timeline_cache_key = cache_key
        self._dashboard_timeline_cache = payload
        return payload

    def _dashboard_scene_timeline_cache_key(
        self,
        plan: Any,
        frames: List[Any],
        events: List[Any],
        event_ids_by_frame: List[Any],
        active_by_frame: List[Any],
        droplets: List[Any],
        trajectories: Dict[Any, Any],
    ) -> Tuple[Any, ...]:
        last_event = events[-1] if events else None
        first_frame_id = id(frames[0]) if frames else None
        last_frame_id = id(frames[-1]) if frames else None
        droplet_key = []
        for droplet in droplets:
            try:
                shape = tuple(sorted((int(row), int(col)) for row, col in (getattr(droplet, "shape", set()) or set())))
                droplet_key.append(
                    (
                        int(getattr(droplet, "id")),
                        self.to_jsonable(getattr(droplet, "origin_corner", None)),
                        self.to_jsonable(getattr(droplet, "target_corner", None)),
                        shape,
                    )
                )
            except Exception:
                continue
        trajectory_key = []
        for raw_id, trajectory in (trajectories or {}).items():
            points = list(trajectory or [])
            trajectory_key.append(
                (
                    self.to_jsonable(raw_id),
                    len(points),
                    self.to_jsonable(points[0]) if points else None,
                    self.to_jsonable(points[-1]) if points else None,
                )
            )
        return (
            id(plan),
            len(frames),
            first_frame_id,
            last_frame_id,
            len(events),
            self.to_jsonable(last_event),
            len(event_ids_by_frame),
            len(active_by_frame),
            tuple(sorted(droplet_key)),
            tuple(sorted(trajectory_key, key=lambda item: str(item[0]))),
        )

    def _dashboard_scene_timeline_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Trim matrix summaries to the fields needed for dashboard replay."""
        if not isinstance(summary, dict):
            return {}
        keep = {
            "type",
            "source",
            "shape",
            "active_count",
            "active_bbox",
            "encoding",
            "zeros_are_implicit",
            "rows",
            "error",
        }
        return {key: summary[key] for key in keep if key in summary}

    def _dashboard_scene_timeline_frame_droplets(
        self,
        droplets: List[Any],
        trajectories: Dict[Any, Any],
        active_ids: List[int],
        frame_index: int,
    ) -> List[Dict[str, Any]]:
        """Return droplet shapes/positions for one timeline frame."""
        if not active_ids:
            return []

        try:
            from droplogic.utils.advanced_drop.common import get_droplet_positions
        except Exception:
            get_droplet_positions = None

        droplets_by_id: Dict[int, Any] = {}
        for droplet in droplets:
            try:
                droplets_by_id[int(getattr(droplet, "id"))] = droplet
            except Exception:
                continue

        result: List[Dict[str, Any]] = []
        for droplet_id in sorted(set(active_ids)):
            droplet = droplets_by_id.get(int(droplet_id))
            trajectory = self._execution_scene_trajectory(trajectories, int(droplet_id))
            fallback_position = getattr(droplet, "origin_corner", None) if droplet is not None else None
            position = self._execution_scene_position(trajectory, frame_index, fallback_position)
            if position is None:
                continue

            fallback_target = getattr(droplet, "target_corner", None) if droplet is not None else None
            target = self._execution_scene_target(trajectory, fallback_target) or position
            shape = sorted(
                [[int(row), int(col)] for row, col in (getattr(droplet, "shape", set()) or set())]
            ) if droplet is not None else [[0, 0]]
            if not shape:
                shape = [[0, 0]]

            cells = [[position[0] + offset[0], position[1] + offset[1]] for offset in shape]
            if get_droplet_positions is not None and droplet is not None:
                try:
                    cells = sorted(
                        [[int(row), int(col)] for row, col in get_droplet_positions(droplet, tuple(position))]
                    )
                except Exception:
                    pass

            result.append(
                {
                    "id": int(droplet_id),
                    "position": self.to_jsonable(position),
                    "origin": self.to_jsonable(fallback_position or position),
                    "target": self.to_jsonable(target),
                    "active": True,
                    "shape": self.to_jsonable(shape),
                    "shape_size": len(shape),
                    "cells": self.to_jsonable(cells),
                    "cells_truncated": False,
                    "bbox": self._execution_scene_bbox(cells),
                    "target_bbox": None,
                    "path_length": len(trajectory),
                }
            )
        return result

    def _execution_scene_frame_index(
        self,
        executor_status: Optional[Dict[str, Any]],
        frame_count: int,
    ) -> Optional[int]:
        if frame_count <= 0:
            return None
        status = executor_status if isinstance(executor_status, dict) else {}
        last_frame = status.get("last_frame") if isinstance(status.get("last_frame"), dict) else {}
        last_index = last_frame.get("index")
        if isinstance(last_index, (int, float)) and 0 <= int(last_index) < frame_count:
            return int(last_index)
        current = status.get("current_frame", 0)
        try:
            current_index = int(current)
        except Exception:
            current_index = 0
        return max(0, min(frame_count - 1, current_index))

    def _execution_scene_frame_source(
        self,
        executor: Any,
        executor_status: Optional[Dict[str, Any]],
        frames: List[Any],
        matrix_summary: Optional[Dict[str, Any]],
    ) -> Tuple[Optional[int], Any, str]:
        frame_count = len(frames)
        status = executor_status if isinstance(executor_status, dict) else {}
        applied = status.get("last_applied_frame") if isinstance(status.get("last_applied_frame"), dict) else {}
        applied_index = applied.get("index")
        applied_matrix = getattr(executor, "last_applied_frame_matrix", None) if executor is not None else None
        if applied_matrix is not None and isinstance(applied_index, (int, float)) and int(applied_index) >= 0:
            if (
                isinstance(matrix_summary, dict)
                and matrix_summary.get("error") is None
                and not self._execution_scene_matrix_matches_summary(applied_matrix, matrix_summary)
            ):
                return None, None, "state"
            return int(applied_index), applied_matrix, "executor_last_applied_frame"

        # Before the executor has applied any frame, the only truthful matrix
        # state is the live hardware/runtime state. Do not show future planned
        # frames as if they had executed.
        if isinstance(matrix_summary, dict) and matrix_summary.get("error") is None:
            return None, None, "state"

        frame_index = self._execution_scene_frame_index(executor_status, frame_count)
        if frame_index is not None and 0 <= frame_index < frame_count:
            return frame_index, frames[frame_index], "plan_frame_fallback"
        return None, None, "none"

    def _execution_scene_matrix_matches_summary(
        self,
        matrix: Any,
        summary: Dict[str, Any],
    ) -> bool:
        expected_hash = summary.get("active_mask_sha256")
        if not expected_hash:
            return True
        try:
            array = np.asarray(matrix)
            if array.ndim != 2:
                return False
            active_mask = array != 0
            contiguous = np.ascontiguousarray(active_mask.astype(np.uint8))
            return hashlib.sha256(contiguous.tobytes()).hexdigest() == expected_hash
        except Exception:
            return True

    def _execution_scene_droplets(
        self,
        advanced_drop: Any,
        plan: Any,
        frame_index: Optional[int],
        executed_frame: bool,
        max_path_points: int,
        max_droplet_cells: int,
        include_droplet_cells: bool,
        include_paths: bool,
    ) -> List[Dict[str, Any]]:
        if not executed_frame or frame_index is None:
            return []

        droplets = getattr(advanced_drop, "droplets", None) or []
        trajectories = getattr(plan, "droplet_trajectories", {}) or {}
        trajectory_ids = set()
        for raw_id, trajectory in trajectories.items():
            if not trajectory:
                continue
            try:
                trajectory_ids.add(int(raw_id))
            except Exception:
                continue
        active_by_frame = getattr(plan, "active_droplets_per_frame", []) or []
        has_active_frame = frame_index is not None and 0 <= frame_index < len(active_by_frame)
        active_ids = set()
        if has_active_frame:
            for item in active_by_frame[frame_index] or []:
                try:
                    active_ids.add(int(item))
                except Exception:
                    continue
            if not active_ids:
                return []
        targets_reached = getattr(plan, "targets_reached", {}) or {}

        try:
            from droplogic.utils.advanced_drop.common import get_droplet_positions
        except Exception:
            get_droplet_positions = None

        result = []
        for droplet in droplets:
            droplet_id = int(getattr(droplet, "id", len(result)))
            trajectory = self._execution_scene_trajectory(trajectories, droplet_id)
            if trajectory_ids and droplet_id not in trajectory_ids:
                continue
            if has_active_frame and droplet_id not in active_ids:
                continue
            position = self._execution_scene_position(
                trajectory,
                frame_index,
                getattr(droplet, "origin_corner", None),
            )
            target = self._execution_scene_target(
                trajectory,
                getattr(droplet, "target_corner", None),
            )
            shape = sorted(
                [[int(row), int(col)] for row, col in (getattr(droplet, "shape", set()) or set())]
            )
            cells = []
            cells_truncated = False
            bbox = None
            target_bbox = None
            if get_droplet_positions is not None and position is not None:
                try:
                    raw_cells = sorted(
                        [[int(row), int(col)] for row, col in get_droplet_positions(droplet, tuple(position))]
                    )
                    if include_droplet_cells:
                        limit = max(0, int(max_droplet_cells))
                        cells = raw_cells[:limit]
                        cells_truncated = len(raw_cells) > limit
                    bbox = self._execution_scene_bbox(raw_cells)
                except Exception:
                    cells = []
            if get_droplet_positions is not None and target is not None:
                try:
                    target_cells = sorted(
                        [[int(row), int(col)] for row, col in get_droplet_positions(droplet, tuple(target))]
                    )
                    target_bbox = self._execution_scene_bbox(target_cells)
                except Exception:
                    target_bbox = None

            at_target = bool(position is not None and target is not None and tuple(position) == tuple(target))
            planned_target_reached = bool(
                targets_reached.get(droplet_id) or targets_reached.get(str(droplet_id), False)
            )

            result.append(
                {
                    "id": droplet_id,
                    "position": self.to_jsonable(position),
                    "origin": self.to_jsonable(getattr(droplet, "origin_corner", None)),
                    "target": self.to_jsonable(target),
                    "active": True,
                    "at_target": at_target,
                    "target_reached": at_target,
                    "planned_target_reached": planned_target_reached,
                    "priority": self.to_jsonable(getattr(droplet, "priority", None)),
                    "vital_space": self.to_jsonable(getattr(droplet, "vital_space", None)),
                    "shape": shape,
                    "shape_size": len(shape),
                    "cells": cells,
                    "cells_truncated": cells_truncated,
                    "bbox": bbox,
                    "target_bbox": target_bbox,
                    "path": self._execution_scene_compact_path(trajectory, max_path_points=max_path_points)
                    if include_paths
                    else [],
                    "path_included": bool(include_paths),
                    "path_length": len(trajectory),
                }
            )
        return result

    def _execution_scene_action_paths(
        self,
        plan: Any,
        max_path_points: int = 256,
    ) -> List[Dict[str, Any]]:
        if plan is None:
            return []
        events = list(getattr(plan, "events", []) or [])
        trajectories = getattr(plan, "droplet_trajectories", {}) or {}

        frame_count = len(getattr(plan, "frames", []) or [])
        if frame_count <= 0:
            try:
                frame_count = max(len(list(trajectory or [])) for trajectory in trajectories.values())
            except ValueError:
                frame_count = 0
        event_ids_by_frame = list(getattr(plan, "event_id_per_frame", []) or [])
        actions: List[Dict[str, Any]] = []

        for index, event in enumerate(events):
            if not isinstance(event, (list, tuple)) or len(event) < 2:
                continue
            try:
                event_frame = int(event[0])
            except Exception:
                event_frame = 0
            event_type = str(event[1] or "action")
            data = event[2] if len(event) >= 3 and isinstance(event[2], dict) else {}
            event_id = data.get("event_id")
            span = self._execution_scene_event_span(
                data=data,
                event_frame=event_frame,
                event_id=event_id,
                event_ids_by_frame=event_ids_by_frame,
                frame_count=frame_count,
            )
            if span is None:
                continue
            start, end = span
            mentioned_droplets = set(self._execution_scene_event_droplet_ids(data))
            paths = []

            for raw_id, trajectory in trajectories.items():
                try:
                    droplet_id = int(raw_id)
                except Exception:
                    continue
                segment = self._execution_scene_trajectory_segment(
                    list(trajectory or []),
                    start,
                    end,
                )
                path = self._execution_scene_compact_path(
                    segment,
                    max_path_points=max_path_points,
                )
                if not path:
                    continue
                moving = len(path) > 1
                if not moving and droplet_id not in mentioned_droplets:
                    continue
                mentioned_droplets.add(droplet_id)
                paths.append(
                    {
                        "key": f"{event_id if event_id is not None else index}:{droplet_id}",
                        "droplet_id": droplet_id,
                        "path": path,
                        "path_length": len(segment),
                        "start": path[0],
                        "end": path[-1],
                    }
                )

            action_id = str(event_id) if event_id is not None else f"{index + 1}:{event_type}:{start}-{end}"
            actions.append(
                {
                    "id": action_id,
                    "event_id": self.to_jsonable(event_id),
                    "index": index,
                    "type": event_type,
                    "label": f"{index + 1}. {event_type}",
                    "frame_span": [start, end],
                    "frame_count": end - start + 1,
                    "droplet_ids": sorted(mentioned_droplets),
                    "paths": paths,
                    "data": self._execution_scene_compact_event_data(data),
                }
            )

        if actions:
            return actions

        fallback = self._execution_scene_trajectory_actions(
            trajectories,
            frame_count=frame_count,
            max_path_points=max_path_points,
        )
        return fallback or actions

    def _execution_scene_has_moving_action(self, actions: List[Dict[str, Any]]) -> bool:
        for action in actions:
            for path_info in action.get("paths") or []:
                if len(self._execution_scene_distinct_points(path_info.get("path"))) > 1:
                    return True
        return False

    def _execution_scene_trajectory_actions(
        self,
        trajectories: Dict[Any, Any],
        frame_count: int,
        max_path_points: int = 256,
    ) -> List[Dict[str, Any]]:
        paths = []
        droplet_ids = []
        for raw_id, trajectory in trajectories.items():
            try:
                droplet_id = int(raw_id)
            except Exception:
                continue
            full_trajectory = list(trajectory or [])
            path = self._execution_scene_compact_path(
                full_trajectory,
                max_path_points=max_path_points,
            )
            if len(self._execution_scene_distinct_points(path)) <= 1:
                continue
            droplet_ids.append(droplet_id)
            paths.append(
                {
                    "key": f"trajectory:{droplet_id}",
                    "droplet_id": droplet_id,
                    "path": path,
                    "path_length": len(full_trajectory),
                    "start": path[0],
                    "end": path[-1],
                    "synthetic": True,
                }
            )

        if not paths:
            return []
        end_frame = max(0, frame_count - 1)
        return [
            {
                "id": "planned-trajectories",
                "event_id": None,
                "index": None,
                "type": "trajectory",
                "label": "Planned trajectories",
                "frame_span": [0, end_frame],
                "frame_count": end_frame + 1,
                "droplet_ids": sorted(droplet_ids),
                "paths": paths,
                "data": {"synthetic": True, "source": "droplet_trajectories"},
            }
        ]

    def _execution_scene_distinct_points(self, path: Any) -> List[List[int]]:
        points = []
        previous = None
        for item in path or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            try:
                point = [int(item[0]), int(item[1])]
            except Exception:
                continue
            if previous == point:
                continue
            points.append(point)
            previous = point
        return points

    def _execution_scene_event_span(
        self,
        data: Dict[str, Any],
        event_frame: int,
        event_id: Any,
        event_ids_by_frame: List[Any],
        frame_count: int,
    ) -> Optional[Tuple[int, int]]:
        frame_span = data.get("frame_span") if isinstance(data, dict) else None
        if isinstance(frame_span, (list, tuple)) and len(frame_span) >= 2:
            try:
                start = int(frame_span[0])
                end = int(frame_span[1])
                return self._clamp_execution_scene_span(start, end, frame_count)
            except Exception:
                pass

        if event_id is not None and event_ids_by_frame:
            matches = [
                index
                for index, item in enumerate(event_ids_by_frame)
                if item == event_id or str(item) == str(event_id)
            ]
            if matches:
                return self._clamp_execution_scene_span(min(matches), max(matches), frame_count)

        return self._clamp_execution_scene_span(event_frame, event_frame, frame_count)

    def _clamp_execution_scene_span(
        self,
        start: int,
        end: int,
        frame_count: int,
    ) -> Optional[Tuple[int, int]]:
        if frame_count <= 0:
            return None
        lo = max(0, min(int(start), int(end)))
        hi = min(frame_count - 1, max(int(start), int(end)))
        if lo > hi:
            return None
        return lo, hi

    def _execution_scene_trajectory_segment(
        self,
        trajectory: List[Any],
        start: int,
        end: int,
    ) -> List[Any]:
        if not trajectory:
            return []
        lo = max(0, min(len(trajectory) - 1, int(start)))
        hi = max(0, min(len(trajectory) - 1, int(end)))
        if lo > hi:
            lo, hi = hi, lo
        return trajectory[lo : hi + 1]

    def _execution_scene_event_droplet_ids(self, value: Any, key: str = "") -> List[int]:
        found: List[int] = []
        key_mentions_droplet = "droplet" in str(key).lower()
        if key_mentions_droplet and isinstance(value, (int, float, str)):
            try:
                found.append(int(value))
            except Exception:
                pass
        elif isinstance(value, dict):
            for child_key, child_value in value.items():
                found.extend(self._execution_scene_event_droplet_ids(child_value, str(child_key)))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                found.extend(self._execution_scene_event_droplet_ids(item, key))
        return sorted(set(found))

    def _execution_scene_compact_event_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        compact: Dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key in {"event_id", "frame_span"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[str(key)] = value
            elif isinstance(value, (list, tuple, set)) and len(value) <= 16:
                compact[str(key)] = self.to_jsonable(value)
            elif isinstance(value, dict) and len(value) <= 12:
                compact[str(key)] = self.to_jsonable(value)
            else:
                compact[str(key)] = {
                    "type": type(value).__name__,
                    "omitted": True,
                }
        return compact

    def _execution_scene_trajectory(self, trajectories: Dict[Any, Any], droplet_id: int) -> List[Any]:
        trajectory = trajectories.get(droplet_id)
        if trajectory is None:
            trajectory = trajectories.get(str(droplet_id))
        return list(trajectory or [])

    def _execution_scene_position(
        self,
        trajectory: List[Any],
        frame_index: Optional[int],
        fallback: Any,
    ) -> Optional[List[int]]:
        value = None
        if trajectory and frame_index is not None:
            value = trajectory[max(0, min(len(trajectory) - 1, int(frame_index)))]
        if value is None:
            value = fallback
        if value is None:
            return None
        items = list(value)
        if len(items) < 2:
            return None
        return [int(items[0]), int(items[1])]

    def _execution_scene_target(
        self,
        trajectory: List[Any],
        fallback: Any,
    ) -> Optional[List[int]]:
        if trajectory:
            return self._execution_scene_position(
                trajectory,
                len(trajectory) - 1,
                fallback,
            )
        return self._execution_scene_position([], None, fallback)

    def _execution_scene_bbox(self, cells: List[List[int]]) -> Optional[Dict[str, int]]:
        if not cells:
            return None
        rows = [int(cell[0]) for cell in cells]
        cols = [int(cell[1]) for cell in cells]
        return {
            "row_min": min(rows),
            "row_max": max(rows),
            "col_min": min(cols),
            "col_max": max(cols),
        }

    def _execution_scene_compact_path(
        self,
        trajectory: List[Any],
        max_path_points: int = 256,
    ) -> List[List[int]]:
        points = []
        previous = None
        for item in trajectory:
            if item is None:
                continue
            values = list(item)
            if len(values) < 2:
                continue
            point = [int(values[0]), int(values[1])]
            if point != previous:
                points.append(point)
                previous = point
        limit = max(2, int(max_path_points or 256))
        if len(points) <= limit:
            return points
        if limit <= 2:
            return [points[0], points[-1]]
        keep = [points[0]]
        interior_count = limit - 2
        stride = max(1, int(np.ceil((len(points) - 2) / interior_count)))
        keep.extend(points[1:-1:stride][:interior_count])
        keep.append(points[-1])
        return keep

    def _execution_scene_current_event(self, plan: Any, frame_index: Optional[int]) -> Optional[Any]:
        if plan is None or frame_index is None:
            return None
        event_id_per_frame = getattr(plan, "event_id_per_frame", []) or []
        event_id = None
        if 0 <= frame_index < len(event_id_per_frame):
            event_id = event_id_per_frame[frame_index]
        events = getattr(plan, "events", []) or []
        if event_id is not None:
            for event in events:
                data = event[2] if len(event) >= 3 else {}
                if isinstance(data, dict) and data.get("event_id") == event_id:
                    return self.to_jsonable(event)
        for event in events:
            if not event:
                continue
            try:
                event_frame = int(event[0])
            except Exception:
                continue
            data = event[2] if len(event) >= 3 else {}
            frame_span = data.get("frame_span") if isinstance(data, dict) else None
            if isinstance(frame_span, (list, tuple)) and len(frame_span) >= 2:
                if int(frame_span[0]) <= frame_index <= int(frame_span[1]):
                    return self.to_jsonable(event)
            if event_frame == frame_index:
                return self.to_jsonable(event)
        return None

    def write_dashboard_scene_snapshot(self) -> None:
        """Write an internal dashboard scene file without affecting MCP calls."""
        path = (self.dashboard_scene_path or "").strip()
        if not path:
            return
        output_path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
        try:
            scene = self.dashboard_scene()
        except Exception:
            scene = {
                "available": False,
                "reason": "scene_snapshot_error",
                "updated_at": time.time(),
            }
        try:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            temp_path = f"{output_path}.{os.getpid()}.tmp"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(
                    self.to_jsonable(scene),
                    handle,
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
            os.replace(temp_path, output_path)
        except Exception:
            pass

    def save_protocol(self, output_path: str) -> Dict[str, Any]:
        """Save the current plan and droplets to a pickle protocol file."""
        advanced_drop = self.require_advanced_drop()
        output_path = os.path.abspath(os.fspath(output_path))
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        payload = {
            "plan": advanced_drop.plan,
            "droplets": list(advanced_drop.droplets),
        }
        with open(output_path, "wb") as handle:
            pickle.dump(payload, handle)

        return {
            "path": output_path,
            "droplets": self.to_jsonable(advanced_drop.droplets.get_droplets_summary()),
            "plan": self.plan_summary(advanced_drop.plan),
        }

    # ---------------------------------------------------------------------
    # Unsafe/system tools

    def set_system_state(self, path: str, value: Any) -> Dict[str, Any]:
        """Set a DropSystem state path. Disabled unless unsafe tools are enabled."""
        if not self.allow_unsafe_tools:
            raise DropLogicMCPError(
                "set_system_state is disabled. Restart with --allow-unsafe-tools "
                "if you intentionally want raw state writes."
            )
        system = self.require_system()
        result = system.update_state(path, value)
        return self.to_jsonable(result)

    def emergency_stop(self, deactivate_electrodes: bool = True) -> Dict[str, Any]:
        """Stop execution, clear hardware queues and optionally deactivate electrodes."""
        system = self.require_system()
        with self._lock:
            advanced_drop = getattr(system, "advanced_drop", None)
            executor = getattr(advanced_drop, "executor", None) if advanced_drop else None
            if executor is not None:
                executor.stop()

            if hasattr(system, "emergency_stop"):
                system.emergency_stop()

            deactivated = False
            if deactivate_electrodes:
                try:
                    electrode_config = system.state.get("electrode_matrix", {})
                    rows = int(electrode_config.get("rows", 128))
                    columns = int(electrode_config.get("columns", 128))
                    zeros = np.zeros((rows, columns), dtype=int).tolist()
                    system.update_state("electrode_matrix.matrix", zeros)
                    deactivated = True
                except Exception:
                    deactivated = False

            return {
                "stopped": True,
                "deactivated_electrodes": deactivated,
                "status": self.status(),
            }

    # ---------------------------------------------------------------------
    # Internals and serialization

    def _record_error(self, context: str, exc: Exception) -> None:
        self.last_error = {
            "timestamp": time.time(),
            "context": context,
            "type": type(exc).__name__,
            "message": str(exc),
        }

    def _real_hardware_lock_key(self, system_key: str) -> Optional[str]:
        name = (system_key or "").lower()
        if name in {"boxmini", "box_mini", "box_mini1"}:
            return "boxmini"
        if name == "dmlite":
            return "dmlite"
        return None

    def _acquire_real_hardware_lock(self, system_key: str) -> None:
        """Prevent multiple MCP runtimes from owning the same real hardware."""
        hardware_key = self._real_hardware_lock_key(system_key)
        if hardware_key is None:
            return
        if self._real_hardware_lock_handle is not None:
            return

        lock_path = os.path.join(tempfile.gettempdir(), f"droplogic_mcp_{hardware_key}.lock")
        if not os.path.exists(lock_path):
            open(lock_path, "w", encoding="utf-8").close()
        handle = open(lock_path, "r+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                if os.path.getsize(lock_path) == 0:
                    handle.seek(0)
                    handle.write(" ")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise DropLogicMCPError(
                        f"Another DropLogic MCP runtime already owns {hardware_key}. "
                        "Close the old Claude/MCP session before loading real hardware again."
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise DropLogicMCPError(
                        f"Another DropLogic MCP runtime already owns {hardware_key}. "
                        "Close the old Claude/MCP session before loading real hardware again."
                    ) from exc

            handle.seek(0)
            handle.truncate()
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "session_id": self.session_id,
                        "hardware": hardware_key,
                        "acquired_at": time.time(),
                    }
                )
            )
            handle.flush()
            self._real_hardware_lock_handle = handle
            self._real_hardware_lock_path = lock_path
            self._real_hardware_lock_system = hardware_key
        except Exception:
            try:
                handle.close()
            except Exception:
                pass
            raise

    def _release_real_hardware_lock(self) -> None:
        handle = self._real_hardware_lock_handle
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                handle.close()
            except Exception:
                pass
            self._real_hardware_lock_handle = None
            self._real_hardware_lock_path = None
            self._real_hardware_lock_system = None

    def _wait_or_report_busy(
        self,
        module_key: str,
        wait_if_busy: bool = False,
        timeout_seconds: float = 0.0,
        poll_interval: float = 0.1,
    ) -> Optional[Dict[str, Any]]:
        status = self._module_busy_status(module_key)
        if not status["busy"]:
            return None

        if wait_if_busy:
            wait_result = self.wait_for_module_free(
                module_key,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
            if wait_result.get("ok"):
                return None
            return {
                "timed_out": True,
                "status": wait_result.get("status", status),
            }

        return {
            "timed_out": False,
            "status": status,
        }

    def _module_busy_status(self, module_key: str) -> Dict[str, Any]:
        system = self.require_system()
        module_instance = getattr(system, module_key, None)
        reasons = []

        if module_instance is None and not self._module_logically_available(module_key):
            return {
                "available": False,
                "busy": False,
                "reasons": ["module is not available on the loaded system"],
                "queue": self._hardware_queue_summary(),
                "executor_active": self._executor_active(),
            }

        if module_key in self.EXECUTOR_OWNED_MODULES and self._executor_active():
            reasons.append("PlanExecutor is actively executing frames")

        queue_summary = self._hardware_queue_summary()
        if queue_summary["pending_commands"] > 0:
            reasons.append(
                f"hardware command queue has {queue_summary['pending_commands']} pending command(s)"
            )

        if module_key == "xy_stage":
            stage_reason = self._stage_motion_busy(module_instance)
            if stage_reason:
                reasons.append(stage_reason)

        if module_key in {"camera", "microscope"} and self._streamer_running():
            reasons.append("StreamerVisualizer is running and may be reading live frames")

        lock_reason = self._probe_lock_busy(module_key)
        if lock_reason:
            reasons.append(lock_reason)

        return {
            "available": module_instance is not None or self._module_logically_available(module_key),
            "busy": bool(reasons),
            "reasons": reasons,
            "queue": queue_summary,
            "executor_active": self._executor_active(),
        }

    def _module_logically_available(self, module_key: str) -> bool:
        system = self.system
        if system is None:
            return False

        if module_key == "electrode_matrix":
            state = getattr(system, "state", {})
            return (
                isinstance(state, dict)
                and "electrode_matrix" in state
            ) or hasattr(system, "_electrode_lock") or hasattr(system, "_electrode_matrix_lock")

        if module_key == "xy_stage":
            return hasattr(system, "xy_stage") and getattr(system, "xy_stage") is not None

        return False

    def _executor_active(self) -> bool:
        system = self.system
        if system is None or not hasattr(system, "advanced_drop"):
            return False
        executor = getattr(system.advanced_drop, "executor", None)
        if executor is None:
            return False
        try:
            status = executor.status()
            return bool(status.get("is_executing"))
        except Exception:
            return False

    def _hardware_queue_summary(self) -> Dict[str, Any]:
        system = self.system
        if system is None or not hasattr(system, "get_queue_status"):
            return {"pending_commands": 0, "queues": {}, "last_command_errors": []}

        try:
            queues = system.get_queue_status()
        except Exception:
            return {"pending_commands": 0, "queues": {}, "last_command_errors": []}

        pending = 0
        last_command_errors = []
        for item in queues.values():
            try:
                pending += int(item.get("unfinished_tasks", item.get("queue_size", 0)) or 0)
            except Exception:
                pass
            if isinstance(item, dict) and item.get("last_command_error"):
                last_command_errors.append(item["last_command_error"])
        return {
            "pending_commands": pending,
            "queues": self.to_jsonable(queues),
            "last_command_errors": self.to_jsonable(last_command_errors),
        }

    def _wait_for_hardware_queue_empty(
        self,
        timeout_seconds: float = 10.0,
        poll_interval: float = 0.05,
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        wait_started_at = time.time()
        poll_interval = max(0.01, float(poll_interval))
        last_summary = self._hardware_queue_summary()

        while True:
            pending = int(last_summary.get("pending_commands", 0) or 0)
            if pending <= 0:
                last_command_errors = [
                    error for error in last_summary.get("last_command_errors", [])
                    if error.get("processed_at") is None
                    or float(error.get("processed_at")) >= wait_started_at
                ]
                if last_command_errors:
                    return {
                        "ok": False,
                        "timed_out": False,
                        "pending_commands": 0,
                        "hardware_errors": last_command_errors,
                        "queues": last_summary.get("queues", {}),
                    }
                return {
                    "ok": True,
                    "timed_out": False,
                    "pending_commands": 0,
                    "queues": last_summary.get("queues", {}),
                }

            if time.monotonic() >= deadline:
                return {
                    "ok": False,
                    "timed_out": True,
                    "pending_commands": pending,
                    "queues": last_summary.get("queues", {}),
                }

            time.sleep(poll_interval)
            last_summary = self._hardware_queue_summary()

    def _stage_motion_busy(self, module_instance) -> Optional[str]:
        if module_instance is None or not hasattr(module_instance, "is_motion_complete"):
            return None

        busy_axes = []
        for axis in ("X", "Y", "Z"):
            try:
                if not bool(module_instance.is_motion_complete(axis)):
                    busy_axes.append(axis)
            except Exception:
                continue
        if busy_axes:
            return f"XY stage motion is not complete on axis/axes: {', '.join(busy_axes)}"
        return None

    def _streamer_running(self) -> bool:
        system = self.system
        if system is None:
            return False
        try:
            streamer = self._get_visualizer_instance(system, "streamer")
        except Exception:
            return False
        if streamer is None or not hasattr(streamer, "is_running"):
            return False
        try:
            return bool(streamer.is_running())
        except Exception:
            return False

    def _probe_lock_busy(self, module_key: str) -> Optional[str]:
        system = self.system
        if system is None:
            return None

        lock_names_by_module = {
            "electrode_matrix": ("_electrode_matrix_lock", "_electrode_lock"),
            "xy_stage": ("_xy_stage_lock",),
        }
        for lock_name in lock_names_by_module.get(module_key, ()):
            lock = getattr(system, lock_name, None)
            if lock is None or not hasattr(lock, "acquire"):
                continue

            acquired = lock.acquire(blocking=False)
            if acquired:
                try:
                    lock.release()
                except Exception:
                    pass
            else:
                return f"internal {lock_name} is currently held"

        return None

    def _describe_methods(
        self,
        instance,
        method_names,
        unsafe_pairs=None,
        module_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if instance is None:
            return {}

        unsafe_pairs = unsafe_pairs or set()
        methods = {}
        for method_name in sorted(method_names):
            func = getattr(instance, method_name, None)
            if func is None:
                continue
            try:
                signature = str(inspect.signature(func))
            except Exception:
                signature = "(...)"
            unsafe = (
                module_name is not None
                and (module_name, method_name) in unsafe_pairs
            )
            methods[method_name] = {
                "signature": signature,
                "doc": inspect.getdoc(func) or "",
                "requires_allow_unsafe_tools": bool(unsafe),
            }
        return methods

    def _normalize_visualizer_name(self, visualizer: str) -> str:
        name = (visualizer or "matrix").lower()
        if name in {"matrix", "electrode_matrix"}:
            return "matrix"
        if name in {"streamer", "stream", "camera"}:
            return "streamer"
        raise DropLogicMCPError("visualizer must be matrix or streamer.")

    def _normalize_streamer_source(self, source: str) -> str:
        name = (source or "microscope").strip().lower()
        if name in {"microscope", "scope", "micro"}:
            return "microscope"
        if name in {"camera", "cam"}:
            return "camera"
        raise DropLogicMCPError("streamer_source/source must be microscope or camera.")

    def _normalize_execution_view_mode(self, mode: str) -> str:
        name = (mode or "follow_droplets").strip().lower()
        if name in {"follow", "follow_droplets", "track", "track_droplets", "droplet_tracking"}:
            return "follow_droplets"
        if name in {"whole_chip_camera", "camera_overview", "overview", "whole_chip"}:
            return "whole_chip_camera"
        if name in {"fixed", "fixed_stage"}:
            return "fixed_stage"
        raise DropLogicMCPError(
            "execution_view_mode/mode must be follow_droplets, whole_chip_camera, or fixed_stage."
        )

    def _executor_stage_mode_for_view(
        self,
        view_mode: str,
        fixed_stage_position: Optional[Any] = None,
    ):
        if view_mode == "follow_droplets":
            return "follow_droplets", None
        if view_mode == "whole_chip_camera":
            preset = self._get_named_preset("imaging", "whole_chip_camera")
            return "fixed_stage", self._normalize_stage_position(
                fixed_stage_position or preset.get("position")
            )
        return "fixed_stage", self._normalize_stage_position(fixed_stage_position)

    def _get_named_preset(self, *keys: str) -> Dict[str, Any]:
        state = getattr(self.require_system(), "state", {}) or {}
        current = state.get("presets", {})
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                dotted = ".".join(("presets",) + keys)
                raise DropLogicMCPError(f"Missing config preset: {dotted}")
            current = current[key]
        if not isinstance(current, dict):
            dotted = ".".join(("presets",) + keys)
            raise DropLogicMCPError(f"Config preset is not an object: {dotted}")
        return dict(current)

    def _get_stage_move_preset(self, preset: str) -> Dict[str, Any]:
        name = str(preset or "").strip().lower().replace("/", ".")
        aliases = {
            "inject": "stage.manual_injection",
            "injection": "stage.manual_injection",
            "load": "stage.manual_injection",
            "loading": "stage.manual_injection",
            "manual_injection": "stage.manual_injection",
            "manual-injection": "stage.manual_injection",
            "manual injection": "stage.manual_injection",
            "camera_overview": "imaging.whole_chip_camera",
            "overview": "imaging.whole_chip_camera",
            "whole_chip": "imaging.whole_chip_camera",
            "whole_chip_camera": "imaging.whole_chip_camera",
            "whole-chip-camera": "imaging.whole_chip_camera",
        }
        dotted = aliases.get(name, name)
        if dotted.startswith("presets."):
            dotted = dotted[len("presets."):]
        parts = [part for part in dotted.split(".") if part]
        if len(parts) == 1:
            # Stage presets are the common case for direct movement.
            parts = ["stage", parts[0]]
        if len(parts) != 2 or parts[0] not in {"stage", "imaging"}:
            raise DropLogicMCPError(
                "Stage preset must be a known preset such as manual_injection, "
                "stage.manual_injection, whole_chip_camera, or imaging.whole_chip_camera."
            )
        preset_data = self._get_named_preset(parts[0], parts[1])
        if not isinstance(preset_data.get("position"), dict):
            raise DropLogicMCPError(f"Preset '{preset}' does not define a stage position.")
        return preset_data

    def _normalize_stage_axis_update(self, position: Any) -> Dict[str, int]:
        if position is None:
            raise DropLogicMCPError("move_stage requires either position or preset.")
        if isinstance(position, dict):
            normalized = {}
            for key, value in position.items():
                axis = str(key).upper()
                if axis not in {"X", "Y", "Z"}:
                    raise DropLogicMCPError(
                        "Stage position keys must be X, Y, and/or Z."
                    )
                normalized[axis] = int(round(float(value)))
            if not normalized:
                raise DropLogicMCPError("Stage position cannot be empty.")
            return normalized
        if isinstance(position, (list, tuple)) and len(position) >= 3:
            return {
                "X": int(round(float(position[0]))),
                "Y": int(round(float(position[1]))),
                "Z": int(round(float(position[2]))),
            }
        raise DropLogicMCPError(
            "Stage position must be a dict with X/Y/Z axes or a 3-item list."
        )

    def _normalize_stage_position(self, position: Any) -> Dict[str, int]:
        if position is None:
            raise DropLogicMCPError("fixed_stage_position/position is required.")
        if isinstance(position, dict):
            return {
                "X": int(round(float(position["X"]))),
                "Y": int(round(float(position["Y"]))),
                "Z": int(round(float(position["Z"]))),
            }
        if isinstance(position, (list, tuple)) and len(position) >= 3:
            return {
                "X": int(round(float(position[0]))),
                "Y": int(round(float(position[1]))),
                "Z": int(round(float(position[2]))),
            }
        raise DropLogicMCPError("Stage position must be a dict with X/Y/Z or a 3-item list.")

    def _actions_ok(self, actions: List[Dict[str, Any]]) -> bool:
        for action in actions:
            if not isinstance(action, dict):
                continue
            for value in action.values():
                if isinstance(value, dict) and value.get("ok") is False:
                    return False
                if isinstance(value, dict) and value.get("success") is False:
                    return False
                if isinstance(value, dict):
                    result = value.get("result")
                    if isinstance(result, dict) and result.get("success") is False:
                        return False
            if action.get("ok") is False or action.get("success") is False:
                return False
            result = action.get("result")
            if isinstance(result, dict) and result.get("success") is False:
                return False
        return True

    def _execution_view_ready_status(
        self,
        view_mode: str,
        view_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if view_result is None:
            return {"ready": True, "reason": None}
        if not view_result.get("ok", False):
            return {
                "ready": False,
                "reason": "view_prepare_failed",
                "view_mode": view_mode,
                "view_result": self.to_jsonable(view_result),
            }

        if view_mode == "follow_droplets":
            return {"ready": True, "reason": None, "view_mode": view_mode}

        move_result = None
        for action in view_result.get("actions", []) or []:
            if isinstance(action, dict) and isinstance(action.get("move_stage"), dict):
                move_result = action["move_stage"]
                break

        if move_result is None:
            return {
                "ready": False,
                "reason": "missing_fixed_stage_move",
                "view_mode": view_mode,
                "view_result": self.to_jsonable(view_result),
            }
        if not move_result.get("ok", False) or not move_result.get("motion_complete", False):
            return {
                "ready": False,
                "reason": "fixed_stage_move_incomplete",
                "view_mode": view_mode,
                "move_stage": self.to_jsonable(move_result),
            }

        target = move_result.get("target_position") or move_result.get("position")
        actual = move_result.get("actual_position")
        if actual is not None and not self._stage_positions_close(target, actual):
            return {
                "ready": False,
                "reason": "fixed_stage_target_not_reached",
                "view_mode": view_mode,
                "target_position": target,
                "actual_position": actual,
                "move_stage": self.to_jsonable(move_result),
            }
        return {
            "ready": True,
            "reason": None,
            "view_mode": view_mode,
            "move_stage": self.to_jsonable(move_result),
        }

    def _stage_positions_close(
        self,
        target: Optional[Dict[str, Any]],
        actual: Optional[Dict[str, Any]],
        tolerance_steps: int = 100,
    ) -> bool:
        if target is None or actual is None:
            return True
        try:
            for axis in ("X", "Y", "Z"):
                if axis not in target or axis not in actual:
                    continue
                if abs(int(actual[axis]) - int(target[axis])) > int(tolerance_steps):
                    return False
            return True
        except Exception:
            return True

    def _apply_whole_chip_camera_preset(self, system, preset: Dict[str, Any]) -> List[Dict[str, Any]]:
        actions = []
        camera_settings = dict(preset.get("camera_settings") or {})
        light_settings = dict(preset.get("light_settings") or {})


        for key in ("auto_exposure", "exposure_time", "gain"):
            if key in camera_settings:
                path = f"camera_settings.{key}"
                actions.append({"update_state": path, "result": system.update_state(path, camera_settings[key])})

        for key in ("coaxial_intensity", "ring_intensity"):
            if key in light_settings:
                path = f"light_settings.{key}"
                actions.append({"update_state": path, "result": system.update_state(path, light_settings[key])})

        channel = preset.get("channel")
        if channel:
            actions.append(
                {
                    "state_label": "channel",
                    "value": channel,
                    "notes": "Whole-chip overview uses the camera feed; microscope channel is not required for camera capture.",
                }
            )

        return actions

    def _normalize_temperature_steps(
        self,
        steps: List[Dict[str, Any]],
        tolerance_c: float,
        settle_timeout_seconds: float,
        sample_interval_seconds: float,
        require_settle: bool,
        max_samples_per_step: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(steps, list) or not steps:
            raise DropLogicMCPError("Temperature routine expects a non-empty list of steps.")

        normalized = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise DropLogicMCPError(f"Temperature step {index} must be an object.")

            target = step.get("target_c", step.get("target", step.get("temperature")))
            if target is None:
                raise DropLogicMCPError(f"Temperature step {index} is missing target_c.")

            hold = step.get("hold_seconds", step.get("duration_seconds", step.get("hold", 0)))
            normalized.append(
                {
                    "index": index,
                    "target_c": float(target),
                    "hold_seconds": max(0.0, float(hold or 0)),
                    "tolerance_c": max(0.0, float(step.get("tolerance_c", tolerance_c))),
                    "settle_timeout_seconds": max(
                        0.0,
                        float(step.get("settle_timeout_seconds", settle_timeout_seconds)),
                    ),
                    "sample_interval_seconds": max(
                        0.1,
                        float(step.get("sample_interval_seconds", sample_interval_seconds)),
                    ),
                    "require_settle": bool(step.get("require_settle", require_settle)),
                    "max_samples": max(1, int(step.get("max_samples", max_samples_per_step))),
                }
            )
        return normalized

    def _update_temperature_routine_status(self, routine_id: str, **updates: Any) -> None:
        with self._temperature_routine_lock:
            if not self._temperature_routine_status:
                return
            if self._temperature_routine_status.get("routine_id") != routine_id:
                return
            self._temperature_routine_status.update(self.to_jsonable(updates))

    def _append_temperature_routine_result(self, routine_id: str, result: Dict[str, Any]) -> None:
        with self._temperature_routine_lock:
            if not self._temperature_routine_status:
                return
            if self._temperature_routine_status.get("routine_id") != routine_id:
                return
            results = self._temperature_routine_status.setdefault("results", [])
            results.append(self.to_jsonable(result))
            self._temperature_routine_status["completed_steps"] = sum(
                1 for item in results if item.get("ok")
            )

    def _run_temperature_routine(
        self,
        routine_id: str,
        steps: List[Dict[str, Any]],
        stop_on_error: bool,
    ) -> None:
        ok = True
        error = None
        try:
            for step in steps:
                if self._temperature_routine_stop_event.is_set():
                    ok = False
                    error = "cancelled"
                    break

                self._update_temperature_routine_status(
                    routine_id,
                    current_step_index=step["index"],
                    active_step=step,
                    last_sample=None,
                )
                item = self._temperature_hold_impl(
                    target_c=step["target_c"],
                    hold_seconds=step["hold_seconds"],
                    tolerance_c=step["tolerance_c"],
                    settle_timeout_seconds=step["settle_timeout_seconds"],
                    sample_interval_seconds=step["sample_interval_seconds"],
                    require_settle=step["require_settle"],
                    max_samples=step["max_samples"],
                    stop_event=self._temperature_routine_stop_event,
                    status_callback=lambda sample, rid=routine_id: self._update_temperature_routine_status(
                        rid,
                        last_sample=sample,
                    ),
                )
                item["index"] = step["index"]
                self._append_temperature_routine_result(routine_id, item)

                if self._temperature_routine_stop_event.is_set():
                    ok = False
                    error = "cancelled"
                    break
                if not item.get("ok"):
                    ok = False
                    error = item.get("error") or "temperature step failed"
                    if stop_on_error:
                        break
        except Exception as exc:
            ok = False
            error = str(exc)
            self._record_error("temperature_routine", exc)
        finally:
            self._update_temperature_routine_status(
                routine_id,
                running=False,
                completed=not self._temperature_routine_stop_event.is_set() and error is None,
                ok=ok,
                finished_at=time.time(),
                active_step=None,
                error=error,
            )

    def _temperature_hold_impl(
        self,
        target_c: float,
        hold_seconds: float,
        tolerance_c: float,
        settle_timeout_seconds: float,
        sample_interval_seconds: float,
        require_settle: bool,
        max_samples: int,
        stop_event: Optional[threading.Event] = None,
        status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        system = self.require_system()
        target = float(target_c)
        hold_seconds = max(0.0, float(hold_seconds))
        tolerance = max(0.0, float(tolerance_c))
        settle_timeout = max(0.0, float(settle_timeout_seconds))
        sample_interval = max(0.1, float(sample_interval_seconds))
        max_samples = max(1, int(max_samples))

        set_result = system.update_state("temperature.target", target)
        samples = []
        settled = False
        settle_started = time.time()
        deadline = settle_started + settle_timeout

        while time.time() <= deadline:
            current = self._read_temperature_value()
            sample = {
                "elapsed_seconds": round(time.time() - settle_started, 2),
                "temperature_c": current,
                "within_tolerance": (
                    current is not None and abs(float(current) - target) <= tolerance
                ),
            }
            self._append_compact_sample(samples, sample, max_samples)
            if status_callback is not None:
                status_callback(sample)
            if sample["within_tolerance"]:
                settled = True
                break
            if stop_event is not None and stop_event.is_set():
                return {
                    "ok": False,
                    "target_c": target,
                    "hold_seconds": hold_seconds,
                    "settled": settled,
                    "set_result": self.to_jsonable(set_result),
                    "samples": samples,
                    "error": "cancelled",
                }
            if settle_timeout <= 0:
                break
            if stop_event is not None:
                if stop_event.wait(sample_interval):
                    return {
                        "ok": False,
                        "target_c": target,
                        "hold_seconds": hold_seconds,
                        "settled": settled,
                        "set_result": self.to_jsonable(set_result),
                        "samples": samples,
                        "error": "cancelled",
                    }
            else:
                time.sleep(sample_interval)

        if require_settle and not settled:
            return {
                "ok": False,
                "target_c": target,
                "hold_seconds": hold_seconds,
                "settled": False,
                "set_result": self.to_jsonable(set_result),
                "samples": samples,
                "error": "temperature did not settle within tolerance before timeout",
            }

        hold_started = time.time()
        hold_deadline = hold_started + hold_seconds
        while time.time() < hold_deadline:
            current = self._read_temperature_value()
            sample = {
                "elapsed_seconds": round(time.time() - settle_started, 2),
                "temperature_c": current,
                "within_tolerance": (
                    current is not None and abs(float(current) - target) <= tolerance
                ),
            }
            self._append_compact_sample(samples, sample, max_samples)
            if status_callback is not None:
                status_callback(sample)
            if stop_event is not None and stop_event.is_set():
                return {
                    "ok": False,
                    "target_c": target,
                    "hold_seconds": hold_seconds,
                    "settled": settled,
                    "set_result": self.to_jsonable(set_result),
                    "samples": samples,
                    "error": "cancelled",
                }
            remaining = hold_deadline - time.time()
            if remaining <= 0:
                break
            sleep_time = min(sample_interval, remaining)
            if stop_event is not None:
                if stop_event.wait(sleep_time):
                    return {
                        "ok": False,
                        "target_c": target,
                        "hold_seconds": hold_seconds,
                        "settled": settled,
                        "set_result": self.to_jsonable(set_result),
                        "samples": samples,
                        "error": "cancelled",
                    }
            else:
                time.sleep(sleep_time)

        final_temperature = self._read_temperature_value()
        if final_temperature is not None:
            self._append_compact_sample(
                samples,
                {
                    "elapsed_seconds": round(time.time() - settle_started, 2),
                    "temperature_c": final_temperature,
                    "within_tolerance": abs(float(final_temperature) - target) <= tolerance,
                },
                max_samples,
            )
            if status_callback is not None:
                status_callback(samples[-1])

        return {
            "ok": True,
            "target_c": target,
            "hold_seconds": hold_seconds,
            "settled": settled,
            "tolerance_c": tolerance,
            "final_temperature_c": final_temperature,
            "set_result": self.to_jsonable(set_result),
            "samples": samples,
        }

    def _read_temperature_value(self):
        system = self.require_system()
        module = getattr(system, "temperature", None)
        if module is None or not hasattr(module, "get_temperature"):
            return None
        try:
            return module.get_temperature()
        except Exception as exc:
            self._record_error("temperature:get_temperature", exc)
            return None

    def _append_compact_sample(self, samples: List[Dict[str, Any]], sample: Dict[str, Any], max_samples: int) -> None:
        samples.append(self.to_jsonable(sample))
        if len(samples) > max_samples:
            if len(samples) == max_samples + 1:
                samples.insert(1, {"omitted_samples": 1})
            else:
                samples[1]["omitted_samples"] = samples[1].get("omitted_samples", 0) + 1
            del samples[2]

    def _move_stage_to_position(
        self,
        position: Dict[str, int],
        wait_timeout_seconds: float = 20.0,
        poll_interval: float = 0.1,
        source: str = "runtime._move_stage_to_position",
    ) -> Dict[str, Any]:
        system = self.require_system()
        target_position = self._normalize_stage_position(position)
        xy_stage = getattr(system, "xy_stage", None)
        actual_before = self._read_stage_position(xy_stage)
        stage_idle = True
        if xy_stage is not None and hasattr(xy_stage, "is_motion_complete"):
            try:
                stage_idle = all(xy_stage.is_motion_complete(axis) for axis in ("X", "Y", "Z"))
            except Exception:
                stage_idle = False

        if (
            xy_stage is not None
            and stage_idle
            and self._stage_positions_close(target_position, actual_before)
        ):
            queue_wait = self._hardware_queue_summary()
            return {
                "ok": True,
                "position": target_position,
                "target_position": target_position,
                "actual_position": actual_before,
                "update_result": {
                    "success": True,
                    "key": "xy_stage.position",
                    "actual_value": target_position,
                    "changed": False,
                    "skipped": "already_at_target",
                },
                "queue_wait": {
                    "ok": True,
                    "timed_out": False,
                    "pending_commands": queue_wait.get("pending_commands", 0),
                    "queues": queue_wait.get("queues", {}),
                },
                "motion_complete": True,
                "skipped": "already_at_target",
            }

        result = system.update_state("xy_stage.position", dict(target_position))
        queue_wait = self._wait_for_hardware_queue_empty(
            timeout_seconds=max(float(wait_timeout_seconds), 1.0),
            poll_interval=0.05,
        )

        if xy_stage is None or type(system).__name__ == "Simulator":
            actual_position = self._read_stage_position(xy_stage) or target_position
            return {
                "ok": bool(queue_wait.get("ok", True)),
                "position": target_position,
                "target_position": target_position,
                "actual_position": actual_position,
                "update_result": self.to_jsonable(result),
                "queue_wait": queue_wait,
                "motion_complete": True,
            }

        deadline = time.time() + max(0.0, float(wait_timeout_seconds))
        time.sleep(0.2)
        while time.time() < deadline:
            try:
                if all(xy_stage.is_motion_complete(axis) for axis in ("X", "Y", "Z")):
                    actual_position = self._read_stage_position(xy_stage)
                    ok = bool(queue_wait.get("ok", True)) and self._stage_positions_close(
                        target_position,
                        actual_position,
                    )
                    return {
                        "ok": ok,
                        "position": target_position,
                        "target_position": target_position,
                        "actual_position": actual_position,
                        "update_result": self.to_jsonable(result),
                        "queue_wait": queue_wait,
                        "motion_complete": True,
                    }
            except Exception as exc:
                actual_position = self._read_stage_position(xy_stage)
                return {
                    "ok": False,
                    "position": target_position,
                    "target_position": target_position,
                    "actual_position": actual_position,
                    "update_result": self.to_jsonable(result),
                    "queue_wait": queue_wait,
                    "motion_complete": False,
                    "error": str(exc),
                }
            time.sleep(max(0.02, float(poll_interval)))

        actual_position = self._read_stage_position(xy_stage)
        return {
            "ok": False,
            "position": target_position,
            "target_position": target_position,
            "actual_position": actual_position,
            "update_result": self.to_jsonable(result),
            "queue_wait": queue_wait,
            "motion_complete": False,
            "timed_out": True,
        }

    def _read_stage_position(self, xy_stage=None) -> Optional[Dict[str, int]]:
        system = self.system
        if xy_stage is None and system is not None:
            xy_stage = getattr(system, "xy_stage", None)
        if xy_stage is None or not hasattr(xy_stage, "get_position"):
            return None

        values = {}
        for axis in ("X", "Y", "Z"):
            try:
                position = xy_stage.get_position(axis)
            except Exception:
                return None
            if position is None:
                return None
            values[axis] = int(position)
        return values

    def _streamer_source_name(self, system, streamer) -> Optional[str]:
        device = getattr(streamer, "device", None)
        if device is None:
            return None
        if device is getattr(system, "microscope", None):
            return "microscope"
        if device is getattr(system, "camera", None):
            return "camera"
        return "unknown"

    def _visualizer_frame_sources(self, instance) -> List[str]:
        if instance is None:
            return []
        sources = []
        if hasattr(instance, "get_snapshot_frame"):
            sources.append("snapshot")
        if hasattr(instance, "get_processed_frame"):
            sources.append("processed")
        if hasattr(instance, "get_raw_frame"):
            sources.append("raw")
        if getattr(instance, "device", None) is not None:
            sources.append("camera_raw")
        return sources

    def _resize_frame(
        self,
        frame,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
    ):
        if frame is None or (max_width is None and max_height is None):
            return frame

        try:
            import cv2
        except Exception:
            return frame

        height, width = frame.shape[:2]
        scale = 1.0
        if max_width is not None and width > int(max_width):
            scale = min(scale, int(max_width) / float(width))
        if max_height is not None and height > int(max_height):
            scale = min(scale, int(max_height) / float(height))
        if scale >= 1.0:
            return frame

        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)

    def _get_visualizer_instance(self, system, visualizer: str):
        name = self._normalize_visualizer_name(visualizer)
        visualizers = getattr(system, "visualizers", None)
        if visualizers is None:
            return None
        if name == "matrix":
            return getattr(visualizers, "matrix", None)
        if name == "streamer":
            return getattr(visualizers, "streamer", None)

    def _namespace_visualizer_windows(self, system) -> None:
        """Give MCP-owned OpenCV windows unique names to avoid cross-session closes."""
        visualizers = getattr(system, "visualizers", None)
        if visualizers is None:
            return

        suffix = f" [{self.session_id}]"
        for name in ("matrix", "streamer"):
            instance = getattr(visualizers, name, None)
            if instance is None or not hasattr(instance, "window_name"):
                continue

            window_name = str(getattr(instance, "window_name") or "")
            if not window_name or window_name.endswith(suffix):
                continue
            setattr(instance, "window_name", f"{window_name}{suffix}")

    def _get_visualizer_frame(self, system, visualizer: str, frame_source: str = "snapshot"):
        instance = self._get_visualizer_instance(system, visualizer)
        if instance is None:
            raise DropLogicMCPError(f"Visualizer '{visualizer}' is not available.")

        source = (frame_source or "snapshot").lower()
        if source == "snapshot" and hasattr(instance, "get_snapshot_frame"):
            return instance.get_snapshot_frame()
        if source == "processed" and hasattr(instance, "get_processed_frame"):
            return instance.get_processed_frame()
        if source == "raw" and hasattr(instance, "get_raw_frame"):
            return instance.get_raw_frame()
        if source in {"camera_raw", "device_raw", "capture_raw"}:
            return self._capture_visualizer_device_frame(instance)
        raise DropLogicMCPError(
            f"Visualizer '{visualizer}' cannot provide frame source '{frame_source}'. "
            f"Available sources: {self._visualizer_frame_sources(instance)}"
        )

    def _capture_visualizer_device_frame(self, instance):
        device = getattr(instance, "device", None)
        if device is None or not hasattr(device, "capture_image"):
            raise DropLogicMCPError("Visualizer has no camera-like capture device.")
        try:
            if hasattr(device, "capture_lock"):
                with device.capture_lock:
                    frame = device.capture_image()
            else:
                frame = device.capture_image()
        except TypeError:
            frame = device.capture_image(display=False)
        if frame is None:
            raise DropLogicMCPError("Camera device returned no frame.")
        return frame

    def _normalize_advanced_drop_arguments(
        self, method: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        normalized = dict(arguments)
        if method == "move":
            # For MCP/agent use, a failed planner result must not mutate the live
            # AdvancedDrop plan by default. Agents can inspect the returned failed
            # plan summary and retry with smaller batches or waypoints.
            normalized.setdefault("merge_on_failure", False)
            return normalized

        if method == "reservoir_extraction":
            if normalized.get("steps") is not None:
                normalized["steps"] = self._pair(normalized["steps"], "steps")
            if normalized.get("split_size") is not None:
                normalized["split_size"] = self._size_or_shape(
                    normalized["split_size"], "split_size"
                )
            if (
                str(normalized.get("split_mode") or "").lower() == "linear"
                and normalized.get("linear_drop_shape") is None
                and normalized.get("split_size") is not None
            ):
                normalized["linear_drop_shape"] = normalized["split_size"]
            for key in ("linear_direction",):
                if normalized.get(key) is not None:
                    normalized[key] = self._pair(normalized[key], key)
            if normalized.get("linear_drop_shape") is not None:
                normalized["linear_drop_shape"] = self._size_or_shape(
                    normalized["linear_drop_shape"], "linear_drop_shape"
                )
            return normalized

        if method == "isometric_split":
            if normalized.get("steps") is not None:
                normalized["steps"] = self._pairs(normalized["steps"], "steps")
            return normalized

        if method == "mix":
            if normalized.get("split_area") is not None:
                normalized["split_area"] = self._shape(normalized["split_area"])
            return normalized

        if method == "merge":
            droplet_ids = normalized.get("droplet_ids")
            if isinstance(droplet_ids, (int, float, str)):
                normalized["droplet_ids"] = [int(droplet_ids)]
            elif isinstance(droplet_ids, (list, tuple)):
                normalized["droplet_ids"] = [int(item) for item in droplet_ids]
            else:
                raise DropLogicMCPError(
                    "merge droplet_ids must be an integer or a list of integers."
                )
            if isinstance(normalized.get("target"), list):
                normalized["target"] = self._pair(normalized["target"], "target")
            elif isinstance(normalized.get("target"), str):
                normalized["target"] = int(normalized["target"])
            return normalized

        if method == "correct_droplet_position":
            if normalized.get("correct_pos") is not None:
                normalized["correct_pos"] = self._pair(
                    normalized["correct_pos"], "correct_pos"
                )
            return normalized

        if method == "verify_droplets":
            if isinstance(normalized.get("droplet_ids"), tuple):
                normalized["droplet_ids"] = list(normalized["droplet_ids"])
            return normalized

        if method == "push_frame":
            return normalized

        return normalized

    def _normalize_imaging_channels(self, channels: Optional[List[Any]]) -> List[Dict[str, Any]]:
        if channels is None:
            channels = ["Brightfield", "FAM"]

        profiles = []
        defaults = {
            "brightfield": {
                "channel": "Brightfield",
                "exposure_time": 72000,
                "gain": 0,
                "coaxial_intensity": 4,
                "ring_intensity": 0,
                "mode": "brightfield",
            },
            "fam": {
                "channel": "FAM",
                "exposure_time": 4800000,
                "gain": 0,
                "coaxial_intensity": 99,
                "ring_intensity": 0,
                "mode": "fluorescence",
            },
        }
        for item in channels:
            if isinstance(item, str):
                key = item.lower()
                profile = dict(defaults.get(key, {"channel": item, "mode": "brightfield"}))
            elif isinstance(item, dict):
                channel = str(item.get("channel", item.get("name", ""))).strip()
                if not channel:
                    raise DropLogicMCPError("Each imaging channel dict needs 'channel' or 'name'.")
                key = channel.lower()
                profile = dict(defaults.get(key, {"channel": channel, "mode": "brightfield"}))
                profile.update(item)
                profile["channel"] = channel
            else:
                raise DropLogicMCPError(
                    "channels must contain strings or channel profile objects."
                )

            channel_key = str(profile.get("channel", "")).lower()
            if channel_key == "fam":
                profile["mode"] = "fluorescence"
            else:
                profile.setdefault("mode", "brightfield")

            profile["exposure_time"] = int(profile.get("exposure_time", defaults.get(channel_key, {}).get("exposure_time", 72000)))
            profile["gain"] = int(profile.get("gain", 0))
            profile["coaxial_intensity"] = int(profile.get("coaxial_intensity", 0))
            profile["ring_intensity"] = int(profile.get("ring_intensity", 0))
            profiles.append(profile)

        return profiles

    def _pair(self, value: Iterable[int], name: str) -> tuple:
        if value is None:
            raise DropLogicMCPError(f"{name} is required.")
        items = list(value)
        if len(items) != 2:
            raise DropLogicMCPError(f"{name} must contain exactly two integers.")
        return int(items[0]), int(items[1])

    def _pairs(self, value: Iterable[Iterable[int]], name: str) -> List[tuple]:
        return [self._pair(item, name) for item in value]

    def _shape(self, value: Iterable[Iterable[int]]) -> set:
        return {self._pair(item, "shape coordinate") for item in value}

    def _size_or_shape(self, value: Any, name: str):
        if isinstance(value, (list, tuple)) and len(value) == 2 and all(
            isinstance(item, (int, float)) for item in value
        ):
            return self._pair(value, name)
        return self._shape(value)

    def _summarize_state_value(self, value: Any, max_list_items: int = 20) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, np.generic):
            return value.item()

        if isinstance(value, np.ndarray):
            if value.ndim == 2 and value.size > 512:
                return self._matrix_compact_representation(
                    value,
                    source="state_summary",
                    include_ranges=True,
                    include_active_cells=False,
                    include_hash=True,
                )
            summary = {
                "type": "ndarray",
                "shape": list(value.shape),
                "dtype": str(value.dtype),
            }
            if value.size:
                summary["nonzero"] = int(np.count_nonzero(value))
                try:
                    summary["min"] = self.to_jsonable(np.min(value))
                    summary["max"] = self.to_jsonable(np.max(value))
                except Exception:
                    pass
            return summary

        if is_dataclass(value):
            return self._summarize_state_value(asdict(value), max_list_items=max_list_items)

        if isinstance(value, dict):
            return {str(k): self._summarize_state_value(v, max_list_items=max_list_items) for k, v in value.items()}

        if isinstance(value, tuple):
            return [self._summarize_state_value(item, max_list_items=max_list_items) for item in value]

        if isinstance(value, list):
            matrix_array = self._list_matrix_array(value)
            if matrix_array is not None:
                return self._matrix_compact_representation(
                    matrix_array,
                    source="state_summary",
                    include_ranges=True,
                    include_active_cells=False,
                    include_hash=True,
                )
            if len(value) > max_list_items:
                sample = value[: min(5, len(value))]
                return {
                    "type": "list",
                    "length": len(value),
                    "sample": [self._summarize_state_value(item, max_list_items=max_list_items) for item in sample],
                }
            return [self._summarize_state_value(item, max_list_items=max_list_items) for item in value]

        if isinstance(value, set):
            items = list(value)
            if len(items) > max_list_items:
                items = items[: min(5, len(items))]
                return {
                    "type": "set",
                    "length": len(value),
                    "sample": [self._summarize_state_value(item, max_list_items=max_list_items) for item in items],
                }
            return [self._summarize_state_value(item, max_list_items=max_list_items) for item in items]

        if hasattr(value, "__dict__"):
            payload = {
                key: val
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
            payload["type"] = type(value).__name__
            return self._summarize_state_value(payload, max_list_items=max_list_items)

        return str(value)

    def _list_matrix_array(self, value: List[Any]) -> Optional[np.ndarray]:
        if len(value) < 16 or not all(isinstance(row, (list, tuple, np.ndarray)) for row in value):
            return None
        row_lengths = [len(row) for row in value]
        if not row_lengths or min(row_lengths) < 16 or len(set(row_lengths)) != 1:
            return None
        try:
            array = np.asarray(value)
        except Exception:
            return None
        if array.ndim != 2 or array.size <= 512:
            return None
        if not np.issubdtype(array.dtype, np.number) and array.dtype != np.bool_:
            return None
        return array

    def to_jsonable(self, value: Any) -> Any:
        """Convert DropLogic/numpy objects into JSON-safe data."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, np.generic):
            return value.item()

        if isinstance(value, np.ndarray):
            if value.size <= 512:
                return value.tolist()
            return {
                "type": "ndarray",
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "min": self.to_jsonable(np.min(value)) if value.size else None,
                "max": self.to_jsonable(np.max(value)) if value.size else None,
                "nonzero": int(np.count_nonzero(value)),
            }

        if is_dataclass(value):
            payload = asdict(value)
            payload["type"] = type(value).__name__
            return self.to_jsonable(payload)

        if isinstance(value, dict):
            return {str(k): self.to_jsonable(v) for k, v in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [self.to_jsonable(item) for item in value]

        if hasattr(value, "__dict__"):
            payload = {
                key: val
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
            payload["type"] = type(value).__name__
            return self.to_jsonable(payload)

        return str(value)
