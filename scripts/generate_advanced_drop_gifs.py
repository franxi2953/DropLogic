"""Generate AdvancedDrop documentation GIFs from real simulator recordings.

The workflow is intentionally executor-first:

1. Build a short AdvancedDrop plan on the Simulator.
2. Let PlanExecutor save the MatrixVisualizer snapshot stream as MP4.
3. Convert that MP4 into the GIF embedded by the documentation.

This avoids hand-rendered matrix mockups in the docs. The GIF frames come from
the same executor-synchronised recording path users can call in their own runs.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import cv2
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"
OUTPUT_DIR = ROOT / "docs" / "assets" / "advanced-drop"
BUILD_DIR = ROOT / "build" / "advanced-drop-videos"

RECORDING_FPS = 1.0
FRAME_DELAY_SECONDS = 1.0 / RECORDING_FPS
GIF_FRAME_DURATION_MS = int(1000 / RECORDING_FPS)
GIF_MIN_WIDTH = 560
GIF_MAX_WIDTH = 920
GIF_CROP_PADDING_PX = 90


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


def _build_reservoir_extraction_1to2(system):
    """Create a 6x6 reservoir and extract the central 2x2 droplet to the right."""
    ad = system.advanced_drop

    # Larger capture canvas keeps small droplets readable while preserving the
    # real MatrixVisualizer output.
    if ad.visualizer is not None:
        ad.visualizer.matrix_size = (1200, 1050)

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
    return ad.plan


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


def _resize_for_gif(frame):
    height, width = frame.shape[:2]
    if width < GIF_MIN_WIDTH:
        scale = GIF_MIN_WIDTH / width
        return cv2.resize(
            frame,
            (GIF_MIN_WIDTH, int(height * scale)),
            interpolation=cv2.INTER_NEAREST,
        )

    if width <= GIF_MAX_WIDTH:
        return frame

    scale = GIF_MAX_WIDTH / width
    resized = cv2.resize(
        frame,
        (GIF_MAX_WIDTH, int(height * scale)),
        interpolation=cv2.INTER_AREA,
    )
    return resized


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

    crop_box = _active_crop_box(raw_frames)
    frames = []
    for frame in raw_frames:
        if crop_box is not None:
            x0, y0, x1, y1 = crop_box
            frame = frame[y0:y1, x0:x1]

            frame = _resize_for_gif(frame)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))

    gif_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=GIF_FRAME_DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )


def generate_reservoir_extraction_1to2():
    system = _fresh_simulator()
    mp4_path = BUILD_DIR / "reservoir-extraction-1to2.mp4"
    gif_path = OUTPUT_DIR / "reservoir-extraction-1to2.gif"

    try:
        _build_reservoir_extraction_1to2(system)
        _record_plan_to_mp4(system, mp4_path)
        _convert_mp4_to_gif(mp4_path, gif_path)
        print(f"Wrote {gif_path.relative_to(ROOT)} from {mp4_path.relative_to(ROOT)}")
    finally:
        _close_simulator(system)


def main():
    generate_reservoir_extraction_1to2()


if __name__ == "__main__":
    main()
