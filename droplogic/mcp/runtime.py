"""Runtime layer for the DropLogic MCP server.

This module owns the live DropSystem instance and exposes a JSON-safe API for
MCP tools. The MCP transport stays thin; hardware ownership, safety gates and
serialization live here.
"""

import base64
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
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np

from .context_store import DropLogicMCPContextStore
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

    def __init__(
        self,
        config_file: str = "config.json",
        log_level: str = "INFO",
        allow_real_hardware: bool = False,
        allow_unsafe_tools: bool = False,
        snapshots_dir: Optional[str] = None,
        context_dir: Optional[str] = None,
    ):
        self.config_file = config_file
        self.log_level = log_level
        self.allow_real_hardware = allow_real_hardware
        self.allow_unsafe_tools = allow_unsafe_tools
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

    # ---------------------------------------------------------------------
    # Read/observe

    def status(self) -> Dict[str, Any]:
        """Return a compact runtime status."""
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
                if hasattr(system, "get_queue_status"):
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

            return {
                "session_id": self.session_id,
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

    def read_state(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Read the DropSystem state or a dotted state path."""
        system = self.require_system()
        state = system.state
        if not path:
            return {"path": None, "value": self.to_jsonable(state)}

        current = state
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                raise DropLogicMCPError(f"State path not found: {path}")
            current = current[key]
        return {"path": path, "value": self.to_jsonable(current)}

    def state_summary(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Read DropSystem state with large arrays/lists summarized."""
        system = self.require_system()
        state = system.state
        current = state
        if path:
            for key in path.split("."):
                if not isinstance(current, dict) or key not in current:
                    raise DropLogicMCPError(f"State path not found: {path}")
                current = current[key]

        return {
            "path": path,
            "value": self._summarize_state_value(current),
        }

    def context_status(self) -> Dict[str, Any]:
        """Return the active agent context summary."""
        return self.context.status()

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
            "context": self.context_status(),
            "advanced_drop": self.list_advanced_drop_methods()
            if system is not None and hasattr(system, "advanced_drop")
            else {},
            "advanced_drop_tools": [
                "advanced_drop_call",
                "start_advanced_drop_call",
                "advanced_drop_job_status",
                "cancel_advanced_drop_job",
            ],
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
                    "execute_until_breakpoint",
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
                "visualizer_snapshot",
                "visualizer_call",
            ],
            "imaging_tools": [
                "configure_microscope_imaging",
            ],
            "temperature_tools": [
                "temperature_hold",
                "temperature_sweep",
                "start_temperature_routine",
                "temperature_routine_status",
                "cancel_temperature_routine",
            ],
            "system_methods": self._describe_methods(system, self.SYSTEM_METHODS)
            if system is not None
            else {},
            "modules": loaded_modules,
            "safety": {
                "allow_real_hardware": self.allow_real_hardware,
                "allow_unsafe_tools": self.allow_unsafe_tools,
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
                "window_mode": getattr(instance, "_window_mode", None),
                "display_active": bool(getattr(instance, "_display_active", False)),
                "last_exit_reason": getattr(instance, "last_exit_reason", None),
                "last_display_error": getattr(instance, "last_display_error", None),
            }
            window_name = item["window_name"]
            if window_name:
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

    def configure_microscope_imaging(
        self,
        channel: str = "Brightfield",
        exposure_time: int = 60000,
        gain: int = 12,
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

        updates = [
            ("microscope_settings.current_channel", channel),
            ("microscope_settings.auto_exposure", bool(auto_exposure)),
            ("microscope_settings.exposure_time", int(exposure_time)),
            ("microscope_settings.gain", int(gain)),
            ("light_settings.coaxial_intensity", int(coaxial_intensity)),
            ("light_settings.ring_intensity", int(ring_intensity)),
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
                "Each object needs id or droplet_id plus origin=[row, col]."
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
                payload["target"] = self._pair(
                    payload.get("target", payload["origin"]),
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

    def delete_droplet(self, droplet_id: int) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        with self._lock:
            deleted = advanced_drop.droplets.delete_droplet(droplet_id)
            return {
                "deleted": bool(deleted),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
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
        with self._lock:
            updated = advanced_drop.droplets.update_droplet_position(
                droplet_id, self._pair(position, "position")
            )
            return {
                "updated": bool(updated),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
            }

    def droplets_summary(self) -> Dict[str, Any]:
        advanced_drop = self.require_advanced_drop()
        return self.to_jsonable(advanced_drop.droplets.get_droplets_summary())

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
            return self.to_jsonable(status)

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
            call_arguments = dict(arguments)
            call_arguments.pop("allow_long_sync", None)
            return_full_result = bool(call_arguments.pop("return_full_result", False))
            if return_full_result and allow_full_result_override:
                compact_result = False
            result = func(**call_arguments)
            visualizer_recovery = self._recover_visualizer_if_needed(
                "matrix",
                was_running=matrix_was_running,
            )
            return {
                "method": method,
                "result": self._compact_advanced_drop_result(method, result)
                if compact_result
                else self.to_jsonable(result),
                "result_compact": bool(compact_result),
                "visualizer_recovery": visualizer_recovery,
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
                "plan": self.plan_summary(advanced_drop.plan),
            }

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
                'start_advanced_drop_call(method="move", arguments={...}) and '
                "poll advanced_drop_job_status(). "
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
            ok = True
        except Exception as exc:
            error = self.to_jsonable(
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            self._record_error(f"advanced_drop_job:{method}", exc)
        finally:
            plan = None
            droplets = None
            try:
                advanced_drop = self.require_advanced_drop()
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
        brightfield_exposure: int = 3000,
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
            raise DropLogicMCPError(
                f"Module method '{module}.{method}' is not exposed through MCP. "
                f"Allowed methods: {sorted(allowed_methods)}"
            )
        if (module_key, method) in self.UNSAFE_MODULE_METHODS and not self.allow_unsafe_tools:
            raise DropLogicMCPError(
                f"{module}.{method} is a raw/unsafe module operation. Restart with "
                "--allow-unsafe-tools if you intentionally want to expose it."
            )

        module_instance = getattr(self.require_system(), module_key, None)
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

    def pause_plan(self) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.pause()
        return self.to_jsonable(executor.status())

    def resume_plan(self) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.resume()
        return self.to_jsonable(executor.status())

    def stop_plan(self) -> Dict[str, Any]:
        executor = self.require_executor()
        executor.stop()
        return self.to_jsonable(executor.status())

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
                    "Poll execution_wait_status() or call cancel_execution_wait()."
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

    def execution_wait_status(self) -> Dict[str, Any]:
        """Return compact status for the active or last execution wait job."""
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
                if target_frame is not None and current_frame >= int(target_frame):
                    ok = True
                    reason = "target_frame_reached"
                    break
                if total_frames > 0 and current_frame >= total_frames - 1:
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

        return {
            "available": True,
            "frame_count": len(getattr(plan, "frames", []) or []),
            "planning_success": bool(getattr(plan, "planning_success", False)),
            "events": events,
            "targets_reached": self.to_jsonable(
                getattr(plan, "targets_reached", {}) or {}
            ),
            "trajectories": trajectories,
            "conflicts_resolved": self.to_jsonable(
                getattr(plan, "conflicts_resolved", []) or []
            ),
        }

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
        raise DropLogicMCPError(
            f"Visualizer '{visualizer}' cannot provide frame source '{frame_source}'. "
            f"Available sources: {self._visualizer_frame_sources(instance)}"
        )

    def _normalize_advanced_drop_arguments(
        self, method: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        normalized = dict(arguments)
        if method == "move":
            return normalized

        if method == "reservoir_extraction":
            if normalized.get("steps") is not None:
                normalized["steps"] = self._pair(normalized["steps"], "steps")
            if normalized.get("split_size") is not None:
                normalized["split_size"] = self._size_or_shape(
                    normalized["split_size"], "split_size"
                )
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
            if isinstance(normalized.get("target"), list):
                normalized["target"] = self._pair(normalized["target"], "target")
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
