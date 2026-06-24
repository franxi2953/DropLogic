"""Interactive BOXMini stage calibration tool.

This is a lighter, standalone successor to the old terminal calibration script.
It initializes BOXMini hardware only when executed, lets the user jog the stage,
records reference electrode positions, and writes the resulting calibration back
to the selected ``config.json``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import threading
import time
from typing import Dict, Optional

import cv2
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from droplogic.base import Priority
from droplogic.hardware.box_mini1 import BOXMini


console = Console()

DROPLOGIC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = DROPLOGIC_ROOT / "config.json"

VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_MINUS = 0xBD
VK_PLUS = 0xBB
VK_RETURN = 0x0D
VK_PAGE_UP = 0x21
VK_PAGE_DOWN = 0x22
VK_NUMPAD_PLUS = 0x6B
VK_NUMPAD_MINUS = 0x6D

JOG_KEEPALIVE_INTERVAL_SECONDS = 0.08
POSITION_POLL_SECONDS = 0.05
DEFAULT_COAXIAL_INTENSITY = 10
DEFAULT_EXPOSURE_US = 10000
TRAVEL_VELOCITY = 10000.0
TRAVEL_ACCELERATION = 1000000.0

SPEEDS = {
    "1": ("fine", 200.0, 2000.0),
    "2": ("medium", 1000.0, 10000.0),
    "3": ("fast", 5000.0, 100000.0),
}


def resolve_config_path(cli_config: Optional[str] = None) -> Path:
    """Resolve the config file used by both BOXMini and the calibration writer."""
    if cli_config:
        return Path(cli_config).expanduser().resolve()

    env_config = os.environ.get("DROPLOGIC_CONFIG")
    if env_config:
        return Path(env_config).expanduser().resolve()

    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        return cwd_config.resolve()

    return DEFAULT_CONFIG_PATH.resolve()


def load_config(config_path: Path) -> Dict:
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_config(config_path: Path, config_data: Dict) -> None:
    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(config_data, handle, indent=4)
        handle.write("\n")
    os.replace(temp_path, config_path)


def stage_position_from_state(box: BOXMini) -> Dict[str, int]:
    position = box.state.get("xy_stage", {}).get("position", {})
    return {
        "X": int(round(float(position.get("X", 0)))),
        "Y": int(round(float(position.get("Y", 0)))),
        "Z": int(round(float(position.get("Z", 0)))),
    }


def electrode_to_stage_from_config(
    row: int,
    column: int,
    config_data: Dict,
    *,
    include_offsets: bool = False,
) -> Dict[str, int]:
    """Convert an electrode coordinate to stage coordinates using in-memory config.

    Calibration targets deliberately ignore offset_x/offset_y. Those offsets are a
    post-calibration correction; including them would make electrode (0,0) miss the
    saved chip_origin.
    """
    mapping = config_data["calibration"]["electrode_mapping"]
    origin = config_data["calibration"]["chip_origin"]
    inter_row = mapping["inter_row"]
    inter_column = mapping["inter_column"]
    offset_x = mapping.get("offset_x", 0) if include_offsets else 0
    offset_y = mapping.get("offset_y", 0) if include_offsets else 0

    x_offset = row * inter_row[0] + column * inter_column[0] + offset_x
    y_offset = row * inter_row[1] + column * inter_column[1] + offset_y
    z_offset = row * inter_row[2] + column * inter_column[2]

    return {
        "X": int(round(float(origin["X"]) + x_offset)),
        "Y": int(round(float(origin["Y"]) + y_offset)),
        "Z": int(round(float(origin["Z"]) + z_offset)),
    }


def ensure_calibration_shape(config_data: Dict) -> None:
    calibration = config_data.setdefault("calibration", {})
    calibration.setdefault("chip_origin", {"X": 0, "Y": 0, "Z": 0})
    mapping = calibration.setdefault("electrode_mapping", {})
    mapping.setdefault("offset_x", 0)
    mapping.setdefault("offset_y", 0)
    mapping.setdefault("inter_row", [0, 0, 0])
    mapping.setdefault("inter_column", [0, 0, 0])

    for key in ("inter_row", "inter_column"):
        values = list(mapping.get(key, [0, 0, 0]))
        while len(values) < 3:
            values.append(0)
        mapping[key] = values[:3]


class KeyPoller:
    """Small Windows key poller used to keep jogging fail-safe."""

    def __init__(self) -> None:
        import ctypes

        self._user32 = ctypes.windll.user32

    def pressed(self, vk_code: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(vk_code) & 0x8000)

    def just_pressed(self, vk_code: int, previous: Dict[int, bool]) -> bool:
        current = self.pressed(vk_code)
        was_pressed = previous.get(vk_code, False)
        previous[vk_code] = current
        return current and not was_pressed


class StageCalibrationSession:
    """Interactive calibration session for BOXMini stage/electrode mapping."""

    def __init__(self, config_path: Path, *, start_video: bool = True) -> None:
        self.config_path = config_path
        self.config_data = load_config(config_path)
        ensure_calibration_shape(self.config_data)
        self.travel_config_data = copy.deepcopy(self.config_data)
        self.box: Optional[BOXMini] = None
        self.start_video = start_video
        self.exit_flag = threading.Event()
        self.position = {"X": 0, "Y": 0, "Z": 0}
        self.reference_points: Dict[str, Dict[str, int]] = {}
        self.speed_key = "2"
        self.key_poller = KeyPoller()
        self._previous_keys: Dict[int, bool] = {}
        self._last_jog_by_axis = {"X": 0, "Y": 0, "Z": 0}
        self._last_keepalive_by_axis = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self._position_thread: Optional[threading.Thread] = None
        self.guided_index = 0
        self.workflow_complete = False
        self.status_message = "Initializing"
        self.target_rectangle_color = (0, 255, 255)
        self.traveling_to_guided_target = False
        self.travel_started_at = 0.0

    @property
    def speed_name(self) -> str:
        return SPEEDS[self.speed_key][0]

    @property
    def current_origin(self) -> Dict[str, int]:
        origin = self.config_data["calibration"]["chip_origin"]
        return {
            "X": int(round(float(origin.get("X", 0)))),
            "Y": int(round(float(origin.get("Y", 0)))),
            "Z": int(round(float(origin.get("Z", 0)))),
        }

    @property
    def rows(self) -> int:
        return int(self.config_data.get("electrode_matrix", {}).get("rows", 128))

    @property
    def columns(self) -> int:
        return int(self.config_data.get("electrode_matrix", {}).get("columns", 128))

    def reload_config(self) -> None:
        self.config_data = load_config(self.config_path)
        ensure_calibration_shape(self.config_data)

    @property
    def guided_steps(self):
        return [
            {
                "key": "origin",
                "label": "electrode (0,0)",
                "row": 0,
                "column": 0,
                "record": self.record_origin,
            },
            {
                "key": "row",
                "label": f"electrode ({self.rows - 1},0)",
                "row": self.rows - 1,
                "column": 0,
                "record": self.record_row_reference,
            },
            {
                "key": "column",
                "label": f"electrode (0,{self.columns - 1})",
                "row": 0,
                "column": self.columns - 1,
                "record": self.record_column_reference,
            },
        ]

    @property
    def current_guided_step(self):
        if self.guided_index >= len(self.guided_steps):
            return None
        return self.guided_steps[self.guided_index]

    def run(self) -> None:
        self.reload_config()
        self.travel_config_data = copy.deepcopy(self.config_data)
        first_target = electrode_to_stage_from_config(0, 0, self.config_data)
        console.print(
            "[bold yellow]This will initialize real BOXMini hardware.[/] "
            "Close the machine or press Ctrl+C if it is not ready."
        )
        console.print(f"[cyan]Config:[/] {self.config_path}")
        console.print(f"[cyan]Initial target electrode (0,0):[/] {first_target}")
        self.box = BOXMini(config_file=str(self.config_path))
        self.position = stage_position_from_state(self.box)
        self._apply_speed()
        self._configure_optics()
        self._start_visualizers()
        self._start_position_thread()
        self.move_to_current_guided_estimate()

        try:
            with Live(self._render(), refresh_per_second=10, screen=False) as live:
                while not self.exit_flag.is_set():
                    self._handle_keys()
                    live.update(self._render())
                    time.sleep(0.01)
        except KeyboardInterrupt:
            self.exit_flag.set()
        finally:
            self.close()

    def close(self) -> None:
        self.exit_flag.set()
        self._stop_all_jogs()

        if self._position_thread and self._position_thread.is_alive():
            self._position_thread.join(timeout=1.0)

        if self.box is not None:
            try:
                self.box.close()
            finally:
                self.box = None

    def _start_visualizers(self) -> None:
        if not self.start_video or self.box is None:
            return

        visualizers = getattr(self.box, "visualizers", None)
        if not visualizers:
            return

        streamer = getattr(visualizers, "streamer", None)
        if streamer is not None:
            try:
                streamer.electrode_overlay = True
                streamer.coordinates = True
                streamer.set_processor(self._frame_processor)
                streamer.start()
            except Exception as exc:
                console.print(f"[yellow]Could not start live stream: {exc}[/]")

        matrix = getattr(visualizers, "matrix", None)
        if matrix is not None:
            try:
                matrix.start()
            except Exception as exc:
                console.print(f"[yellow]Could not start matrix visualizer: {exc}[/]")

    def _configure_optics(self) -> None:
        """Set a predictable brightfield view for calibration."""
        self._queue_update("light_settings.ring_intensity", 0)
        self._queue_update("light_settings.coaxial_intensity", DEFAULT_COAXIAL_INTENSITY)
        self._queue_update("microscope_settings.current_channel", "Brightfield")
        self._queue_update("microscope_settings.auto_exposure", False)
        self._queue_update("microscope_settings.exposure_time", DEFAULT_EXPOSURE_US)
        self._queue_update("camera_settings.auto_exposure", False)
        self._queue_update("camera_settings.exposure_time", DEFAULT_EXPOSURE_US)

    def _frame_processor(self, frame):
        """Draw calibration crosshair and the electrode currently being adjusted."""
        proc = frame.copy()
        height, width = proc.shape[:2]
        center_x, center_y = width // 2, height // 2

        cv2.line(proc, (center_x, 0), (center_x, height), (0, 255, 0), 2)
        cv2.line(proc, (0, center_y), (width, center_y), (0, 255, 0), 2)

        step = self.current_guided_step
        if step is not None:
            streamer = getattr(getattr(self.box, "visualizers", None), "streamer", None)
            rect_width = int(getattr(streamer, "electrode_width_px", 375) if streamer else 375)
            rect_height = int(getattr(streamer, "electrode_height_px", 375) if streamer else 375)
            half_width = max(10, rect_width // 2)
            half_height = max(10, rect_height // 2)

            top_left = (center_x - half_width, center_y - half_height)
            bottom_right = (center_x + half_width, center_y + half_height)
            cv2.rectangle(proc, top_left, bottom_right, self.target_rectangle_color, 4)

            label = f"target {step['row']},{step['column']}"
            text_pos = (max(10, top_left[0]), max(35, top_left[1] - 12))
            cv2.putText(
                proc,
                label,
                text_pos,
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                self.target_rectangle_color,
                3,
            )

        return proc

    def _start_position_thread(self) -> None:
        self._position_thread = threading.Thread(
            target=self._position_loop,
            daemon=True,
            name="StageCalibrationPositionReader",
        )
        self._position_thread.start()

    def _position_loop(self) -> None:
        while not self.exit_flag.is_set():
            if self.box is None:
                return
            for axis in ("X", "Y", "Z"):
                try:
                    value = self.box.xy_stage.get_position(axis)
                    if value is not None:
                        self.position[axis] = int(value)
                except Exception:
                    pass
            time.sleep(POSITION_POLL_SECONDS)

    def _queue_update(self, path: str, value, *, priority: Optional[Priority] = None) -> None:
        if self.box is None:
            return
        self.box.update_state(path, value, priority=priority)

    def _fresh_position(self) -> Dict[str, int]:
        """Read the current hardware position and update the displayed cache."""
        if self.box is None:
            return copy.deepcopy(self.position)

        fresh = copy.deepcopy(self.position)
        for axis in ("X", "Y", "Z"):
            try:
                value = self.box.xy_stage.get_position(axis)
                if value is not None:
                    fresh[axis] = int(value)
            except Exception:
                pass
        self.position = fresh
        return copy.deepcopy(fresh)

    def _apply_speed(self) -> None:
        _, velocity, acceleration = SPEEDS[self.speed_key]
        self._queue_update("xy_stage.motion_params.dMaxV", velocity)
        self._queue_update("xy_stage.motion_params.dMaxA", acceleration)

    def _handle_keys(self) -> None:
        self._update_travel_state()
        self._handle_speed_keys()
        self._handle_action_keys()
        self._handle_jog_keys()

    def _handle_speed_keys(self) -> None:
        for key in SPEEDS:
            if self.key_poller.just_pressed(ord(key), self._previous_keys):
                self.speed_key = key
                self._apply_speed()

    def _handle_action_keys(self) -> None:
        actions = {
            VK_RETURN: self.confirm_current_guided_step,
            ord("O"): self.record_origin,
            ord("R"): self.record_row_reference,
            ord("C"): self.record_column_reference,
            ord("S"): self.save_current_calibration,
            ord("M"): self.move_to_current_guided_estimate,
            ord("Q"): self.exit_flag.set,
            0x1B: self.exit_flag.set,
        }
        for vk_code, action in actions.items():
            if self.key_poller.just_pressed(vk_code, self._previous_keys):
                action()

    def _handle_jog_keys(self) -> None:
        x_direction = 0
        y_direction = 0
        z_direction = 0

        if self.key_poller.pressed(VK_LEFT):
            x_direction = -1
        elif self.key_poller.pressed(VK_RIGHT):
            x_direction = 1

        if self.key_poller.pressed(VK_UP):
            y_direction = 1
        elif self.key_poller.pressed(VK_DOWN):
            y_direction = -1

        if self.key_poller.pressed(VK_MINUS) or self.key_poller.pressed(VK_NUMPAD_MINUS) or self.key_poller.pressed(VK_PAGE_DOWN):
            z_direction = -1
        elif self.key_poller.pressed(VK_PLUS) or self.key_poller.pressed(VK_NUMPAD_PLUS) or self.key_poller.pressed(VK_PAGE_UP):
            z_direction = 1

        now = time.monotonic()
        for axis, direction in (("X", x_direction), ("Y", y_direction), ("Z", z_direction)):
            previous_direction = self._last_jog_by_axis[axis]
            should_refresh = (
                direction != 0
                and now - self._last_keepalive_by_axis[axis] >= JOG_KEEPALIVE_INTERVAL_SECONDS
            )
            if direction != previous_direction or should_refresh:
                self._queue_update(
                    f"xy_stage.continuous_movement.{axis}",
                    direction,
                    priority=Priority.HIGH,
                )
                self._last_jog_by_axis[axis] = direction
                self._last_keepalive_by_axis[axis] = now

    def _stop_all_jogs(self) -> None:
        for axis in ("X", "Y", "Z"):
            try:
                self._queue_update(f"xy_stage.continuous_movement.{axis}", 0, priority=Priority.HIGH)
            except Exception:
                pass

            try:
                if self.box is not None:
                    self.box.xy_stage.stop_continuous_movement(axis)
            except Exception:
                pass

    def move_to_origin(self) -> None:
        self._queue_update("xy_stage.position", self.current_origin, priority=Priority.HIGH)

    def move_to_current_guided_estimate(self) -> None:
        step = self.current_guided_step
        if step is None:
            self.status_message = "Guided calibration complete; no current target."
            self._set_overlay_target(None)
            return

        self._set_overlay_target((step["row"], step["column"]))
        if step["key"] == "origin":
            target = self.current_origin
        else:
            target = electrode_to_stage_from_config(step["row"], step["column"], self.travel_config_data)
        self.status_message = f"Moving to estimated {step['label']}: {target}"
        console.print(f"[cyan]Moving to {step['label']}:[/] {target}")
        self._apply_travel_speed()
        self.traveling_to_guided_target = True
        self.travel_started_at = time.monotonic()
        self._queue_update("xy_stage.position", target, priority=Priority.HIGH)

    def _set_overlay_target(self, target) -> None:
        if self.box is None:
            return
        streamer = getattr(getattr(self.box, "visualizers", None), "streamer", None)
        if streamer is not None:
            streamer.electrode_overlay_center = target

    def _apply_travel_speed(self) -> None:
        self._queue_update("xy_stage.motion_params.dMaxV", TRAVEL_VELOCITY, priority=Priority.HIGH)
        self._queue_update("xy_stage.motion_params.dMaxA", TRAVEL_ACCELERATION, priority=Priority.HIGH)

    def _update_travel_state(self) -> None:
        if not self.traveling_to_guided_target or self.box is None:
            return
        if time.monotonic() - self.travel_started_at < 0.5:
            return

        try:
            axes_done = all(self.box.xy_stage.is_motion_complete(axis) for axis in ("X", "Y", "Z"))
        except Exception:
            axes_done = False

        if axes_done:
            self.traveling_to_guided_target = False
            self._apply_speed()
            step = self.current_guided_step
            if step is not None:
                self.status_message = f"Ready to adjust {step['label']}; press Enter when centered."

    def confirm_current_guided_step(self) -> None:
        step = self.current_guided_step
        if step is None:
            self.save_current_calibration()
            self.status_message = "Calibration already complete; config saved again."
            return

        step["record"]()
        self.status_message = f"Recorded {step['label']} at {copy.deepcopy(self.position)}"
        self.guided_index += 1

        if self.current_guided_step is None:
            self.workflow_complete = True
            self.save_current_calibration()
            self.status_message = f"Guided calibration complete and saved to {self.config_path}"
            return

        self.move_to_current_guided_estimate()

    def record_origin(self) -> None:
        point = self._fresh_position()
        self.reference_points["origin"] = point
        self.config_data["calibration"]["chip_origin"] = point
        self.travel_config_data["calibration"]["chip_origin"] = copy.deepcopy(point)
        self.config_data["calibration"]["electrode_mapping"]["offset_x"] = 0
        self.config_data["calibration"]["electrode_mapping"]["offset_y"] = 0

    def record_row_reference(self) -> None:
        self.reference_points["row"] = self._fresh_position()
        self._recalculate_mapping_if_possible()

    def record_column_reference(self) -> None:
        self.reference_points["column"] = self._fresh_position()
        self._recalculate_mapping_if_possible()

    def save_current_calibration(self) -> None:
        self._recalculate_mapping_if_possible()
        save_config(self.config_path, self.config_data)

    def _recalculate_mapping_if_possible(self) -> None:
        origin = self.reference_points.get("origin") or self.current_origin
        mapping = self.config_data["calibration"]["electrode_mapping"]

        row_reference = self.reference_points.get("row")
        if row_reference is not None and self.rows > 1:
            intervals = self.rows - 1
            mapping["inter_row"] = [
                (row_reference[axis] - origin[axis]) / intervals
                for axis in ("X", "Y", "Z")
            ]

        column_reference = self.reference_points.get("column")
        if column_reference is not None and self.columns > 1:
            intervals = self.columns - 1
            mapping["inter_column"] = [
                (column_reference[axis] - origin[axis]) / intervals
                for axis in ("X", "Y", "Z")
            ]

    def _render(self) -> Group:
        return Group(
            self._controls_panel(),
            self._status_panel(),
            self._calibration_panel(),
        )

    def _controls_panel(self) -> Panel:
        text = (
            "[bold]Movement[/]\n"
            "Arrows: X/Y jog    PageUp/PageDown or +/-: Z jog    1/2/3: speed\n\n"
            "[bold]Calibration[/]\n"
            "Enter: accept current target and move to next guided point\n"
            "Sequence: (0,0) -> (127,0) -> (0,127)\n"
            "O/R/C: manually record origin/row/column if needed\n"
            "M: re-move to current guided estimate    S: save config    Q/Esc: quit"
        )
        return Panel(text, title="Stage Calibration Controls", border_style="cyan")

    def _status_panel(self) -> Panel:
        table = Table.grid(expand=True)
        table.add_column()
        table.add_column()
        table.add_row("Config", str(self.config_path))
        table.add_row("Speed", f"{self.speed_name} ({SPEEDS[self.speed_key][1]:.0f} steps/s)")
        table.add_row(
            "Position",
            f"X={self.position['X']}  Y={self.position['Y']}  Z={self.position['Z']}",
        )
        table.add_row(
            "Configured origin",
            f"X={self.current_origin['X']}  Y={self.current_origin['Y']}  Z={self.current_origin['Z']}",
        )
        step = self.current_guided_step
        if step is None:
            guided_text = "complete"
        else:
            guided_text = f"{self.guided_index + 1}/{len(self.guided_steps)} {step['label']}"
        table.add_row("Guided target", guided_text)
        table.add_row("Optics", f"coaxial={DEFAULT_COAXIAL_INTENSITY}, exposure={DEFAULT_EXPOSURE_US} us")
        table.add_row("Mode", "fast travel" if self.traveling_to_guided_target else "manual adjustment")
        table.add_row("Status", self.status_message)
        return Panel(table, title="Live Stage State", border_style="green")

    def _calibration_panel(self) -> Panel:
        calibration = self.config_data["calibration"]
        mapping = calibration["electrode_mapping"]
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Value")
        table.add_column("X")
        table.add_column("Y")
        table.add_column("Z")

        origin = calibration["chip_origin"]
        table.add_row(
            "chip_origin",
            str(int(origin["X"])),
            str(int(origin["Y"])),
            str(int(origin["Z"])),
        )
        table.add_row(
            "inter_row",
            f"{float(mapping['inter_row'][0]):.4f}",
            f"{float(mapping['inter_row'][1]):.4f}",
            f"{float(mapping['inter_row'][2]):.4f}",
        )
        table.add_row(
            "inter_column",
            f"{float(mapping['inter_column'][0]):.4f}",
            f"{float(mapping['inter_column'][1]):.4f}",
            f"{float(mapping['inter_column'][2]):.4f}",
        )

        saved = ", ".join(sorted(self.reference_points)) or "none this session"
        return Panel(Group(table, f"Recorded references: {saved}"), title="Calibration Preview")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive BOXMini stage calibration.")
    parser.add_argument(
        "--config",
        help="Path to config.json. Defaults to DROPLOGIC_CONFIG, cwd/config.json, then repo config.json.",
    )
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Do not start the microscope/camera and matrix visualizer windows.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = resolve_config_path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    session = StageCalibrationSession(config_path, start_video=not args.no_video)
    session.run()


if __name__ == "__main__":
    main()
