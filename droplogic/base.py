import json
import threading
import time
import copy
import queue
import numpy as np
import logging
import platform
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

from .utils.basic_drop import BasicDrop
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
        
        self._state_lock = threading.Lock()
        self.basic_drop = BasicDrop(parent=self)
        # AdvancedDrop will be initialized by child classes after hardware setup
        
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

    def _setup_queue_system(self):
        """Initialize the hardware command queue system."""
        self._hardware_queues = {priority: queue.Queue() for priority in Priority}
        self._queue_workers = {}
        self._queue_stop_event = threading.Event()
        
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
                self.logger.debug(f"Processing {priority.name} command: {cmd.path} = {cmd.value} (queued at {cmd.timestamp:.3f})")
                self._process_hardware_command(cmd.path, cmd.value, cmd.priority)
                self._hardware_queues[priority].task_done()
            except queue.Empty:
                time.sleep(priority.interval)
            except Exception as e:
                self.logger.error(f"Worker {priority.name} error: {e}")

    def update_state(self, path: str, value: Any, priority: Optional[Priority] = None):
        """Simplified update_state with queue-based hardware processing."""
        # Update software state (simple, fast)
        with self._state_lock:
            keys = path.split('.')
            current = self._state
            for key in keys[:-1]:
                current = current[key]  # Assume path exists
            current[keys[-1]] = value
        
        # Determine priority and enqueue hardware command
        if priority is None:
            priority = self._determine_command_priority(path)
        
        cmd = HardwareCommand(path=path, value=value, priority=priority, timestamp=time.time())
        self._hardware_queues[priority].put(cmd)
        
        return {'success': True, 'key': path, 'actual_value': value, 'changed': True}
    
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
            status[priority.name] = {
                'queue_size': self._hardware_queues[priority].qsize(),
                'interval_ms': priority.interval * 1000,
                'worker_alive': self._queue_workers[priority].is_alive()
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
        self._queue_stop_event.set()
        
        # Wait for workers to finish
        for worker in self._queue_workers.values():
            if worker.is_alive():
                worker.join(timeout=1)
        
        if hasattr(self, "basic_drop") and self.basic_drop:
            self.basic_drop.close()

    def __del__(self):
        self.close()
