"""DroptiBot v1.0 face controller for EQ2013-U front panels."""

from __future__ import annotations

import ctypes
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import serial
from PIL import Image, ImageDraw

from ..front_panel_types import FrontPanelResponse


class DroptiBotV1:
    """EQ2013 front-panel driver with a DroptiBot face state machine."""

    DISPLAY_VERSION = "DroptiBot v1.0"
    DEFAULT_PORT = "COM16"
    DEFAULT_BAUDRATE = 57600
    DEFAULT_ADDRESS = "001"
    DEFAULT_WIDTH = 48
    DEFAULT_HEIGHT = 16

    DEFAULT_FACE_FRAMES = {
        "idle": (
            {"open": 1.0, "pupil": 0, "brow": 0, "smile": 1},
            {"open": 0.25, "pupil": 0, "brow": 0, "smile": 1},
            {"open": 1.0, "pupil": 1, "brow": 0, "smile": 1},
            {"open": 1.0, "pupil": -1, "brow": 0, "smile": 1},
        ),
        "thinking": (
            {"open": 1.0, "pupil": -1, "brow": 1, "mouth": "dot"},
            {"open": 0.75, "pupil": 1, "brow": 1, "mouth": "dot"},
            {"open": 1.0, "pupil": 0, "brow": 1, "spark": True, "mouth": "dot"},
        ),
        "working": (
            {"open": 0.85, "pupil": -1, "brow": -1, "mouth": "line"},
            {"open": 0.85, "pupil": 1, "brow": -1, "mouth": "line"},
            {"open": 0.6, "pupil": 0, "brow": -1, "mouth": "line"},
        ),
        "moving": (
            {"open": 1.0, "pupil": 2, "brow": 0, "mouth": "line"},
            {"open": 1.0, "pupil": 3, "brow": 0, "motion": "right", "mouth": "line"},
            {"open": 1.0, "pupil": -2, "brow": 0, "motion": "left", "mouth": "line"},
        ),
        "looking": (
            {"open": 1.0, "pupil": 0, "brow": 0, "mouth": "dot"},
            {"open": 1.0, "pupil": 2, "brow": 0, "spark": True, "mouth": "dot"},
            {"open": 1.0, "pupil": -2, "brow": 0, "mouth": "dot"},
        ),
        "heating": (
            {"open": 0.8, "pupil": 0, "brow": 0, "heat": 0, "mouth": "line"},
            {"open": 0.8, "pupil": 0, "brow": 0, "heat": 1, "mouth": "line"},
        ),
        "light": (
            {"open": 1.0, "pupil": 0, "brow": 1, "spark": True, "smile": 1},
            {"open": 1.0, "pupil": 0, "brow": 1, "spark": True, "smile": 2},
        ),
        "done": (
            {"open": 1.0, "pupil": 0, "brow": 1, "smile": 2},
            {"open": 0.8, "pupil": 0, "brow": 1, "smile": 2},
        ),
        "error": (
            {"open": 0.6, "pupil": 0, "brow": -1, "error": True, "mouth": "frown"},
            {"open": 1.0, "pupil": 0, "brow": -1, "error": True, "mouth": "frown"},
        ),
        "blank": ({"blank": True},),
    }

    TEXT_FALLBACK_FRAMES = {
        "idle": ("o_o", "-_-", "o_o", "^_^"),
        "thinking": ("o_o?", "-_?", "o_?", "o_o?"),
        "working": ("o_o", "o_O", "O_o", "o_o"),
        "moving": (">_>", ">>_", ">_>", "_<<"),
        "looking": ("[o]", "[O]", "[o]"),
        "heating": ("~_~", "^_^", "~_~"),
        "light": ("*_*", "O_O", "*_*"),
        "done": ("^_^", "o_o"),
        "error": (">_<", "x_x", ">_<"),
        "blank": ("",),
    }

    ACTION_EXPRESSIONS = {
        "xy_stage.": "moving",
        "electrode_matrix.": "working",
        "temperature.": "heating",
        "camera_settings.": "looking",
        "microscope_settings.": "looking",
        "light_settings.": "light",
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
        action_expression_duration: float = 2.5,
        bitmap_enabled: bool = False,
        bitmap_transport: str = "serial_font",
        bitmap_visual_confirmed: bool = False,
        text_fallback_enabled: bool = False,
        bitmap_dll_path: Optional[str] = None,
        card_number: int = 1,
        face_color: Any = (255, 0, 0),
        text: str = "",
        last_response: str = "",
        **_unused,
    ):
        self.parent = parent
        self.port = port or Port or self.DEFAULT_PORT
        self.baudrate = int(BaudRate if BaudRate is not None else baudrate)
        self.address = self._format_address(Address if Address is not None else address)
        self.width = self._positive_int(Width if Width is not None else width, "width")
        self.height = self._positive_int(Height if Height is not None else height, "height")
        self.color = int(color)
        self.font_size = int(fontSize if fontSize is not None else font_size)
        self.horizontal_align = int(horizontalAlign if horizontalAlign is not None else horizontal_align)
        self.vertical_align = int(verticalAlign if verticalAlign is not None else vertical_align)
        self.encoding = encoding
        self.read_timeout = float(read_timeout)
        self.write_timeout = float(write_timeout)
        self.require_ack = bool(require_ack)
        self.dtr = bool(dtr)
        self.rts = bool(rts)
        self.default_expression = default_expression
        self.frame_interval = max(0.1, float(frame_interval))
        self.action_expression_duration = max(0.1, float(action_expression_duration))
        self.bitmap_enabled = bool(bitmap_enabled)
        self.bitmap_transport = str(bitmap_transport or "serial_font")
        self.bitmap_visual_confirmed = bool(bitmap_visual_confirmed)
        self.text_fallback_enabled = bool(text_fallback_enabled)
        self.bitmap_dll_path = bitmap_dll_path
        self.card_number = int(card_number)
        self.face_color = self._parse_color(face_color)
        self.last_response = last_response

        self._serial_lock = threading.RLock()
        self._bitmap_lock = threading.RLock()
        self._animation_lock = threading.RLock()
        self._animation_stop = threading.Event()
        self._animation_wake = threading.Event()
        self._animation_thread = None
        self._eq_dll = None
        self._gdi32 = None
        self._dll_runtime_dir = None
        self._expression = default_expression
        self._expression_expires_at = None
        self._frame_index = 0
        self._last_frame = None
        self._animations_enabled = bool(animations_enabled)

        if self._animations_enabled:
            self.start_animation(default_expression)
        elif text:
            self.set_text(text)

    @property
    def expressions(self) -> Iterable[str]:
        return self.DEFAULT_FACE_FRAMES.keys()

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

        ok = self.is_ack(response) if self.require_ack else True
        self.last_response = response
        return FrontPanelResponse(ok=ok, response=response, packet=packet)

    def set_text(self, text: Any, **kwargs) -> FrontPanelResponse:
        """Display text on the front panel."""
        return self._send_packet(self.build_text_packet(text, **kwargs))

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
            "ColorStyle=1\r\n"
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
        self._gdi32.CreateBitmap.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        self._gdi32.CreateBitmap.restype = ctypes.c_void_p
        self._gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self._gdi32.DeleteObject.restype = ctypes.c_bool

        self._dll_runtime_dir = runtime_dir
        self._eq_dll = dll
        return dll

    def _image_to_hbitmap(self, image: Image.Image):
        image = image.convert("RGBA").resize((self.width, self.height))
        bits = bytearray()
        for y in range(self.height):
            for x in range(self.width):
                r, g, b, a = image.getpixel((x, y))
                bits.extend((b, g, r, a))
        buffer = ctypes.create_string_buffer(bytes(bits))
        hbitmap = self._gdi32.CreateBitmap(
            self.width,
            self.height,
            1,
            32,
            ctypes.byref(buffer),
        )
        if not hbitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        return hbitmap, buffer

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
            dll = self._load_bitmap_dll()
            ini_path = self._write_eq_ini(self._dll_runtime_dir)
            dll.User_ReloadIniFile(str(ini_path).encode("mbcs"))
            hbitmap, _buffer = self._image_to_hbitmap(image)
            connected = False
            try:
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
                self.last_response = response
                return FrontPanelResponse(ok=connected and sent, response=response, packet="<bitmap>")
            finally:
                try:
                    if connected:
                        dll.User_RealtimeDisConnect(self.card_number)
                finally:
                    self._gdi32.DeleteObject(hbitmap)

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
        return self.DEFAULT_FACE_FRAMES.get(expression, self.DEFAULT_FACE_FRAMES["thinking"])

    def _text_frames_for_expression(self, expression: str):
        return self.TEXT_FALLBACK_FRAMES.get(expression, self.TEXT_FALLBACK_FRAMES["thinking"])

    def start_animation(self, expression: Optional[str] = None):
        """Start the background face animator."""
        if expression:
            self.set_expression(expression)
        self._animations_enabled = True
        if self._animation_thread and self._animation_thread.is_alive():
            return True
        self._animation_stop.clear()
        self._animation_thread = threading.Thread(
            target=self._animation_loop,
            name="DroptiBotFaceAnimator",
            daemon=True,
        )
        self._animation_thread.start()
        return True

    def stop_animation(self):
        """Stop the background face animator."""
        self._animations_enabled = False
        self._animation_stop.set()
        self._animation_wake.set()
        if self._animation_thread and self._animation_thread.is_alive():
            self._animation_thread.join(timeout=1.0)
        return True

    def set_expression(self, expression: str, duration: Optional[float] = None, immediate: bool = False):
        """Set the current DroptiBot face expression."""
        expression = str(expression or self.default_expression)
        if expression not in self.DEFAULT_FACE_FRAMES:
            expression = "thinking"

        with self._animation_lock:
            self._expression = expression
            self._expression_expires_at = (
                time.monotonic() + float(duration) if duration is not None else None
            )
            self._frame_index = 0
            self._last_frame = None

        self._animation_wake.set()
        if not self._animations_enabled or immediate:
            frame = self._frames_for_expression(expression)[0]
            return self._send_face_frame(frame, expression)
        return True

    def notify_action(self, path: str, value: Any = None):
        """Update the face according to a BOXMini command path."""
        for prefix, expression in self.ACTION_EXPRESSIONS.items():
            if path.startswith(prefix):
                return self.set_expression(expression, duration=self.action_expression_duration)
        return self.set_expression("thinking", duration=self.action_expression_duration)

    def _next_animation_frame(self):
        now = time.monotonic()
        with self._animation_lock:
            if self._expression_expires_at is not None and now >= self._expression_expires_at:
                self._expression = self.default_expression
                self._expression_expires_at = None
                self._frame_index = 0
                self._last_frame = None

            frames = self._frames_for_expression(self._expression)
            frame = frames[self._frame_index % len(frames)]
            self._frame_index += 1
            if frame == self._last_frame:
                return None
            self._last_frame = frame
            return frame, self._expression

    def _render_face(self, frame: Dict[str, Any]) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), "black")
        if frame.get("blank"):
            return image

        draw = ImageDraw.Draw(image)
        color = self.face_color
        eye_w = 17
        eye_h = max(2, int(10 * float(frame.get("open", 1.0))))
        eye_y = 3 + (10 - eye_h) // 2
        left = (4, eye_y, 4 + eye_w, eye_y + eye_h)
        right = (27, eye_y, 27 + eye_w, eye_y + eye_h)

        for box in (left, right):
            radius = min(5, max(1, eye_h // 2))
            draw.rounded_rectangle(box, radius=radius, fill=color)

        if not frame.get("error"):
            pupil_shift = int(frame.get("pupil", 0))
            pupil_y = 7
            for px in (12 + pupil_shift, 35 + pupil_shift):
                draw.ellipse((px, pupil_y - 2, px + 4, pupil_y + 2), fill="black")
                draw.point((px + 1, pupil_y - 1), fill=color)
        else:
            for x in (9, 32):
                draw.line((x, 5, x + 7, 11), fill="black", width=2)
                draw.line((x + 7, 5, x, 11), fill="black", width=2)

        brow = int(frame.get("brow", 0))
        if brow:
            if brow > 0:
                draw.line((5, 2, 18, 0), fill=color)
                draw.line((30, 0, 43, 2), fill=color)
            else:
                draw.line((5, 0, 18, 2), fill=color)
                draw.line((30, 2, 43, 0), fill=color)

        mouth = frame.get("mouth")
        smile = int(frame.get("smile", 0))
        if smile:
            y = 13
            draw.arc((20, 9, 28, 16), start=15, end=165, fill=color)
            if smile > 1:
                draw.point((21, 14), fill=color)
                draw.point((27, 14), fill=color)
        elif mouth == "line":
            draw.line((21, 14, 27, 14), fill=color)
        elif mouth == "dot":
            draw.ellipse((23, 13, 25, 15), fill=color)
        elif mouth == "frown":
            draw.arc((20, 12, 28, 20), start=195, end=345, fill=color)

        if frame.get("spark"):
            draw.line((46, 1, 46, 5), fill=color)
            draw.line((44, 3, 48, 3), fill=color)
        if frame.get("motion") == "right":
            draw.line((0, 7, 3, 7), fill=color)
            draw.point((2, 6), fill=color)
            draw.point((2, 8), fill=color)
        elif frame.get("motion") == "left":
            draw.line((45, 7, 48, 7), fill=color)
            draw.point((45, 6), fill=color)
            draw.point((45, 8), fill=color)
        if "heat" in frame:
            offset = int(frame["heat"])
            for x in (1, 46):
                draw.arc((x, 1 + offset, x + 4, 7 + offset), start=90, end=270, fill=color)

        return image

    def _send_face_frame(self, frame, expression: str):
        if self._bitmap_animation_allowed() and isinstance(frame, dict):
            try:
                response = self.send_image(self._render_face(frame))
                if response.ok:
                    return response
                self.last_response = response.response
            except Exception as exc:
                self.last_response = f"bitmap failed: {exc}"
                if self.parent is not None and hasattr(self.parent, "logger"):
                    self.parent.logger.debug("DroptiBot bitmap frame failed", exc_info=True)

        if self.text_fallback_enabled:
            text_frame = self._text_frames_for_expression(expression)[0]
            return self.set_text(text_frame)

        response = "no confirmed pixel transport for DroptiBot expression"
        self.last_response = response
        return FrontPanelResponse(ok=False, response=response, packet="<expression>")

    def _animation_loop(self):
        while not self._animation_stop.is_set():
            frame_info = self._next_animation_frame()
            if frame_info is not None:
                try:
                    frame, expression = frame_info
                    self._send_face_frame(frame, expression)
                except Exception:
                    if self.parent is not None and hasattr(self.parent, "logger"):
                        self.parent.logger.debug("DroptiBot animation frame failed", exc_info=True)
            self._animation_wake.wait(self.frame_interval)
            self._animation_wake.clear()

    def close(self):
        """Stop animation; serial handles are opened only per write."""
        self.stop_animation()
        return None
