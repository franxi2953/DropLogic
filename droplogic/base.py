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
    
    def __init__(self, name="test", state_file="config.json", log_level=logging.INFO):
        self._name = name
        self._state_file = state_file
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
        
        # Load state from config file
        try:
            with open(state_file, "r") as f:
                self._state = json.load(f)
        except Exception as e:
            self.logger.error(f"Could not load state from {state_file}: {e}")
            self._state = {}
        
        self._state_lock = threading.RLock()
        # AdvancedDrop will be initialized by child classes after hardware setup

        # State persistence is handled by a dedicated worker so update_state()
        # never performs file I/O in the caller's thread.
        self._setup_state_persistence()
        
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

    def _setup_state_persistence(self):
        """Start the background worker that persists the latest state snapshot."""
        self._state_save_event = threading.Event()
        self._state_save_stop_event = threading.Event()
        self._state_write_lock = threading.Lock()
        self._state_save_version = 0
        self._state_saved_version = 0
        self._state_save_debounce_seconds = 0.05
        self._state_persistence_enabled = bool(self._state_file)
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
        """Mark direct state mutations for asynchronous persistence."""
        if not getattr(self, "_state_persistence_enabled", False):
            return
        with self._state_lock:
            self._state_save_version += 1
        self._state_save_event.set()

    def _mark_state_dirty_locked(self):
        """Mark state dirty while the caller already holds _state_lock."""
        if not getattr(self, "_state_persistence_enabled", False):
            return
        self._state_save_version += 1
        self._state_save_event.set()

    def _state_save_loop(self):
        """Persist coalesced state updates until the system is closed."""
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
        """Write the latest dirty state snapshot to disk using an atomic replace."""
        if not getattr(self, "_state_persistence_enabled", False):
            return

        with self._state_write_lock:
            with self._state_lock:
                version = self._state_save_version
                if version == self._state_saved_version:
                    return
                snapshot = copy.deepcopy(self._state)

            try:
                self._write_state_snapshot(self._json_safe(snapshot))
                self._state_saved_version = version
            except Exception as e:
                self.logger.error(f"Could not save state to {self._state_file}: {e}")
                self._state_save_event.set()

    def _write_state_snapshot(self, snapshot: Dict[str, Any]):
        state_path = os.path.abspath(self._state_file)
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

    def _get_initial_electrode_matrix(self, rows: int, columns: int, reset_matrix: bool = False):
        """Return a valid matrix from state, or zeros when requested/missing/invalid."""
        if reset_matrix:
            return np.zeros((rows, columns), dtype=int).tolist(), "reset"

        with self._state_lock:
            matrix = (
                self._state
                .get("electrode_matrix", {})
                .get("matrix")
            )

        try:
            if matrix is None:
                raise ValueError("missing matrix")
            if isinstance(matrix, list) and not matrix:
                raise ValueError("empty matrix")

            matrix_array = np.asarray(matrix)
            if matrix_array.shape != (rows, columns):
                raise ValueError(f"expected {(rows, columns)}, got {matrix_array.shape}")
            return matrix_array.astype(int).tolist(), "state_file"
        except Exception as e:
            self.logger.warning(
                "Could not restore electrode matrix from state (%s); using zeros",
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
                time.sleep(priority.interval)
                continue

            try:
                self.logger.debug(f"Processing {priority.name} command: {cmd.path} = {cmd.value} (queued at {cmd.timestamp:.3f})")
                self._process_hardware_command(cmd.path, cmd.value, cmd.priority)
                self._last_hardware_command[priority.name] = {
                    "path": cmd.path,
                    "priority": priority.name,
                    "queued_at": cmd.timestamp,
                    "processed_at": time.time(),
                    "ok": True,
                }
                self._last_hardware_command_error[priority.name] = None
            except Exception as e:
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
        """Simplified update_state with queue-based hardware processing."""
        state_value = copy.deepcopy(value)
        command_value = copy.deepcopy(value)

        # Update software state (simple, fast)
        with self._state_lock:
            keys = path.split('.')
            current = self._state
            for key in keys[:-1]:
                current = current[key]  # Assume path exists
            current[keys[-1]] = state_value
            self._mark_state_dirty_locked()
        
        # Determine priority and enqueue hardware command
        if priority is None:
            priority = self._determine_command_priority(path)
        
        cmd = HardwareCommand(path=path, value=command_value, priority=priority, timestamp=time.time())
        self._hardware_queues[priority].put(cmd)

        return {'success': True, 'key': path, 'actual_value': copy.deepcopy(state_value), 'changed': True}
    
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
