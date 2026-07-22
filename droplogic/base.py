import json
import os
import threading
import time
import copy
import queue
import numpy as np
import logging
import platform
import tempfile
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

from .utils.advanced_drop import AdvancedDrop
from .utils.logging_config import setup_droplogic_logger, set_droplogic_logging_level


@dataclass
class HardwareCommand:
    """Represents a hardware command to be processed."""
    path: str
    value: Any
    priority: 'Priority'
    timestamp: float
    previous_value: Any = None

class Priority(Enum):
    """Command priority levels with processing intervals."""
    CRITICAL = (1, 0.001)    # 1ms - Emergency stops
    HIGH = (2, 0.01)         # 10ms - Movement, electrodes
    MEDIUM = (3, 0.1)        # 100ms - Camera, microscope
    LOW = (4, 1.0)           # 1s - Temperature, lights
    
    def __init__(self, level: int, interval: float):
        self.level = level
        self.interval = interval

class DropSystem(ABC):
    """Base class for all DropSystem hardware systems with queue-based hardware processing."""

    RUNTIME_PERSISTENT_PATHS = {"electrode_matrix.matrix"}
    
    def __init__(self, name="test", state_file="config.json", log_level=logging.INFO):
        self._name = name
        self._state_file = state_file
        self._runtime_state_file = self._derive_runtime_state_file(state_file)
        self.host_platform = self._detect_host_platform()
        
        # Set up logging for this DropSystem instance
        self.logger = setup_droplogic_logger(f'droplogic.{name}', level=log_level)
        set_droplogic_logging_level(log_level)
        self.logger.info(f"Initializing {name}...{state_file}")
        self.logger.info(
            "Detected host OS: %s (%s)",
            self.host_platform["system"],
            self.host_platform["machine"],
        )
        
        # Load stable configuration from config file.
        try:
            with open(state_file, "r") as f:
                self._state = json.load(f)
        except Exception as e:
            self.logger.error(f"Could not load state from {state_file}: {e}")
            self._state = {}

        self._runtime_state = self._load_runtime_state(self._runtime_state_file)
        
        self._state_lock = threading.RLock()
        # AdvancedDrop will be initialized by child classes after hardware setup

        # config.json is reserved for stable configuration, calibration,
        # defaults, and presets. Runtime persistence writes only explicitly
        # tracked physical state, currently the active electrode matrix, to a
        # separate local runtime-state file.
        self._setup_state_persistence(enabled=True)
        
        # Initialize queue system
        self._setup_queue_system()

    def _detect_host_platform(self) -> Dict[str, Any]:
        """Capture host OS information once so downstream modules can adapt behavior."""
        system = platform.system() or "Unknown"
        normalized = {
            "Darwin": "macos",
            "Windows": "windows",
            "Linux": "linux",
        }.get(system, system.lower())
        return {
            "system": system,
            "normalized_system": normalized,
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "gui_requires_main_thread": system == "Darwin",
        }

    @property
    def name(self):
        return self._name

    @property
    def host_os(self) -> str:
        return self.host_platform["normalized_system"]

    @property
    def state(self):
        with self._state_lock:
            return self._state.copy()

    def _derive_runtime_state_file(self, config_file: Optional[str]) -> Optional[str]:
        """Return the sidecar runtime-state path for a config file."""
        if not config_file:
            return None
        root, ext = os.path.splitext(os.path.abspath(config_file))
        return f"{root}.runtime-state{ext or '.json'}"

    def _load_runtime_state(self, runtime_state_file: Optional[str]) -> Dict[str, Any]:
        """Load persisted runtime state from the local sidecar file."""
        if not runtime_state_file or not os.path.exists(runtime_state_file):
            return {}
        try:
            with open(runtime_state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.logger.info("Loaded runtime state from %s", runtime_state_file)
                return data
            self.logger.warning("Ignoring non-object runtime state in %s", runtime_state_file)
        except Exception as e:
            self.logger.warning("Could not load runtime state from %s: %s", runtime_state_file, e)
        return {}

    def _setup_state_persistence(self, enabled: bool = False):
        """Configure optional runtime-state persistence."""
        self._state_save_event = threading.Event()
        self._state_save_stop_event = threading.Event()
        self._state_write_lock = threading.Lock()
        self._state_save_version = 0
        self._state_saved_version = 0
        self._state_save_debounce_seconds = 0.05
        self._state_persistence_enabled = bool(enabled and self._runtime_state_file)
        self._state_save_worker = None

        if not self._state_persistence_enabled:
            return

        self._state_save_worker = threading.Thread(
            target=self._state_save_loop,
            name=f"{self._name}StateSaver",
            daemon=True
        )
        self._state_save_worker.start()

    def mark_state_dirty(self):
        """Mark runtime-state dirty after a direct persisted mutation."""
        if not getattr(self, "_state_persistence_enabled", False):
            return
        with self._state_lock:
            self._state_save_version += 1
        self._state_save_event.set()

    def _mark_state_dirty_locked(self):
        """Mark runtime-state dirty while the caller already holds _state_lock."""
        if not getattr(self, "_state_persistence_enabled", False):
            return
        self._state_save_version += 1
        self._state_save_event.set()

    def _state_save_loop(self):
        """Persist coalesced runtime-state updates until the system is closed."""
        while True:
            self._state_save_event.wait(timeout=0.5)
            if self._state_save_stop_event.is_set():
                break

            if not self._state_save_event.is_set():
                continue

            self._state_save_event.clear()
            self._state_save_stop_event.wait(self._state_save_debounce_seconds)
            self.flush_state()

        self.flush_state()

    def flush_state(self):
        """Write the latest dirty runtime-state snapshot using an atomic replace."""
        if not getattr(self, "_state_persistence_enabled", False):
            return

        with self._state_write_lock:
            with self._state_lock:
                version = self._state_save_version
                if version == self._state_saved_version:
                    return
                snapshot = copy.deepcopy(self._runtime_state)
                if not snapshot:
                    self._state_saved_version = version
                    return

            try:
                self._write_state_snapshot(self._json_safe(snapshot))
                self._state_saved_version = version
            except Exception as e:
                self.logger.error(f"Could not save runtime state to {self._runtime_state_file}: {e}")
                self._state_save_event.set()

    def _write_state_snapshot(self, snapshot: Dict[str, Any]):
        state_path = os.path.abspath(self._runtime_state_file)
        state_dir = os.path.dirname(state_path) or "."
        os.makedirs(state_dir, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(state_path)}.",
            suffix=".tmp",
            dir=state_dir,
            text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=4)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, state_path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def _json_safe(self, value: Any):
        """Convert numpy-heavy runtime state into JSON-serializable values."""
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(item) for item in value]
        return value

    def _should_persist_runtime_path(self, path: str) -> bool:
        """Return whether a state path should be persisted across sessions."""
        return path in self.RUNTIME_PERSISTENT_PATHS

    def _coerce_electrode_matrix(self, matrix: Any, rows: int, columns: int) -> np.ndarray:
        """Validate and coerce an electrode matrix to an integer ndarray."""
        if matrix is None:
            raise ValueError("missing matrix")
        if isinstance(matrix, list) and not matrix:
            raise ValueError("empty matrix")
        matrix_array = np.asarray(matrix)
        if matrix_array.shape != (rows, columns):
            raise ValueError(f"expected {(rows, columns)}, got {matrix_array.shape}")
        return matrix_array.astype(int)

    def _runtime_matrix_candidate(self):
        runtime_matrix = (
            self._runtime_state
            .get("electrode_matrix", {})
            .get("matrix")
        )
        config_matrix = (
            self._state
            .get("electrode_matrix", {})
            .get("matrix")
        )
        return (
            ("runtime_state", runtime_matrix),
            ("config_matrix", config_matrix),
        )

    def _has_matrix_candidate(self, matrix: Any) -> bool:
        """Return whether a matrix candidate is meaningful enough to warn about."""
        if matrix is None:
            return False
        if isinstance(matrix, list) and not matrix:
            return False
        return True

    def _record_runtime_persistent_value(self, path: str, value: Any):
        """Record a processed hardware value in the runtime-state sidecar."""
        if not self._should_persist_runtime_path(path):
            return

        if path == "electrode_matrix.matrix":
            try:
                matrix_array = np.asarray(value).astype(int)
            except Exception as e:
                self.logger.warning("Ignoring invalid runtime matrix value: %s", e)
                return
            if matrix_array.ndim != 2 or 0 in matrix_array.shape:
                self.logger.warning("Ignoring invalid runtime matrix shape: %s", matrix_array.shape)
                return

            rows, columns = matrix_array.shape
            with self._state_lock:
                self._runtime_state["version"] = 1
                self._runtime_state["system"] = self._name
                self._runtime_state["updated_at"] = time.time()
                matrix_state = self._runtime_state.setdefault("electrode_matrix", {})
                matrix_state["rows"] = int(rows)
                matrix_state["columns"] = int(columns)
                matrix_state["matrix"] = matrix_array.tolist()
                self._mark_state_dirty_locked()

    def _values_equal(self, a: Any, b: Any) -> bool:
        """Compare possibly numpy-backed state values."""
        try:
            if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
                return bool(np.array_equal(np.asarray(a), np.asarray(b)))
            return a == b
        except Exception:
            return False

    def _get_state_path_locked(self, path: str):
        keys = path.split('.')
        current = self._state
        for key in keys:
            current = current[key]
        return current

    def _set_state_path_locked(self, path: str, value: Any) -> None:
        keys = path.split('.')
        current = self._state
        for key in keys[:-1]:
            current = current[key]
        current[keys[-1]] = copy.deepcopy(value)

    def _restore_state_after_failed_command(self, cmd: HardwareCommand) -> None:
        """Roll back optimistic state when a hardware command fails.

        If another command has already changed the same path, skip rollback so a
        stale failure cannot overwrite newer intent.
        """
        with self._state_lock:
            try:
                current_value = self._get_state_path_locked(cmd.path)
            except Exception:
                return
            if not self._values_equal(current_value, cmd.value):
                return
            self._set_state_path_locked(cmd.path, cmd.previous_value)

    def _get_initial_electrode_matrix(
        self,
        rows: int,
        columns: int,
        reset_matrix: bool = False,
        restore_runtime_matrix: bool = True,
    ):
        """Return an initial matrix for hardware startup.

        Runtime matrix restore is on by default and uses the local sidecar
        runtime-state file. config.json is only a fallback for explicit static
        defaults and should not act as the last-frame persistence store.
        """
        if reset_matrix:
            return np.zeros((rows, columns), dtype=int).tolist(), "reset"
        if not restore_runtime_matrix:
            return np.zeros((rows, columns), dtype=int).tolist(), "default_zero"

        with self._state_lock:
            candidates = self._runtime_matrix_candidate()

        for source, matrix in candidates:
            try:
                matrix_array = self._coerce_electrode_matrix(matrix, rows, columns)
                return matrix_array.tolist(), source
            except Exception as e:
                if self._has_matrix_candidate(matrix):
                    self.logger.warning(
                        "Could not restore electrode matrix from %s (%s); trying next source",
                        source,
                        e,
                    )

        return np.zeros((rows, columns), dtype=int).tolist(), "default_zero"

    def _setup_queue_system(self):
        """Initialize the hardware command queue system."""
        self._hardware_queues = {priority: queue.Queue() for priority in Priority}
        self._queue_workers = {}
        self._queue_stop_event = threading.Event()
        self._last_hardware_command = {priority.name: None for priority in Priority}
        self._last_hardware_command_error = {priority.name: None for priority in Priority}
        
        # Start worker threads for each priority level
        for priority in Priority:
            worker = threading.Thread(
                target=self._queue_worker_loop,
                args=(priority,),
                name=f"HardwareWorker-{priority.name}",
                daemon=True
            )
            self._queue_workers[priority] = worker
            worker.start()
    
    def _queue_worker_loop(self, priority: Priority):
        """Worker loop for processing hardware commands at specific priority level."""
        while not self._queue_stop_event.is_set():
            try:
                cmd = self._hardware_queues[priority].get(timeout=priority.interval)
            except queue.Empty:
                self._queue_stop_event.wait(priority.interval)
                continue

            try:
                self.logger.debug(f"Processing {priority.name} command: {cmd.path} = {cmd.value} (queued at {cmd.timestamp:.3f})")
                result = self._process_hardware_command(cmd.path, cmd.value, cmd.priority)
                if result is False:
                    raise RuntimeError(f"Hardware command returned False for {cmd.path}")
                self._record_runtime_persistent_value(cmd.path, cmd.value)
                self._last_hardware_command[priority.name] = {
                    "path": cmd.path,
                    "priority": priority.name,
                    "queued_at": cmd.timestamp,
                    "processed_at": time.time(),
                    "ok": True,
                }
                self._last_hardware_command_error[priority.name] = None
            except Exception as e:
                self._restore_state_after_failed_command(cmd)
                self.logger.error(f"Worker {priority.name} error: {e}")
                self._last_hardware_command[priority.name] = {
                    "path": cmd.path,
                    "priority": priority.name,
                    "queued_at": cmd.timestamp,
                    "processed_at": time.time(),
                    "ok": False,
                }
                self._last_hardware_command_error[priority.name] = {
                    "path": cmd.path,
                    "priority": priority.name,
                    "queued_at": cmd.timestamp,
                    "processed_at": time.time(),
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            finally:
                self._hardware_queues[priority].task_done()

    def update_state(self, path: str, value: Any, priority: Optional[Priority] = None):
        """Update in-memory state and enqueue hardware processing."""
        state_value = copy.deepcopy(value)
        command_value = copy.deepcopy(value)

        # Update software state (simple, fast). This does not rewrite
        # config.json. Persisted runtime paths are saved only after their
        # hardware command has been processed by a worker.
        with self._state_lock:
            keys = path.split('.')
            current = self._state
            for key in keys[:-1]:
                current = current[key]  # Assume path exists
            previous_value = copy.deepcopy(current.get(keys[-1]))
            current[keys[-1]] = state_value
        
        # Determine priority and enqueue hardware command
        if priority is None:
            priority = self._determine_command_priority(path)
        
        cmd = HardwareCommand(
            path=path,
            value=command_value,
            priority=priority,
            timestamp=time.time(),
            previous_value=previous_value,
        )
        self._enqueue_hardware_command(cmd)

        return {'success': True, 'key': path, 'actual_value': copy.deepcopy(state_value), 'changed': True}

    def _enqueue_hardware_command(self, cmd: HardwareCommand) -> None:
        """Enqueue a hardware command. Child classes may override to coalesce UI work."""
        self._hardware_queues[cmd.priority].put(cmd)

    def set_cached_state(self, path: str, value: Any):
        """Update in-memory state without sending a hardware command.

        Use this for readback/telemetry values such as measured temperature or
        stage position. Commanded hardware state should still use update_state().
        """
        state_value = copy.deepcopy(value)
        with self._state_lock:
            keys = path.split('.')
            current = self._state
            for key in keys[:-1]:
                current = current.setdefault(key, {})
            current[keys[-1]] = state_value

        return {
            'success': True,
            'key': path,
            'actual_value': copy.deepcopy(state_value),
            'changed': True,
            'cached_only': True,
        }
    
    def _determine_command_priority(self, path: str) -> Priority:
        """Determine command priority based on path. Override in child classes."""
        if "emergency" in path.lower() or "stop" in path.lower():
            return Priority.CRITICAL
        return Priority.MEDIUM
    
    @abstractmethod
    def _process_hardware_command(self, path: str, value: Any, priority: Priority):
        """Process hardware command. Must be implemented by child classes."""
        pass
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status and statistics."""
        status = {}
        for priority in Priority:
            queue_obj = self._hardware_queues[priority]
            status[priority.name] = {
                'queue_size': queue_obj.qsize(),
                'unfinished_tasks': getattr(queue_obj, 'unfinished_tasks', queue_obj.qsize()),
                'interval_ms': priority.interval * 1000,
                'worker_alive': self._queue_workers[priority].is_alive(),
                'last_command': copy.deepcopy(
                    getattr(self, "_last_hardware_command", {}).get(priority.name)
                ),
                'last_command_error': copy.deepcopy(
                    getattr(self, "_last_hardware_command_error", {}).get(priority.name)
                ),
            }
        status["STATE_SAVE"] = {
            "enabled": getattr(self, "_state_persistence_enabled", False),
            "runtime_state_file": getattr(self, "_runtime_state_file", None),
            "dirty": getattr(self, "_state_save_version", 0) != getattr(self, "_state_saved_version", 0),
            "worker_alive": bool(
                getattr(self, "_state_save_worker", None)
                and self._state_save_worker.is_alive()
            ),
        }
        return status
    
    def set_logging_level(self, level):
        """Set logging level for this DropSystem instance and all DropLogic modules."""
        set_droplogic_logging_level(level)
        self.logger.info(f"Logging level set to {level}")


    @property
    def logging(self):
        """Access logging control methods."""
        return self._LoggingController(self)

    class _LoggingController:
        """Controller class for easy logging level management."""

        def __init__(self, system_instance):
            self._system = system_instance

        def set_level(self, level):
            """Set logging level. Can be string ('DEBUG', 'INFO', 'WARNING', 'ERROR') or logging constant."""
            if isinstance(level, str):
                level_map = {
                    'DEBUG': logging.DEBUG,
                    'INFO': logging.INFO,
                    'WARNING': logging.WARNING,
                    'WARN': logging.WARNING,
                    'ERROR': logging.ERROR,
                    'CRITICAL': logging.CRITICAL
                }
                level = level_map.get(level.upper())
                if level is None:
                    raise ValueError(f"Invalid logging level: {level}. Use DEBUG, INFO, WARNING, ERROR, or CRITICAL")

            self._system.set_logging_level(level)

        def debug(self):
            """Enable DEBUG level logging."""
            self.set_level(logging.DEBUG)

        def info(self):
            """Enable INFO level logging."""
            self.set_level(logging.INFO)

        def warning(self):
            """Enable WARNING level logging."""
            self.set_level(logging.WARNING)

        def error(self):
            """Enable ERROR level logging."""
            self.set_level(logging.ERROR)

        def critical(self):
            """Enable CRITICAL level logging."""
            self.set_level(logging.CRITICAL)

        def get_level(self):
            """Get current logging level name."""
            level = self._system.logger.level
            level_names = {
                logging.DEBUG: 'DEBUG',
                logging.INFO: 'INFO',
                logging.WARNING: 'WARNING',
                logging.ERROR: 'ERROR',
                logging.CRITICAL: 'CRITICAL'
            }
            return level_names.get(level, f'UNKNOWN({level})')
    
    def emergency_stop(self):
        """Emergency stop - clear all queues and stop operations."""
        self.logger.warning("Emergency stop initiated")
        for q in self._hardware_queues.values():
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                except queue.Empty:
                    break

    def close(self):
        """Close the DropSystem instance and stop all queue workers."""
        self.logger.info(f"Closing DropSystem instance: {self._name}")
        self.flush_state()
        if getattr(self, "_state_save_worker", None) is not None:
            self._state_save_stop_event.set()
            self._state_save_event.set()
            if (
                self._state_save_worker.is_alive()
                and threading.current_thread() is not self._state_save_worker
            ):
                self._state_save_worker.join(timeout=2)
            self.flush_state()

        self._queue_stop_event.set()
        
        # Wait for workers to finish
        for worker in self._queue_workers.values():
            if worker.is_alive():
                worker.join(timeout=1)
        
    def __del__(self):
        self.close()
