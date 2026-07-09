"""DroptiBot v1.0 face controller for EQ2013-U front panels."""

from __future__ import annotations

import json
import ctypes
import logging
import os
import platform
import random
import threading
import time
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import serial
from PIL import Image, ImageDraw

from ..droptibot_personality import DroptiBotFacePersonality
from ..front_panel_types import FrontPanelResponse


class DroptiBotV1:
    """EQ2013 front-panel driver with a DroptiBot face state machine."""

    DISPLAY_VERSION = "DroptiBot v1.0"
    DEFAULT_PORT = "COM16"
    DEFAULT_BAUDRATE = 57600
    DEFAULT_ADDRESS = "001"
    DEFAULT_WIDTH = 48
    DEFAULT_HEIGHT = 16
    ASSET_STATE_ALIASES = {
        "blank": "sleep",
        "done": "happy",
        "error": "sad",
        "happy": "happy",
        "heating": "working",
        "idle": "idle",
        "light": "happy",
        "looking": "thinking",
        "moving": "working",
        "sad": "sad",
        "sleep": "sleep",
        "thinking": "thinking",
        "working": "working",
    }
    ASSET_FRAME_INTERVALS = {
        "idle": 1.2,
        "happy": 0.95,
        "thinking": 0.9,
        "working": 0.75,
        "sad": 1.4,
        "sleep": 2.2,
    }
    TEXT_FALLBACK_FRAMES = {
        "idle": ("0.0", " 0.0", "0.0 ", " 0.o", "o.0 ", "-.-"),
        "sleep": ("-.- z", " -.-", "-.- Z", "zZZ"),
        "thinking": ("0.0?", " 0.o?", "o.0 ?", "0.0 .", "-.-?"),
        "working": ("0.0.", "0.0..", "0.0...", " 0.o..", "o.0..", "0.0:"),
        "moving": (" >_>", ">>_ ", " _<<", " <_<", " o_O ", " O_o "),
        "looking": (" 0.o", "o.0 ", " 0.0", "0.0 ", "-.-"),
        "heating": ("0_0", " 0_0", "0_0.", " 0.o~", "~0.0"),
        "light": ("0.*", " *.0", "0.0*", "*.* ", " 0.*", " *.*"),
        "done": ("0.0!", " 0.0!", "0.0 ", " -.-!"),
        "sad": ("._.", " ._.", "._. ", "-.-"),
        "error": (">_<", "x_x", "._."),
        "blank": ("",),
    }

    TEXT_FALLBACK_BEHAVIORS = {
        "idle": (
            {"text": "0.0", "weight": 14, "delay": (2.2, 3.8), "hold": (2, 4)},
            {"text": " 0.0", "weight": 3, "delay": (0.85, 1.45), "hold": (1, 2)},
            {"text": "0.0 ", "weight": 3, "delay": (0.85, 1.45), "hold": (1, 2)},
            {"text": " 0.o", "weight": 2, "delay": (0.45, 0.8)},
            {"text": "o.0 ", "weight": 2, "delay": (0.45, 0.8)},
            {"text": "-.-", "weight": 1, "delay": (0.16, 0.24)},
        ),
        "sleep": (
            {"text": "-.- z", "weight": 5, "delay": (3.0, 4.4), "hold": (2, 3)},
            {"text": " -.-", "weight": 3, "delay": (2.0, 3.1), "hold": (1, 2)},
            {"text": "-.- Z", "weight": 2, "delay": (2.1, 3.0)},
            {"text": "zZZ", "weight": 1, "delay": (1.6, 2.3)},
        ),
        "thinking": (
            {"text": "0.0?", "weight": 5, "delay": (1.0, 1.7), "hold": (1, 2)},
            {"text": " 0.o?", "weight": 3, "delay": (0.55, 0.9)},
            {"text": "o.0 ?", "weight": 3, "delay": (0.55, 0.9)},
            {"text": "0.0 .", "weight": 2, "delay": (0.65, 1.05)},
            {"text": "-.-?", "weight": 1, "delay": (0.18, 0.26)},
        ),
        "working": (
            {"text": "0.0.", "weight": 4, "delay": (0.42, 0.62)},
            {"text": "0.0..", "weight": 4, "delay": (0.46, 0.68)},
            {"text": "0.0...", "weight": 4, "delay": (0.52, 0.76)},
            {"text": " 0.o..", "weight": 2, "delay": (0.42, 0.62)},
            {"text": "o.0..", "weight": 2, "delay": (0.42, 0.62)},
            {"text": "0.0:", "weight": 1, "delay": (0.5, 0.75)},
        ),
        "moving": (
            {"text": " >_>", "weight": 3, "delay": (0.14, 0.24)},
            {"text": ">>_ ", "weight": 3, "delay": (0.14, 0.22)},
            {"text": " _<<", "weight": 3, "delay": (0.14, 0.22)},
            {"text": " <_<", "weight": 3, "delay": (0.14, 0.24)},
            {"text": " o_O ", "weight": 2, "delay": (0.2, 0.34)},
            {"text": " O_o ", "weight": 2, "delay": (0.2, 0.34)},
        ),
        "looking": (
            {"text": " 0.o", "weight": 4, "delay": (0.7, 1.2), "hold": (1, 2)},
            {"text": "o.0 ", "weight": 4, "delay": (0.7, 1.2), "hold": (1, 2)},
            {"text": " 0.0", "weight": 3, "delay": (1.0, 1.8), "hold": (1, 2)},
            {"text": "0.0 ", "weight": 3, "delay": (1.0, 1.8), "hold": (1, 2)},
            {"text": "-.-", "weight": 1, "delay": (0.14, 0.22)},
        ),
        "heating": (
            {"text": "0_0", "weight": 4, "delay": (0.8, 1.2), "hold": (1, 2)},
            {"text": " 0_0", "weight": 3, "delay": (0.65, 1.0)},
            {"text": "0_0.", "weight": 2, "delay": (0.55, 0.82)},
            {"text": " 0.o~", "weight": 2, "delay": (0.55, 0.82)},
            {"text": "~0.0", "weight": 2, "delay": (0.55, 0.82)},
        ),
        "light": (
            {"text": "0.*", "weight": 3, "delay": (0.36, 0.54)},
            {"text": " *.0", "weight": 3, "delay": (0.36, 0.54)},
            {"text": "0.0*", "weight": 2, "delay": (0.4, 0.58)},
            {"text": "*.* ", "weight": 2, "delay": (0.4, 0.6)},
            {"text": " 0.*", "weight": 2, "delay": (0.36, 0.54)},
            {"text": " *.*", "weight": 1, "delay": (0.42, 0.6)},
        ),
        "done": (
            {"text": "0.0!", "weight": 4, "delay": (0.8, 1.3), "hold": (1, 2)},
            {"text": " 0.0!", "weight": 3, "delay": (0.65, 1.0)},
            {"text": "0.0 ", "weight": 3, "delay": (1.1, 1.8)},
            {"text": "-.-!", "weight": 1, "delay": (0.16, 0.24)},
        ),
        "sad": (
            {"text": "._.", "weight": 4, "delay": (1.3, 2.0), "hold": (1, 2)},
            {"text": " ._.", "weight": 2, "delay": (1.0, 1.6)},
            {"text": "._. ", "weight": 2, "delay": (1.0, 1.6)},
            {"text": "-.-", "weight": 1, "delay": (0.18, 0.26)},
        ),
        "error": (
            {"text": ">_<", "weight": 4, "delay": (0.3, 0.5)},
            {"text": "x_x", "weight": 3, "delay": (0.4, 0.7)},
            {"text": "._.", "weight": 2, "delay": (0.35, 0.55)},
        ),
        "blank": (
            {"text": "", "weight": 1, "delay": (1.0, 1.0), "hold": (1, 1)},
        ),
    }

    TEXT_FALLBACK_INTERVALS = {
        "idle": (1.4, 0.5, 1.8, 0.7, 2.2),
        "sleep": (2.4, 1.8, 3.0, 2.0),
        "thinking": (0.9, 0.6, 1.1, 0.7, 1.3),
        "working": (0.35, 0.45, 0.55, 0.4, 0.6),
        "moving": (0.22, 0.18, 0.22, 0.2, 0.35),
        "looking": (0.7, 0.5, 0.8, 0.6, 1.0),
        "heating": (0.8, 0.6, 0.9, 0.7),
        "light": (0.45, 0.35, 0.5, 0.4, 0.55),
        "done": (0.8, 0.5, 1.3, 0.7),
        "sad": (1.4, 1.1, 1.6, 0.6),
        "error": (0.45, 0.45, 0.7),
        "blank": (1.0,),
    }

    def __init__(
        self,
        parent=None,
        Port: Optional[str] = None,
        port: Optional[str] = None,
        baudrate: int = DEFAULT_BAUDRATE,
        BaudRate: Optional[int] = None,
        address: Any = DEFAULT_ADDRESS,
        Address: Any = None,
        width: int = DEFAULT_WIDTH,
        Width: Optional[int] = None,
        height: int = DEFAULT_HEIGHT,
        Height: Optional[int] = None,
        color: int = 1,
        dll_color_style: int = 0,
        font_size: int = 16,
        fontSize: Optional[int] = None,
        horizontal_align: int = 2,
        horizontalAlign: Optional[int] = None,
        vertical_align: int = 2,
        verticalAlign: Optional[int] = None,
        encoding: str = "gb2312",
        read_timeout: float = 1.0,
        write_timeout: float = 1.0,
        require_ack: bool = False,
        dtr: bool = True,
        rts: bool = True,
        animations_enabled: bool = False,
        default_expression: str = "idle",
        frame_interval: float = 0.8,
        frame_interval_jitter: float = 0.12,
        action_expression_duration: float = 2.5,
        sleep_after_seconds: float = 12.0,
        sleep_expression: str = "sleep",
        bitmap_enabled: bool = False,
        bitmap_transport: str = "serial_font",
        bitmap_visual_confirmed: bool = False,
        text_fallback_enabled: bool = False,
        bitmap_dll_path: Optional[str] = None,
        asset_library_path: Optional[str] = None,
        asset_mode_enabled: bool = True,
        connection_retry_interval: float = 3.0,
        card_number: int = 1,
        face_color: Any = (255, 0, 0),
        text: str = "",
        last_response: str = "",
        trace_enabled: bool = True,
        trace_log_path: Optional[str] = None,
        **_unused,
    ):
        self.parent = parent
        self.port = port or Port or self.DEFAULT_PORT
        self.baudrate = int(BaudRate if BaudRate is not None else baudrate)
        self.address = self._format_address(Address if Address is not None else address)
        self.width = self._positive_int(Width if Width is not None else width, "width")
        self.height = self._positive_int(Height if Height is not None else height, "height")
        self.color = int(color)
        self.dll_color_style = int(dll_color_style)
        self.font_size = int(fontSize if fontSize is not None else font_size)
        self.horizontal_align = int(horizontalAlign if horizontalAlign is not None else horizontal_align)
        self.vertical_align = int(verticalAlign if verticalAlign is not None else vertical_align)
        self.encoding = encoding
        self.read_timeout = float(read_timeout)
        self.write_timeout = float(write_timeout)
        self.require_ack = bool(require_ack)
        self.dtr = bool(dtr)
        self.rts = bool(rts)
        self._personality = DroptiBotFacePersonality()
        self.default_expression = self._personality.normalize_expression(default_expression, default="idle")
        self.frame_interval = max(0.1, float(frame_interval))
        self.frame_interval_jitter = max(0.0, float(frame_interval_jitter))
        self.action_expression_duration = max(0.1, float(action_expression_duration))
        self.sleep_after_seconds = max(1.0, float(sleep_after_seconds))
        self.sleep_expression = self._personality.normalize_expression(sleep_expression, default="sleep")
        self.bitmap_enabled = bool(bitmap_enabled)
        self.bitmap_transport = str(bitmap_transport or "serial_font")
        self.bitmap_visual_confirmed = bool(bitmap_visual_confirmed)
        self.text_fallback_enabled = bool(text_fallback_enabled)
        self.bitmap_dll_path = bitmap_dll_path
        self.asset_library_path = asset_library_path
        self.asset_mode_enabled = bool(asset_mode_enabled)
        self.connection_retry_interval = max(0.25, float(connection_retry_interval))
        self.card_number = int(card_number)
        self.face_color = self._parse_color(face_color)
        self.last_response = last_response
        self.trace_enabled = bool(trace_enabled)
        self.trace_log_path = self._resolve_trace_log_path(trace_log_path)

        self._serial_lock = threading.RLock()
        self._bitmap_lock = threading.RLock()
        self._animation_lock = threading.RLock()
        self._trace_lock = threading.RLock()
        self._animation_stop = threading.Event()
        self._animation_wake = threading.Event()
        self._animation_thread = None
        self._rng = random.Random()
        self._eq_dll = None
        self._gdi32 = None
        self._user32 = None
        self._dll_runtime_dir = None
        self._expression = self.default_expression
        self._expression_expires_at = None
        self._frame_index = 0
        self._last_frame = None
        self._panel_connected = False
        self._last_transport_error = ""
        self._asset_library = self._load_asset_library()
        self._asset_state = self._asset_expression_state(self.default_expression)
        self._asset_frame_name = self._asset_entry_frame(self._asset_state)
        self._last_activity_at = time.monotonic()
        self._animations_enabled = bool(animations_enabled)
        self._text_behavior_state = self._new_text_behavior_state()

        if self._animations_enabled:
            self.start_animation(default_expression)
        elif text:
            self.set_text(text)

    def _resolve_trace_log_path(self, trace_log_path: Optional[str]) -> Optional[Path]:
        if not self.trace_enabled:
            return None
        candidates = []
        if trace_log_path:
            candidates.append(Path(trace_log_path))
        env_path = os.environ.get("DROPLOGIC_FRONT_PANEL_TRACE_LOG")
        if env_path:
            candidates.append(Path(env_path))
        repo_root = Path(__file__).resolve().parents[5]
        candidates.append(repo_root / "runs" / "eq2013_sdk_probe" / "test_sdk_clean" / "front_panel_trace.log")
        for candidate in candidates:
            candidate = candidate.expanduser()
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            return candidate.resolve()
        return None

    def _trace_event(self, event: str, **payload) -> None:
        if not self.trace_enabled or self.trace_log_path is None:
            return
        record = {
            "ts": time.time(),
            "event": event,
            "expression": getattr(self, "_expression", None),
            "owner": getattr(getattr(self, "parent", None), "owner", None),
        }
        record.update(payload)
        try:
            self.trace_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._trace_lock:
                with self.trace_log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        except Exception:
            if self.parent is not None and hasattr(self.parent, "logger"):
                self.parent.logger.debug("DroptiBot trace write failed", exc_info=True)
            else:
                logging.getLogger("droplogic.front_panel").debug("DroptiBot trace write failed", exc_info=True)

    @property
    def expressions(self) -> Iterable[str]:
        return self._personality.supported_expressions()

    def _resolve_asset_library_path(self) -> Optional[Path]:
        candidates = []
        if self.asset_library_path:
            candidates.append(Path(self.asset_library_path))
        env_path = os.environ.get("DROPLOGIC_FRONT_PANEL_ASSET_LIBRARY")
        if env_path:
            candidates.append(Path(env_path))
        repo_root = Path(__file__).resolve().parents[5]
        candidates.extend(
            [
                Path.cwd() / "runs" / "eq2013_sdk_probe" / "test_sdk_clean" / "front_panel_state_library",
                repo_root / "runs" / "eq2013_sdk_probe" / "test_sdk_clean" / "front_panel_state_library",
            ]
        )

        for candidate in candidates:
            candidate = candidate.expanduser()
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            manifest = candidate / "manifest.json"
            if manifest.exists():
                return candidate.resolve()
        return None

    def _load_asset_library(self) -> Dict[str, Dict[str, Any]]:
        if not self.asset_mode_enabled:
            return {}
        root = self._resolve_asset_library_path()
        if root is None:
            return {}

        try:
            top_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

        library: Dict[str, Dict[str, Any]] = {}
        for state_name, summary in top_manifest.items():
            try:
                state_dir = root / state_name
                manifest_name = str(summary.get("manifest") or "manifest.json")
                manifest = json.loads((state_dir / manifest_name).read_text(encoding="utf-8"))
            except Exception:
                continue

            frames = {}
            for frame_name, frame_meta in dict(manifest.get("frames", {}) or {}).items():
                frames[frame_name] = {
                    "next": list(frame_meta.get("next", []) or []),
                    "path": str((state_dir / frame_name).resolve()),
                }

            if not frames:
                continue

            library[state_name] = {
                "root": str(state_dir),
                "entry_frame": str(manifest.get("entry_frame") or next(iter(frames))),
                "allowed_state_transitions": list(manifest.get("allowed_state_transitions", []) or []),
                "frames": frames,
            }
        return library

    def _asset_animation_available(self) -> bool:
        return self._bitmap_animation_allowed() and bool(self._asset_library)

    def _asset_expression_state(self, expression: Optional[str]) -> str:
        normalized = self._personality.normalize_expression(expression, default="idle")
        return self.ASSET_STATE_ALIASES.get(normalized, "idle")

    def _asset_entry_frame(self, state: str) -> Optional[str]:
        state_info = self._asset_library.get(state) or {}
        entry = state_info.get("entry_frame")
        if entry:
            return str(entry)
        frames = state_info.get("frames") or {}
        return next(iter(frames), None)

    def _asset_frame_path(self, state: str, frame_name: Optional[str]) -> Optional[Path]:
        if not frame_name:
            return None
        frame_info = (self._asset_library.get(state) or {}).get("frames", {}).get(frame_name)
        if not frame_info:
            return None
        return Path(frame_info["path"])

    def _asset_shortest_path(self, state: str, start_frame: Optional[str], goal_frame: Optional[str]) -> list[str]:
        if not start_frame or not goal_frame or start_frame == goal_frame:
            return [goal_frame] if goal_frame else []
        frames = (self._asset_library.get(state) or {}).get("frames", {})
        if start_frame not in frames or goal_frame not in frames:
            return [goal_frame] if goal_frame else []

        queue: deque[tuple[str, list[str]]] = deque([(start_frame, [start_frame])])
        visited = {start_frame}
        while queue:
            current, path = queue.popleft()
            for next_frame in frames[current].get("next", []):
                if next_frame in visited:
                    continue
                next_path = path + [next_frame]
                if next_frame == goal_frame:
                    return next_path
                visited.add(next_frame)
                queue.append((next_frame, next_path))
        return [goal_frame]

    def _choose_next_asset_frame(self, state: str, frame_name: Optional[str]) -> Optional[str]:
        state_info = self._asset_library.get(state) or {}
        frames = state_info.get("frames") or {}
        if not frames:
            return None
        current = frame_name if frame_name in frames else self._asset_entry_frame(state)
        if current is None:
            return None
        options = list(frames.get(current, {}).get("next", []) or [])
        if not options:
            return current
        non_self = [name for name in options if name != current]
        if non_self:
            options = non_self
        return self._rng.choice(options)

    @staticmethod
    def _parse_color(value: Any):
        if isinstance(value, str):
            value = value.strip().lower()
            named = {
                "red": (255, 0, 0),
                "green": (0, 255, 0),
                "yellow": (255, 255, 0),
                "white": (255, 255, 255),
            }
            if value in named:
                return named[value]
            if value.startswith("#") and len(value) == 7:
                return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return tuple(max(0, min(255, int(channel))) for channel in value[:3])
        return (255, 0, 0)

    @staticmethod
    def _format_address(address: Any) -> str:
        address_text = str(address).strip()
        if address_text.isdigit():
            address_num = int(address_text)
            if not 0 <= address_num <= 999:
                raise ValueError("front panel address must be between 0 and 999")
            return f"{address_num:03d}"
        if len(address_text) == 3:
            return address_text
        raise ValueError("front panel address must be a 3-character string or integer")

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        number = int(value)
        if number <= 0:
            raise ValueError(f"front panel {name} must be positive")
        return number

    @staticmethod
    def _two_digit(value: Any, name: str) -> str:
        number = int(value)
        if not 0 <= number <= 99:
            raise ValueError(f"{name} must be between 0 and 99")
        return f"{number:02d}"

    @staticmethod
    def _four_digit(value: Any, name: str) -> str:
        number = int(value)
        if not 0 <= number <= 9999:
            raise ValueError(f"{name} must be between 0 and 9999")
        return f"{number:04d}"

    @staticmethod
    def _sanitize_text(text: Any) -> str:
        text = "" if text is None else str(text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.replace("$$", "")

    @staticmethod
    def is_ack(response: str) -> bool:
        """Return whether a response looks like an EQ font-protocol ACK."""
        normalized = response.strip().upper()
        return (
            "FOK" in normalized
            or "EQFOK" in normalized
            or "KOK" in normalized
        )

    def build_text_packet(
        self,
        text: Any,
        *,
        x: int = 0,
        y: int = 0,
        width: Optional[int] = None,
        height: Optional[int] = None,
        area: int = 1,
        action: int = 1,
        speed: int = 3,
        hold_time: int = 6000,
        color: Optional[int] = None,
        font_size: Optional[int] = None,
        horizontal_align: Optional[int] = None,
        vertical_align: Optional[int] = None,
        clear_regions: bool = True,
        save: bool = False,
    ) -> str:
        """Build an EQ2013 font-protocol packet for one text region."""
        width = self.width if width is None else self._positive_int(width, "width")
        height = self.height if height is None else self._positive_int(height, "height")
        color = self.color if color is None else int(color)
        font_size = self.font_size if font_size is None else int(font_size)
        horizontal_align = self.horizontal_align if horizontal_align is None else int(horizontal_align)
        vertical_align = self.vertical_align if vertical_align is None else int(vertical_align)

        parts = [f"!#{self.address}"]
        if clear_regions:
            parts.append("%ZD00")
        parts.extend(
            [
                f"%ZI{self._two_digit(area, 'area')}",
                f"%ZC{self._four_digit(x, 'x')}{self._four_digit(y, 'y')}"
                f"{self._four_digit(width, 'width')}{self._four_digit(height, 'height')}",
                f"%ZA{self._two_digit(action, 'action')}",
                f"%ZS{self._two_digit(speed, 'speed')}",
                f"%ZH{self._four_digit(hold_time, 'hold_time')}",
                f"%F{self._two_digit(font_size, 'font_size')}",
                f"%C{color}",
                f"%AH{horizontal_align}",
                f"%AV{vertical_align}",
                self._sanitize_text(text),
            ]
        )
        if save:
            parts.append("%ZF1")
        parts.append("$$")
        return "".join(parts)

    def build_clear_packet(self) -> str:
        """Build a packet that removes all font-protocol regions."""
        return f"!#{self.address}%ZD00$$"

    def build_program_packet(self, program: int) -> str:
        """Build a stored-program switch packet."""
        program = int(program)
        if not 1 <= program <= 99:
            raise ValueError("front panel program must be between 1 and 99")
        return f"##{self.address}{program:04d}@"

    def _send_packet(self, packet: str) -> FrontPanelResponse:
        payload = packet.encode(self.encoding, errors="replace")
        response = ""

        try:
            with self._serial_lock:
                with serial.Serial(
                    self.port,
                    self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.05,
                    write_timeout=self.write_timeout,
                ) as port:
                    port.dtr = self.dtr
                    port.rts = self.rts
                    port.reset_input_buffer()
                    port.reset_output_buffer()
                    port.write(payload)
                    port.flush()

                    chunks = []
                    deadline = time.monotonic() + self.read_timeout
                    while time.monotonic() < deadline:
                        waiting = port.in_waiting
                        if waiting:
                            chunks.append(port.read(waiting))
                            decoded = b"".join(chunks).decode(self.encoding, errors="replace")
                            if self.is_ack(decoded):
                                response = decoded
                                break
                        time.sleep(0.01)
                    else:
                        if chunks:
                            response = b"".join(chunks).decode(self.encoding, errors="replace")
        except Exception as exc:
            self._panel_connected = False
            self._last_transport_error = str(exc)
            self.last_response = f"front panel transport error: {exc}"
            return FrontPanelResponse(ok=False, response=self.last_response, packet=packet)

        ok = self.is_ack(response) if self.require_ack else True
        self._panel_connected = ok
        self._last_transport_error = ""
        self.last_response = response
        return FrontPanelResponse(ok=ok, response=response, packet=packet)

    def set_text(self, text: Any, **kwargs) -> FrontPanelResponse:
        """Display text on the front panel."""
        self._mark_activity()
        return self._send_packet(self.build_text_packet(text, **kwargs))

    def _mark_activity(self):
        self._last_activity_at = time.monotonic()

    def _resolve_bitmap_dll_path(self) -> Optional[Path]:
        candidates = []
        if self.bitmap_dll_path:
            candidates.append(Path(self.bitmap_dll_path))
        env_path = os.environ.get("DROPLOGIC_EQ2008_DLL")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                Path.cwd() / "EQ2008_Dll.dll",
                Path.cwd() / "runs" / "eq2013_sdk_probe" / "runtime" / "EQ2008_Dll.dll",
                Path(__file__).resolve().parents[5]
                / "runs"
                / "eq2013_sdk_probe"
                / "runtime"
                / "EQ2008_Dll.dll",
            ]
        )

        for candidate in candidates:
            candidate = candidate.expanduser()
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            if candidate.exists():
                return candidate.resolve()
        return None

    def _write_eq_ini(self, runtime_dir: Path) -> Path:
        ini_path = runtime_dir / "EQ2008_Dll_Set.ini"
        ini = (
            "[CONT]\r\n"
            "ScreenCount=0\r\n\r\n"
            "[\u5730\u5740\uff1a0]\r\n"
            "CardType=21\r\n"
            "CardAddress=0\r\n"
            "CommunicationMode=0\r\n"
            f"ScreemHeight={self.height}\r\n"
            f"ScreemWidth={self.width}\r\n"
            f"SerialBaud={self.baudrate}\r\n"
            f"SerialNum={self._serial_number_from_port()}\r\n"
            "NetPort=5005\r\n"
            "IpAddress0=192\r\n"
            "IpAddress1=168\r\n"
            "IpAddress2=1\r\n"
            "IpAddress3=236\r\n"
            f"ColorStyle={self.dll_color_style}\r\n"
        )
        ini_path.write_text(ini, encoding="gbk")
        return ini_path

    def _serial_number_from_port(self) -> int:
        port = str(self.port).upper().replace("COM", "")
        return int(port)

    def _load_bitmap_dll(self):
        if platform.system() != "Windows":
            raise RuntimeError("DroptiBot bitmap transport requires Windows and EQ2008_Dll.dll")
        if self._eq_dll is not None:
            return self._eq_dll

        dll_path = self._resolve_bitmap_dll_path()
        if dll_path is None:
            raise FileNotFoundError("Could not find EQ2008_Dll.dll for DroptiBot bitmap transport")

        runtime_dir = dll_path.parent
        ctypes.windll.kernel32.SetDllDirectoryW(str(runtime_dir))
        dll = ctypes.WinDLL(str(dll_path))
        dll.User_ReloadIniFile.argtypes = [ctypes.c_char_p]
        dll.User_ReloadIniFile.restype = None
        dll.User_RealtimeConnect.argtypes = [ctypes.c_int]
        dll.User_RealtimeConnect.restype = ctypes.c_bool
        dll.User_RealtimeSendData.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        dll.User_RealtimeSendData.restype = ctypes.c_bool
        dll.User_RealtimeDisConnect.argtypes = [ctypes.c_int]
        dll.User_RealtimeDisConnect.restype = ctypes.c_bool

        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self._gdi32.DeleteObject.restype = ctypes.c_bool
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.LoadImageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        self._user32.LoadImageW.restype = ctypes.c_void_p

        self._dll_runtime_dir = runtime_dir
        self._eq_dll = dll
        return dll

    def _image_to_hbitmap(self, image: Image.Image):
        image = image.convert("1").resize((self.width, self.height))
        runtime_dir = self._dll_runtime_dir or Path.cwd()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="droptibot_frame_",
            suffix=".bmp",
            dir=runtime_dir,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        image.save(temp_path, format="BMP")
        hbitmap = self._user32.LoadImageW(
            None,
            str(temp_path),
            0,
            self.width,
            self.height,
            0x10,
        )
        if not hbitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        return hbitmap, temp_path

    def _bitmap_path_to_hbitmap(self, bitmap_path: Path):
        hbitmap = self._user32.LoadImageW(
            None,
            str(bitmap_path),
            0,
            self.width,
            self.height,
            0x10,
        )
        if not hbitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        return hbitmap

    def _send_hbitmap(self, hbitmap, packet_label: str) -> FrontPanelResponse:
        try:
            dll = self._load_bitmap_dll()
            ini_path = self._write_eq_ini(self._dll_runtime_dir)
            dll.User_ReloadIniFile(str(ini_path).encode("mbcs"))
            connected = bool(dll.User_RealtimeConnect(self.card_number))
            sent = False
            if connected:
                sent = bool(
                    dll.User_RealtimeSendData(
                        self.card_number,
                        0,
                        0,
                        self.width,
                        self.height,
                        hbitmap,
                    )
                )
            response = f"bitmap connect={connected} send={sent}"
            self._panel_connected = connected and sent
            self._last_transport_error = ""
            self.last_response = response
            return FrontPanelResponse(ok=connected and sent, response=response, packet=packet_label)
        except Exception as exc:
            self._panel_connected = False
            self._last_transport_error = str(exc)
            self.last_response = f"front panel bitmap error: {exc}"
            return FrontPanelResponse(ok=False, response=self.last_response, packet=packet_label)
        finally:
            try:
                if 'connected' in locals() and connected:
                    dll.User_RealtimeDisConnect(self.card_number)
            finally:
                self._gdi32.DeleteObject(hbitmap)

    def send_image(self, image: Image.Image) -> FrontPanelResponse:
        """Stream a rendered bitmap frame to the panel using the EQ DLL."""
        if not self.bitmap_enabled:
            return FrontPanelResponse(ok=False, response="bitmap transport disabled", packet="<bitmap>")
        if self.bitmap_transport != "eq_dll_realtime":
            return FrontPanelResponse(
                ok=False,
                response=f"bitmap transport unavailable for {self.bitmap_transport}",
                packet="<bitmap>",
            )

        with self._bitmap_lock:
            hbitmap, temp_path = self._image_to_hbitmap(image)
            try:
                return self._send_hbitmap(hbitmap, "<bitmap>")
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def send_bitmap_path(self, bitmap_path: Path) -> FrontPanelResponse:
        """Stream a prebuilt BMP file to the panel using the EQ DLL."""
        if not self.bitmap_enabled:
            return FrontPanelResponse(ok=False, response="bitmap transport disabled", packet=str(bitmap_path))
        if self.bitmap_transport != "eq_dll_realtime":
            return FrontPanelResponse(
                ok=False,
                response=f"bitmap transport unavailable for {self.bitmap_transport}",
                packet=str(bitmap_path),
            )

        bitmap_path = Path(bitmap_path)
        if not bitmap_path.exists():
            return FrontPanelResponse(ok=False, response=f"bitmap asset missing: {bitmap_path}", packet=str(bitmap_path))

        with self._bitmap_lock:
            self._load_bitmap_dll()
            hbitmap = self._bitmap_path_to_hbitmap(bitmap_path)
            return self._send_hbitmap(hbitmap, str(bitmap_path))

    def _bitmap_animation_allowed(self) -> bool:
        # The EQ DLL realtime bitmap API reports success over serial, but the
        # SDK documents realtime data as a network update path. Only use it for
        # animations after a visible pixel update has been confirmed.
        return (
            self.bitmap_enabled
            and self.bitmap_transport == "eq_dll_realtime"
            and self.bitmap_visual_confirmed
        )

    def clear(self) -> FrontPanelResponse:
        """Clear all font-protocol regions from the front panel."""
        return self._send_packet(self.build_clear_packet())

    def select_program(self, program: int) -> FrontPanelResponse:
        """Switch to a stored program on the controller."""
        return self._send_packet(self.build_program_packet(program))

    def _frames_for_expression(self, expression: str):
        return self._personality.frames_for_expression(expression)

    def _text_frames_for_expression(self, expression: str):
        return self.TEXT_FALLBACK_FRAMES.get(expression, self.TEXT_FALLBACK_FRAMES["thinking"])

    def _frame_delay_for_expression(self, expression: str, frame_slot: int) -> float:
        if self._asset_animation_available():
            state = self._asset_expression_state(expression)
            base_delay = float(self.ASSET_FRAME_INTERVALS.get(state, self.frame_interval))
            if state == "sleep":
                frame_name = str(self._asset_frame_name or "")
                if "open_" in frame_name or "close_" in frame_name:
                    base_delay = max(0.18, base_delay * 0.5)
            if self.frame_interval_jitter <= 0:
                return base_delay
            low = max(0.1, base_delay - self.frame_interval_jitter)
            high = max(low, base_delay + self.frame_interval_jitter)
            return self._rng.uniform(low, high)
        intervals = self.TEXT_FALLBACK_INTERVALS.get(expression)
        if intervals:
            base_delay = float(intervals[frame_slot % len(intervals)])
        else:
            base_delay = self.frame_interval * self._personality.frame_delay_multiplier(
                expression, frame_slot
            )
        if self.frame_interval_jitter <= 0:
            return base_delay
        low = max(0.1, base_delay - self.frame_interval_jitter)
        high = max(low, base_delay + self.frame_interval_jitter)
        return self._rng.uniform(low, high)

    @staticmethod
    def _new_text_behavior_state() -> Dict[str, Any]:
        return {
            "expression": None,
            "index": None,
            "hold_remaining": 0,
        }

    def _reset_text_behavior_state(self):
        self._text_behavior_state = self._new_text_behavior_state()

    def _sample_delay(self, delay_spec: Any, fallback: float) -> float:
        if isinstance(delay_spec, (int, float)):
            return max(0.1, float(delay_spec))
        if isinstance(delay_spec, (list, tuple)) and delay_spec:
            if len(delay_spec) == 1:
                return max(0.1, float(delay_spec[0]))
            low = max(0.1, float(delay_spec[0]))
            high = max(low, float(delay_spec[1]))
            return self._rng.uniform(low, high)
        return fallback

    def _sample_hold(self, hold_spec: Any) -> int:
        if isinstance(hold_spec, int):
            return max(1, hold_spec)
        if isinstance(hold_spec, (list, tuple)) and hold_spec:
            if len(hold_spec) == 1:
                return max(1, int(hold_spec[0]))
            low = max(1, int(hold_spec[0]))
            high = max(low, int(hold_spec[1]))
            return self._rng.randint(low, high)
        return 1

    def _choose_text_behavior_index(self, behaviors, previous_index: Optional[int]) -> int:
        weighted_indexes = []
        for index, behavior in enumerate(behaviors):
            weight = max(1, int(behavior.get("weight", 1)))
            if previous_index is not None and index == previous_index and len(behaviors) > 1:
                weight = max(1, weight // 4)
            weighted_indexes.extend([index] * weight)
        return self._rng.choice(weighted_indexes)

    def _next_text_fallback_frame(self, expression: str, frame_slot: int):
        behaviors = self.TEXT_FALLBACK_BEHAVIORS.get(expression)
        if not behaviors:
            text_frames = self._text_frames_for_expression(expression)
            text_slot = frame_slot % len(text_frames)
            return text_frames[text_slot], self._frame_delay_for_expression(expression, text_slot)

        state = self._text_behavior_state
        if state["expression"] != expression:
            self._reset_text_behavior_state()
            state = self._text_behavior_state
            state["expression"] = expression

        if state["index"] is not None and state["hold_remaining"] > 0:
            behavior = behaviors[state["index"]]
            state["hold_remaining"] -= 1
            fallback = self._frame_delay_for_expression(expression, state["index"])
            return behavior["text"], self._sample_delay(behavior.get("delay"), fallback)

        choice_index = self._choose_text_behavior_index(behaviors, state["index"])
        behavior = behaviors[choice_index]
        state["index"] = choice_index
        state["hold_remaining"] = max(0, self._sample_hold(behavior.get("hold", 1)) - 1)
        fallback = self._frame_delay_for_expression(expression, choice_index)
        return behavior["text"], self._sample_delay(behavior.get("delay"), fallback)

    def start_animation(self, expression: Optional[str] = None, reason: Optional[str] = None, source: Optional[str] = None):
        """Start the background face animator."""
        if expression:
            self.set_expression(expression, source=source or "start_animation", reason=reason)
        self._animations_enabled = True
        if self._animation_thread and self._animation_thread.is_alive():
            self._trace_event("animation_start", source=source, reason=reason, thread_action="reuse")
            return True
        self._animation_stop.clear()
        self._animation_thread = threading.Thread(
            target=self._animation_loop,
            name="DroptiBotFaceAnimator",
            daemon=True,
        )
        self._animation_thread.start()
        self._trace_event("animation_start", source=source, reason=reason, thread_action="spawn")
        return True

    def stop_animation(self, reason: Optional[str] = None, source: Optional[str] = None):
        """Stop the background face animator."""
        self._animations_enabled = False
        self._animation_stop.set()
        self._animation_wake.set()
        if self._animation_thread and self._animation_thread.is_alive():
            self._animation_thread.join(timeout=1.0)
        self._trace_event("animation_stop", source=source, reason=reason)
        return True

    def set_expression(
        self,
        expression: str,
        duration: Optional[float] = None,
        immediate: bool = False,
        *,
        source: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        """Set the current DroptiBot face expression."""
        expression = self._personality.normalize_expression(expression, default="thinking")
        if expression != self.sleep_expression:
            self._mark_activity()

        with self._animation_lock:
            self._expression = expression
            self._expression_expires_at = (
                time.monotonic() + float(duration) if duration is not None else None
            )
            self._frame_index = 0
            self._last_frame = None
            self._asset_state = self._asset_expression_state(expression)
            self._asset_frame_name = self._asset_entry_frame(self._asset_state)
            self._reset_text_behavior_state()

        self._trace_event(
            "set_expression",
            target_expression=expression,
            duration=duration,
            immediate=immediate,
            source=source,
            reason=reason,
        )

        self._animation_wake.set()
        if not self._animations_enabled or immediate:
            if self._asset_animation_available():
                frame = self._asset_frame_path(self._asset_state, self._asset_frame_name)
                if frame is None:
                    frame = self._frames_for_expression(expression)[0]
            else:
                frame = self._frames_for_expression(expression)[0]
            return self._send_face_frame(frame, expression)
        return True

    def notify_action(self, path: str, value: Any = None):
        """Update the face according to a BOXMini command path."""
        self._mark_activity()
        expression = self._personality.expression_for_action(path)
        self._trace_event("notify_action", path=path, value_repr=repr(value), action_expression=expression)
        return self.set_expression(
            expression,
            duration=self.action_expression_duration,
            source="notify_action",
            reason=path,
        )

    def _next_animation_frame(self):
        now = time.monotonic()
        with self._animation_lock:
            if self._expression_expires_at is not None and now >= self._expression_expires_at:
                if now - self._last_activity_at >= self.sleep_after_seconds:
                    self._expression = self.sleep_expression
                else:
                    self._expression = self.default_expression
                self._expression_expires_at = None
                self._frame_index = 0
                self._last_frame = None
                self._reset_text_behavior_state()
            elif (
                self._expression == self.default_expression
                and now - self._last_activity_at >= self.sleep_after_seconds
            ):
                self._expression = self.sleep_expression
                self._frame_index = 0
                self._last_frame = None
                self._reset_text_behavior_state()

            if self._asset_animation_available():
                state = self._asset_expression_state(self._expression)
                frame_name = self._asset_frame_name
                if self._asset_state != state:
                    current_entry = self._asset_entry_frame(self._asset_state)
                    if (
                        self._asset_state in self._asset_library
                        and frame_name
                        and current_entry
                        and frame_name != current_entry
                    ):
                        path = self._asset_shortest_path(self._asset_state, frame_name, current_entry)
                        next_name = path[1] if len(path) > 1 else current_entry
                        self._asset_frame_name = next_name
                        frame_path = self._asset_frame_path(self._asset_state, next_name)
                        self._last_frame = str(frame_path) if frame_path else None
                        return frame_path, self._expression, None, self._frame_delay_for_expression(self._expression, 0)
                    self._asset_state = state
                    self._asset_frame_name = self._asset_entry_frame(state)
                    frame_name = self._asset_frame_name

                if frame_name is None:
                    frame_name = self._asset_entry_frame(state)
                    self._asset_frame_name = frame_name
                frame_path = self._asset_frame_path(state, frame_name)
                next_name = self._choose_next_asset_frame(state, frame_name)
                self._asset_state = state
                self._asset_frame_name = next_name
                frame_delay = self._frame_delay_for_expression(self._expression, 0)
                frame_key = str(frame_path) if frame_path else None
                if frame_key == self._last_frame:
                    return None
                self._last_frame = frame_key
                return frame_path, self._expression, None, frame_delay

            frames = self._frames_for_expression(self._expression)
            frame_slot = self._frame_index % len(frames)
            frame = frames[frame_slot]
            frame_delay = self._frame_delay_for_expression(self._expression, frame_slot)
            self._frame_index += 1
            if frame == self._last_frame:
                return None
            self._last_frame = frame
            return frame, self._expression, None, frame_delay

    @staticmethod
    def _draw_pixel_z(draw: ImageDraw.ImageDraw, x: int, y: int, scale: int, color):
        if scale <= 0:
            return
        draw.line((x, y, x + 2 * scale, y), fill=color, width=1)
        draw.line((x + 2 * scale, y, x, y + 2 * scale), fill=color, width=1)
        draw.line((x, y + 2 * scale, x + 2 * scale, y + 2 * scale), fill=color, width=1)

    def _draw_symbol(self, draw: ImageDraw.ImageDraw, frame: Dict[str, Any], color):
        symbol = frame.get("symbol")
        if symbol == "sleep_zz":
            phase = int(frame.get("symbol_phase", 0))
            positions = (
                ((36, 1, 1), (41, 4, 2)),
                ((38, 1, 1), (42, 3, 2)),
                ((40, 0, 1), (43, 2, 2)),
            )
            for x, y, scale in positions[phase % len(positions)]:
                self._draw_pixel_z(draw, x, y, scale, color)

    def _render_face(self, frame: Dict[str, Any]) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), "black")
        if frame.get("blank"):
            return image

        draw = ImageDraw.Draw(image)
        color = self.face_color
        eye_w = 14
        base_open = float(frame.get("open", 1.0))
        left_open = max(0.08, float(frame.get("left_open", base_open)))
        right_open = max(0.08, float(frame.get("right_open", base_open)))
        left_h = max(3, int(10 * left_open))
        right_h = max(3, int(10 * right_open))
        gaze_y = int(frame.get("pupil_y", 0))
        pupil_x = int(frame.get("pupil_x", 0))
        left_eye_y = max(2, 3 + (10 - left_h) // 2 + gaze_y)
        right_eye_y = max(2, 3 + (10 - right_h) // 2 + gaze_y)
        left_x = 6 + min(0, pupil_x)
        right_x = 28 + max(0, pupil_x)
        if frame.get("motion") == "right":
            left_x += 1
            right_x += 1
        elif frame.get("motion") == "left":
            left_x -= 1
            right_x -= 1
        if frame.get("curiosity"):
            if pupil_x < 0:
                left_h = min(self.height - 2, left_h + 2)
            elif pupil_x > 0:
                right_h = min(self.height - 2, right_h + 2)
        left = (left_x, left_eye_y, left_x + eye_w, left_eye_y + left_h)
        right = (right_x, right_eye_y, right_x + eye_w, right_eye_y + right_h)

        def draw_eye(box):
            draw.ellipse(box, fill=color)

        for box in (left, right):
            draw_eye(box)

        if frame.get("spark"):
            draw.line((46, 1, 46, 5), fill=color)
            draw.line((44, 3, 48, 3), fill=color)
        if frame.get("sweat"):
            draw.line((40, 0, 42, 3), fill=color)
            draw.line((42, 3, 40, 6), fill=color)
        if frame.get("motion") == "right":
            draw.line((0, 8, 2, 8), fill=color)
            draw.point((1, 7), fill=color)
            draw.point((1, 9), fill=color)
        elif frame.get("motion") == "left":
            draw.line((46, 8, 48, 8), fill=color)
            draw.point((47, 7), fill=color)
            draw.point((47, 9), fill=color)
        if "heat" in frame:
            offset = int(frame["heat"])
            for x in (1, 46):
                draw.arc((x, 1 + offset, x + 4, 7 + offset), start=90, end=270, fill=color)
        self._draw_symbol(draw, frame, color)

        return image

    def _send_face_frame(self, frame, expression: str, text_frame: Optional[str] = None):
        frame_id = None
        if isinstance(frame, Path):
            frame_id = frame.name
        elif isinstance(frame, dict):
            frame_id = frame.get("symbol") or frame.get("mood") or "procedural"
        elif text_frame is not None:
            frame_id = text_frame
        if self._asset_animation_available() and isinstance(frame, Path):
            try:
                response = self.send_bitmap_path(frame)
                self._trace_event("send_frame", expression=expression, frame_id=frame_id, transport="asset_bitmap", ok=response.ok)
                if response.ok:
                    return response
                self.last_response = response.response
            except Exception as exc:
                self.last_response = f"bitmap asset failed: {exc}"
                if self.parent is not None and hasattr(self.parent, "logger"):
                    self.parent.logger.debug("DroptiBot asset frame failed", exc_info=True)

        if self._bitmap_animation_allowed() and isinstance(frame, dict):
            try:
                response = self.send_image(self._render_face(frame))
                self._trace_event("send_frame", expression=expression, frame_id=frame_id, transport="bitmap_render", ok=response.ok)
                if response.ok:
                    return response
                self.last_response = response.response
            except Exception as exc:
                self.last_response = f"bitmap failed: {exc}"
                if self.parent is not None and hasattr(self.parent, "logger"):
                    self.parent.logger.debug("DroptiBot bitmap frame failed", exc_info=True)

        if self.text_fallback_enabled:
            if text_frame is None:
                text_frame = self._text_frames_for_expression(expression)[0]
            self._trace_event("send_frame", expression=expression, frame_id=text_frame, transport="text", ok=True)
            return self.set_text(text_frame)

        response = "no confirmed pixel transport for DroptiBot expression"
        self.last_response = response
        self._trace_event("send_frame", expression=expression, frame_id=frame_id, transport="none", ok=False, response=response)
        return FrontPanelResponse(ok=False, response=response, packet="<expression>")

    def _animation_loop(self):
        next_delay = self.frame_interval
        while not self._animation_stop.is_set():
            frame_info = self._next_animation_frame()
            if frame_info is not None:
                try:
                    frame, expression, text_frame, next_delay = frame_info
                    response = self._send_face_frame(frame, expression, text_frame=text_frame)
                    if not getattr(response, "ok", False):
                        next_delay = min(max(0.25, next_delay), self.connection_retry_interval)
                except Exception:
                    if self.parent is not None and hasattr(self.parent, "logger"):
                        self.parent.logger.debug("DroptiBot animation frame failed", exc_info=True)
                    next_delay = min(max(0.25, next_delay), self.connection_retry_interval)
            self._animation_wake.wait(next_delay)
            self._animation_wake.clear()

    def blackout(self):
        """Render a blank frame and stop background animation."""
        self.stop_animation()
        blank_frames = self._frames_for_expression("blank")
        if blank_frames:
            return self._send_face_frame(blank_frames[0], "blank")
        return self.clear()

    def close(self, *, blackout: bool = False):
        """Stop animation; serial handles are opened only per write."""
        if blackout:
            try:
                self.blackout()
            except Exception:
                if self.parent is not None and hasattr(self.parent, "logger"):
                    self.parent.logger.debug("DroptiBot blackout frame failed", exc_info=True)
            return None

        self.stop_animation()
        try:
            self._send_face_frame(
                self._frames_for_expression(self.sleep_expression)[-1],
                self.sleep_expression,
            )
        except Exception:
            if self.parent is not None and hasattr(self.parent, "logger"):
                self.parent.logger.debug("DroptiBot shutdown frame failed", exc_info=True)
        return None
