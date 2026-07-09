"""RoboEyes-inspired personality layer for small monochrome front panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class FaceScene:
    """High-level eye pose that gets rendered by a hardware-specific panel."""

    gaze: str = "CENTER"
    open: float = 1.0
    left_open: Optional[float] = None
    right_open: Optional[float] = None
    mood: str = "default"
    curiosity: bool = False
    spark: bool = False
    sweat: bool = False
    heat: Optional[int] = None
    motion: Optional[str] = None
    error: bool = False
    symbol: Optional[str] = None
    symbol_phase: int = 0
    dwell: float = 1.0


class DroptiBotFacePersonality:
    """Reusable face behavior model independent from panel transport."""

    EXPRESSION_ALIASES = {
        "awake": "idle",
        "blanked": "blank",
        "confused": "thinking",
        "content": "done",
        "focused": "working",
        "happy": "done",
        "serious": "working",
        "sleeping": "sleep",
    }

    ACTION_EXPRESSIONS = {
        "xy_stage.": "moving",
        "electrode_matrix.": "working",
        "temperature.": "heating",
        "camera_settings.": "looking",
        "microscope_settings.": "looking",
        "light_settings.": "light",
    }

    GAZE_VECTORS = {
        "CENTER": (0, 0),
        "N": (0, -1),
        "NE": (2, -1),
        "E": (3, 0),
        "SE": (2, 1),
        "S": (0, 1),
        "SW": (-2, 1),
        "W": (-3, 0),
        "NW": (-2, -1),
    }

    _SCENES: Dict[str, Tuple[FaceScene, ...]] = {
        "idle": (
            FaceScene(gaze="CENTER", open=1.0, mood="default", dwell=3.2),
            FaceScene(gaze="CENTER", open=0.18, dwell=0.22),
            FaceScene(gaze="E", open=1.0, mood="default", curiosity=True, dwell=1.25),
            FaceScene(gaze="CENTER", open=1.0, mood="default", dwell=2.0),
            FaceScene(gaze="W", open=1.0, mood="default", curiosity=True, dwell=1.1),
            FaceScene(gaze="CENTER", open=0.86, mood="default", dwell=1.4),
        ),
        "sleep": (
            FaceScene(gaze="CENTER", left_open=0.06, right_open=0.08, mood="tired", symbol="sleep_zz", symbol_phase=0, dwell=2.6),
            FaceScene(gaze="CENTER", left_open=0.05, right_open=0.07, mood="tired", symbol="sleep_zz", symbol_phase=1, dwell=2.4),
            FaceScene(gaze="CENTER", left_open=0.06, right_open=0.06, mood="tired", symbol="sleep_zz", symbol_phase=2, dwell=2.1),
        ),
        "thinking": (
            FaceScene(gaze="NW", open=1.0, mood="tired", curiosity=True, dwell=1.3),
            FaceScene(gaze="NE", open=0.85, mood="tired", curiosity=True, dwell=1.0),
            FaceScene(gaze="N", open=1.0, mood="tired", spark=True, dwell=0.9),
            FaceScene(gaze="CENTER", open=0.24, mood="tired", dwell=0.2),
        ),
        "working": (
            FaceScene(gaze="W", open=0.92, mood="angry", dwell=0.9),
            FaceScene(gaze="CENTER", open=0.82, mood="angry", dwell=0.55),
            FaceScene(gaze="E", open=0.92, mood="angry", dwell=0.9),
            FaceScene(gaze="CENTER", open=0.7, mood="angry", dwell=0.45),
        ),
        "moving": (
            FaceScene(gaze="E", open=1.0, mood="default", motion="right", dwell=0.25),
            FaceScene(gaze="CENTER", open=1.0, mood="default", dwell=0.18),
            FaceScene(gaze="W", open=1.0, mood="default", motion="left", dwell=0.25),
            FaceScene(gaze="CENTER", open=1.0, mood="default", dwell=0.18),
        ),
        "looking": (
            FaceScene(gaze="CENTER", open=1.0, mood="default", dwell=1.3),
            FaceScene(gaze="E", open=1.0, mood="default", curiosity=True, dwell=1.1),
            FaceScene(gaze="CENTER", open=1.0, mood="default", dwell=0.9),
            FaceScene(gaze="W", open=1.0, mood="default", curiosity=True, dwell=1.1),
            FaceScene(gaze="CENTER", open=0.24, mood="default", dwell=0.18),
        ),
        "heating": (
            FaceScene(gaze="CENTER", open=0.84, mood="tired", heat=0, dwell=1.1),
            FaceScene(gaze="CENTER", open=0.84, mood="tired", heat=1, dwell=0.95),
        ),
        "light": (
            FaceScene(gaze="CENTER", open=1.0, mood="happy", spark=True, dwell=0.75),
            FaceScene(gaze="CENTER", open=1.0, mood="happy", spark=True, dwell=0.95),
        ),
        "done": (
            FaceScene(gaze="CENTER", open=1.0, mood="happy", dwell=1.8),
            FaceScene(gaze="CENTER", open=0.82, mood="happy", dwell=0.65),
            FaceScene(gaze="E", open=1.0, mood="happy", curiosity=True, dwell=1.2),
            FaceScene(gaze="CENTER", open=1.0, mood="happy", dwell=1.6),
        ),
        "sad": (
            FaceScene(gaze="S", open=0.62, mood="tired", dwell=1.8),
            FaceScene(gaze="SW", open=0.58, mood="tired", dwell=1.4),
            FaceScene(gaze="S", open=0.2, mood="tired", dwell=0.22),
            FaceScene(gaze="SE", open=0.58, mood="tired", dwell=1.4),
        ),
        "error": (
            FaceScene(gaze="CENTER", open=0.7, mood="angry", error=True, sweat=True, dwell=0.8),
            FaceScene(gaze="CENTER", open=1.0, mood="angry", error=True, sweat=True, dwell=0.8),
        ),
        "blank": (
            FaceScene(gaze="CENTER", open=0.0, dwell=1.0),
        ),
    }

    def supported_expressions(self) -> Iterable[str]:
        return self._SCENES.keys()

    def normalize_expression(self, expression: Optional[str], default: str = "idle") -> str:
        normalized = str(expression or default).strip().lower()
        normalized = self.EXPRESSION_ALIASES.get(normalized, normalized)
        if normalized not in self._SCENES:
            return default
        return normalized

    def expression_for_action(self, path: str) -> str:
        for prefix, expression in self.ACTION_EXPRESSIONS.items():
            if path.startswith(prefix):
                return expression
        return "thinking"

    def frames_for_expression(self, expression: Optional[str]) -> Tuple[Dict[str, object], ...]:
        normalized = self.normalize_expression(expression)
        scenes = self._SCENES[normalized]
        return tuple(self._scene_to_frame(scene) for scene in scenes)

    def frame_delay_multiplier(self, expression: Optional[str], frame_slot: int) -> float:
        normalized = self.normalize_expression(expression)
        scenes = self._SCENES[normalized]
        return float(scenes[frame_slot % len(scenes)].dwell)

    def _scene_to_frame(self, scene: FaceScene) -> Dict[str, object]:
        pupil_x, pupil_y = self.GAZE_VECTORS.get(scene.gaze, self.GAZE_VECTORS["CENTER"])
        frame: Dict[str, object] = {
            "open": scene.open,
            "pupil_x": pupil_x,
            "pupil_y": pupil_y,
            "mood": scene.mood,
        }
        if scene.left_open is not None:
            frame["left_open"] = scene.left_open
        if scene.right_open is not None:
            frame["right_open"] = scene.right_open
        if scene.curiosity:
            frame["curiosity"] = True
        if scene.spark:
            frame["spark"] = True
        if scene.sweat:
            frame["sweat"] = True
        if scene.heat is not None:
            frame["heat"] = scene.heat
        if scene.motion:
            frame["motion"] = scene.motion
        if scene.error:
            frame["error"] = True
        if scene.symbol:
            frame["symbol"] = scene.symbol
            frame["symbol_phase"] = scene.symbol_phase
        if scene.open <= 0 and scene.left_open is None and scene.right_open is None:
            frame["blank"] = True
        return frame
