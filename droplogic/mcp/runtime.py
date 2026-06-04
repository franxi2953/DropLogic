"""Runtime layer for the DropLogic MCP server.

This module owns the live DropSystem instance and exposes a JSON-safe API for
MCP tools. The MCP transport stays thin; hardware ownership, safety gates and
serialization live here.
"""

import base64
import inspect
import logging
import os
import pickle
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional

import numpy as np


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

    VISUALIZER_METHODS = {
        "matrix": {
            "is_running",
            "requires_main_thread_window",
            "set_matrix_rotation",
            "clear_paths",
            "save_snapshot",
        },
        "streamer": {
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

    def __init__(
        self,
        config_file: str = "config.json",
        log_level: str = "INFO",
        allow_real_hardware: bool = False,
        allow_unsafe_tools: bool = False,
        snapshots_dir: Optional[str] = None,
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
        self.system = None
        self.system_name = None
        self.loaded_at = None

    # ---------------------------------------------------------------------
    # System lifecycle

    def load_system(
        self,
        system: str = "simulator",
        config_file: Optional[str] = None,
        log_level: Optional[str] = None,
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

            if system_key == "simulator":
                from droplogic.hardware.simulator import Simulator

                self.system = Simulator(config_file=config_file, log_level=log_level)
                self.system_name = "simulator"
            elif system_key == "dmlite":
                from droplogic.hardware.DMLite import DMLite

                self.system = DMLite(config_file=config_file, log_level=log_level)
                self.system_name = "dmlite"
            elif system_key in {"boxmini", "box_mini", "box_mini1"}:
                from droplogic.hardware.box_mini1 import BOXMini

                self.system = BOXMini(config_file=config_file, log_level=log_level)
                self.system_name = "boxmini"
            else:
                raise DropLogicMCPError(
                    f"Unknown system '{system}'. Use simulator, dmlite, or boxmini."
                )

            self.config_file = config_file
            self.log_level = log_level
            self.loaded_at = time.time()
            return self.status()

    def close_system(self) -> Dict[str, Any]:
        """Close the current DropSystem, if any."""
        with self._lock:
            if self.system is not None and hasattr(self.system, "close"):
                self.system.close()
            self.system = None
            self.system_name = None
            self.loaded_at = None
            return self.status()

    def require_system(self):
        if self.system is None:
            raise DropLogicMCPError("No system loaded. Call load_system() first.")
        return self.system

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
                "system": system_status,
                "executor": executor_status,
                "plan": plan_summary,
                "droplets": droplet_summary,
            }

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
            "advanced_drop": self.list_advanced_drop_methods()
            if system is not None and hasattr(system, "advanced_drop")
            else {},
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
                ],
            },
            "visualizers": visualizers,
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
            }
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
                item["droplet_detection_enabled"] = getattr(
                    instance, "droplet_detection_enabled", None
                )
                item["condensate_detection_enabled"] = getattr(
                    instance, "condensate_detection_enabled", None
                )
            status[visualizer_name] = self.to_jsonable(item)
        return status

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
        instance.start()
        return {"visualizer": visualizer, "started": True}

    def stop_visualizer(self, visualizer: str = "matrix") -> Dict[str, Any]:
        """Stop a visualizer window."""
        instance = self._get_visualizer_instance(self.require_system(), visualizer)
        if instance is None or not hasattr(instance, "stop"):
            raise DropLogicMCPError(f"Visualizer '{visualizer}' is not available.")
        instance.stop()
        return {"visualizer": visualizer, "stopped": True}

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
        for item in droplets:
            payload = dict(item)
            payload["origin"] = self._pair(payload["origin"], "origin")
            payload["target"] = self._pair(payload.get("target", payload["origin"]), "target")
            if payload.get("shape") is not None:
                payload["shape"] = self._shape(payload["shape"])
            normalized.append(payload)

        with self._lock:
            created = advanced_drop.droplets.add_droplets(normalized)
            return {
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

        with self._lock:
            result = func(**arguments)
            return {
                "method": method,
                "result": self.to_jsonable(result),
                "droplets": self.to_jsonable(
                    advanced_drop.droplets.get_droplets_summary()
                ),
                "plan": self.plan_summary(advanced_drop.plan),
            }

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
        self, method: str, arguments: Optional[Dict[str, Any]] = None
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
        result = func(**(arguments or {}))
        return {
            "method": method,
            "result": self.to_jsonable(result),
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

    def module_call(
        self,
        module: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
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
        result = func(**(arguments or {}))
        return {
            "module": module_key,
            "method": method,
            "result": self.to_jsonable(result),
        }

    # ---------------------------------------------------------------------
    # PlanExecutor API

    def start_plan(
        self,
        frame_delay: float = 1.0,
        verify_positions: bool = True,
        enable_visualizers: bool = False,
        save_to_file: Optional[Any] = None,
        record_matrix: bool = False,
        record_streamer: bool = False,
        matrix_filename: Optional[str] = None,
        streamer_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        executor = self.require_executor()
        with self._lock:
            executor.start(
                frame_delay=frame_delay,
                verify_positions=verify_positions,
                enable_visualizers=enable_visualizers,
                save_to_file=save_to_file,
                record_matrix=record_matrix,
                record_streamer=record_streamer,
                matrix_filename=matrix_filename,
                streamer_filename=streamer_filename,
            )
            return self.to_jsonable(executor.status())

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
