"""Generate AdvancedDrop documentation GIFs from real simulator recordings.

Workflow:

1. Build a short AdvancedDrop plan on the Simulator.
2. Let PlanExecutor save the MatrixVisualizer snapshot stream as MP4.
3. Convert that MP4 into a fixed-size horizontal GIF for the docs.

The GIF frames are cropped and letterboxed for the web, but every visible frame
comes from the executor-synchronised MP4 recording path.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"
OUTPUT_DIR = ROOT / "docs" / "assets" / "advanced-drop"
BUILD_DIR = ROOT / "build" / "advanced-drop-videos"

RECORDING_FPS = 8.0
FRAME_DELAY_SECONDS = 1.0 / RECORDING_FPS
GIF_FRAME_DURATION_MS = 420
GIF_CARD_SIZE = (720, 405)
GIF_CARD_INSET = 28
GIF_CROP_PADDING_PX = 80
MIN_ACTIVITY_PIXELS = 10
MATRIX_CAPTURE_SIZE = (1400, 1000)
MATRIX_CAPTURE_CELL_PX = 8
MATRIX_CAPTURE_MARGIN_PX = 40


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from droplogic.hardware.simulator import Simulator


def _fresh_simulator():
    Simulator._instance = None
    return Simulator(config_file=str(CONFIG_FILE), log_level=logging.ERROR)


def _close_simulator(system):
    try:
        system.close()
    finally:
        Simulator._instance = None


def _prepare_visualizer(system):
    visualizer = system.advanced_drop.visualizer
    if visualizer is not None:
        matrix = None
        if hasattr(system, "get_simulated_matrix"):
            matrix = system.get_simulated_matrix()
        elif hasattr(system, "_simulated_matrix"):
            matrix = system._simulated_matrix

        if matrix is not None:
            rows, cols = matrix.shape
            margin = MATRIX_CAPTURE_MARGIN_PX
            visualizer.matrix_size = (
                rows * MATRIX_CAPTURE_CELL_PX + margin * 2,
                cols * MATRIX_CAPTURE_CELL_PX + margin * 2,
            )
            visualizer.margins = (margin, margin, margin, margin)
        else:
            visualizer.matrix_size = MATRIX_CAPTURE_SIZE


def _build_reservoir_extraction_1to2(system):
    """Create a 6x6 reservoir and extract the central 2x2 droplet to the right."""
    _prepare_visualizer(system)
    ad = system.advanced_drop

    ad.droplets.create_droplet(
        1,
        origin=(20, 16),
        target=(20, 16),
        width=6,
        height=6,
    )
    ad.reservoir_extraction(
        reservoir_droplet_id=1,
        split_mode="1to2",
        steps=(0, 10),
        split_size={(2, 2), (2, 3), (3, 2), (3, 3)},
        halo_size=1,
        new_droplet_id=2,
    )


def _build_reservoir_extraction_1to3(system):
    """Create a larger reservoir and extract a centered 2x2 droplet with 1to3."""
    _prepare_visualizer(system)
    ad = system.advanced_drop

    ad.droplets.create_droplet(
        1,
        origin=(24, 16),
        target=(24, 16),
        width=12,
        height=12,
    )
    ad.reservoir_extraction(
        reservoir_droplet_id=1,
        split_mode="1to3",
        steps=(0, 14),
        split_size=(2, 2),
        separation_steps=4,
        new_droplet_id=2,
    )


def _build_reservoir_extraction_linear(system):
    """Create a reservoir and sweep it rightward to leave three full droplet lines."""
    _prepare_visualizer(system)
    ad = system.advanced_drop

    ad.droplets.create_droplet(
        1,
        origin=(18, 18),
        target=(18, 18),
        width=10,
        height=14,
    )
    ad.reservoir_extraction(
        reservoir_droplet_id=1,
        split_mode="linear",
        linear_drops_number=21,
        linear_offset=0,
        linear_space_per_col=3,
        linear_space_per_row=1,
        linear_drop_shape=(1, 1),
        linear_direction=(0, 1),
        new_droplet_id=2,
    )


DEMOS = {
    "reservoir-extraction-1to2": _build_reservoir_extraction_1to2,
    "reservoir-extraction-1to3": _build_reservoir_extraction_1to3,
    "reservoir-extraction-linear": _build_reservoir_extraction_linear,
}


def _wait_for_executor(executor, timeout_seconds=60.0):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = executor.status()
        if not status.get("is_executing"):
            return status
        time.sleep(0.05)

    status = executor.status()
    raise TimeoutError(
        "Timed out waiting for PlanExecutor "
        f"at frame {status.get('current_frame')}/{status.get('total_frames')}"
    )


def _record_plan_to_mp4(system, mp4_path):
    ad = system.advanced_drop
    mp4_path.parent.mkdir(parents=True, exist_ok=True)
    if mp4_path.exists():
        mp4_path.unlink()

    ad.executor.start(
        plan=ad.plan,
        frame_delay=FRAME_DELAY_SECONDS,
        verify_positions=False,
        enable_visualizers=False,
        record_matrix=True,
        matrix_filename=str(mp4_path),
    )

    status = _wait_for_executor(ad.executor)
    ad.executor.stop()

    if status.get("frames_executed", 0) < status.get("total_frames", 0):
        raise RuntimeError(f"PlanExecutor stopped before completing the plan: {status}")
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        raise RuntimeError(f"PlanExecutor did not create a usable MP4 at {mp4_path}")


def _active_crop_box(frames):
    """Find a shared crop around colored matrix activity in recorded frames."""
    points = []
    for frame in frames:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        mask = (saturation > 30) & (value > 45)
        coords = cv2.findNonZero(mask.astype("uint8"))
        if coords is not None:
            points.append(coords.reshape(-1, 2))

    if not points:
        return None

    all_points = cv2.vconcat(points)
    x, y, width, height = cv2.boundingRect(all_points)
    frame_h, frame_w = frames[0].shape[:2]
    x0 = max(0, x - GIF_CROP_PADDING_PX)
    y0 = max(0, y - GIF_CROP_PADDING_PX)
    x1 = min(frame_w, x + width + GIF_CROP_PADDING_PX)
    y1 = min(frame_h, y + height + GIF_CROP_PADDING_PX)
    return x0, y0, x1, y1


def _frame_activity_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    return (saturation > 30) & (value > 45)


def _trim_inactive_edges(frames):
    active_indices = [
        index
        for index, frame in enumerate(frames)
        if int(np.count_nonzero(_frame_activity_mask(frame))) >= MIN_ACTIVITY_PIXELS
    ]
    if not active_indices:
        return frames

    return frames[active_indices[0]:active_indices[-1] + 1]


def _fit_frame_to_card(frame):
    card_w, card_h = GIF_CARD_SIZE
    max_w = card_w - GIF_CARD_INSET * 2
    max_h = card_h - GIF_CARD_INSET * 2
    frame_h, frame_w = frame.shape[:2]

    scale = min(max_w / frame_w, max_h / frame_h)
    target_w = max(1, int(round(frame_w * scale)))
    target_h = max(1, int(round(frame_h * scale)))
    interpolation = cv2.INTER_NEAREST if scale >= 1.0 else cv2.INTER_AREA
    resized = cv2.resize(frame, (target_w, target_h), interpolation=interpolation)

    card = np.zeros((card_h, card_w, 3), dtype=np.uint8)
    x = (card_w - target_w) // 2
    y = (card_h - target_h) // 2
    card[y:y + target_h, x:x + target_w] = resized
    return card


def _convert_mp4_to_gif(mp4_path, gif_path):
    capture = cv2.VideoCapture(str(mp4_path))
    raw_frames = []

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            raw_frames.append(frame)
    finally:
        capture.release()

    if not raw_frames:
        raise RuntimeError(f"No frames could be read from {mp4_path}")

    raw_frames = _trim_inactive_edges(raw_frames)
    crop_box = _active_crop_box(raw_frames)
    gif_frames = []
    for frame in raw_frames:
        if crop_box is not None:
            x0, y0, x1, y1 = crop_box
            frame = frame[y0:y1, x0:x1]

        card = _fit_frame_to_card(frame)
        rgb = cv2.cvtColor(card, cv2.COLOR_BGR2RGB)
        gif_frames.append(Image.fromarray(rgb))

    gif_path.parent.mkdir(parents=True, exist_ok=True)
    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=GIF_FRAME_DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )


def generate_demo(slug, builder):
    system = _fresh_simulator()
    mp4_path = BUILD_DIR / f"{slug}.mp4"
    gif_path = OUTPUT_DIR / f"{slug}.gif"

    try:
        builder(system)
        _record_plan_to_mp4(system, mp4_path)
        _convert_mp4_to_gif(mp4_path, gif_path)
        print(f"Wrote {gif_path.relative_to(ROOT)} from {mp4_path.relative_to(ROOT)}")
    finally:
        _close_simulator(system)


def main():
    for slug, builder in DEMOS.items():
        generate_demo(slug, builder)


if __name__ == "__main__":
    main()
