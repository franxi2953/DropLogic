import logging
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "assets" / "advanced-drop"
CONFIG_FILE = ROOT / "config.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from droplogic.hardware.simulator import Simulator


def _font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/Library/Fonts/Georgia Bold.ttf" if bold else "/Library/Fonts/Georgia.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


TITLE_FONT = _font(18, bold=True)
SMALL_FONT = _font(12)
GIF_FRAME_DURATION_MS = 700


def _fresh_simulator():
    Simulator._instance = None
    return Simulator(config_file=str(CONFIG_FILE), log_level=logging.ERROR)


def _close_simulator(system):
    try:
        system.close()
    finally:
        Simulator._instance = None


def _active_bounds(frames, padding=3):
    active_positions = []
    for frame in frames:
        coords = np.argwhere(np.asarray(frame) > 0)
        if coords.size:
            active_positions.append(coords)

    if not active_positions:
        return 0, 0, 16, 16

    coords = np.vstack(active_positions)
    min_r, min_c = coords.min(axis=0)
    max_r, max_c = coords.max(axis=0)
    rows, cols = np.asarray(frames[0]).shape
    return (
        max(0, int(min_r) - padding),
        max(0, int(min_c) - padding),
        min(rows - 1, int(max_r) + padding),
        min(cols - 1, int(max_c) + padding),
    )


def _sample_indices(frame_count, max_frames=36):
    if frame_count <= max_frames:
        return list(range(frame_count))

    indices = np.linspace(0, frame_count - 1, max_frames).round().astype(int).tolist()
    deduped = []
    for idx in indices:
        if idx not in deduped:
            deduped.append(idx)
    if deduped[-1] != frame_count - 1:
        deduped.append(frame_count - 1)
    return deduped


def _render_frame(frame, title, frame_number, total_frames, bounds):
    frame = np.asarray(frame)
    min_r, min_c, max_r, max_c = bounds
    cropped = frame[min_r:max_r + 1, min_c:max_c + 1]
    crop_rows, crop_cols = cropped.shape

    cell = int(min(18, max(7, 360 / max(crop_rows, crop_cols))))
    margin = 18
    title_h = 34
    grid_w = crop_cols * cell
    grid_h = crop_rows * cell
    width = max(grid_w + margin * 2, 420)
    height = crop_rows * cell + margin * 2 + title_h

    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, width - 1, height - 1), outline="#111111", width=2)
    draw.text((margin, 10), title.upper(), fill="#111111", font=TITLE_FONT)
    step_text = f"{frame_number + 1}/{total_frames}"
    text_box = draw.textbbox((0, 0), step_text, font=SMALL_FONT)
    draw.text((width - margin - (text_box[2] - text_box[0]), 14), step_text, fill="#676767", font=SMALL_FONT)

    grid_x = (width - grid_w) // 2
    grid_y = margin + title_h
    draw.rectangle((grid_x, grid_y, grid_x + grid_w, grid_y + grid_h), fill="#f7f7f7", outline="#111111", width=1)

    grid_color = "#dedede"
    for r in range(crop_rows + 1):
        y = grid_y + r * cell
        draw.line((grid_x, y, grid_x + grid_w, y), fill=grid_color, width=1)
    for c in range(crop_cols + 1):
        x = grid_x + c * cell
        draw.line((x, grid_y, x, grid_y + grid_h), fill=grid_color, width=1)

    for r in range(crop_rows):
        for c in range(crop_cols):
            value = cropped[r, c]
            if value <= 0:
                continue
            fill = "#111111" if value == 1 else "#7a7a7a"
            x0 = grid_x + c * cell + 2
            y0 = grid_y + r * cell + 2
            x1 = grid_x + (c + 1) * cell - 2
            y1 = grid_y + (r + 1) * cell - 2
            draw.rectangle((x0, y0, x1, y1), fill=fill)

    return image


def _write_gif(path, plan, title, max_frames=14):
    first_visible = 0
    for idx, frame in enumerate(plan.frames):
        if np.any(np.asarray(frame) > 0):
            first_visible = idx
            break

    frames = plan.frames[first_visible:]
    indices = _sample_indices(len(frames), max_frames=max_frames)
    bounds = _active_bounds(frames)
    images = [
        _render_frame(frames[idx], title=title, frame_number=display_idx, total_frames=len(indices), bounds=bounds)
        for display_idx, idx in enumerate(indices)
    ]

    # Add a short final hold without changing the source plan.
    images.extend([images[-1].copy(), images[-1].copy()])
    durations = [GIF_FRAME_DURATION_MS] * len(images)
    durations[-2:] = [700, 900]

    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"Wrote {path.relative_to(ROOT)} ({len(frames)} source frames, {len(images)} gif frames)")


def demo_droplet_management():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (8, 8), (8, 8), width=2, height=2)
        ad.droplets.create_droplet(2, (8, 14), (8, 14), shape={(0, 0), (0, 1), (1, 0)})
        ad.push_frame(event_type="manual_hold", event_data={"reason": "demo"})
        return ad.plan
    finally:
        _close_simulator(system)


def demo_move():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.add_droplets([
            {"id": 1, "origin": (8, 8), "target": (25, 25), "width": 2, "height": 2, "priority": 0},
            {"id": 2, "origin": (8, 28), "target": (25, 10), "width": 2, "height": 2, "priority": 1},
        ])
        ad.move(
            mode="sipp",
            planning_timeout=30,
            max_iterations=20000,
            max_path_frames=80,
            reservation_horizon=100,
        )
        return ad.plan
    finally:
        _close_simulator(system)


def demo_reservoir_extraction_1to2():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (20, 16), (20, 16), width=6, height=3)
        ad.reservoir_extraction(
            reservoir_droplet_id=1,
            split_mode="1to2",
            steps=(0, 9),
            split_size={(1, 4), (1, 5)},
            halo_size=1,
            new_droplet_id=2,
        )
        return ad.plan
    finally:
        _close_simulator(system)


def demo_reservoir_extraction_1to3():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (20, 16), (20, 16), width=7, height=3)
        ad.reservoir_extraction(
            reservoir_droplet_id=1,
            split_mode="1to3",
            steps=(0, 8),
            split_size=(1, 2),
            separation_steps=3,
            new_droplet_id=2,
        )
        return ad.plan
    finally:
        _close_simulator(system)


def demo_reservoir_extraction_linear():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (20, 10), (20, 10), width=8, height=3)
        ad.reservoir_extraction(
            reservoir_droplet_id=1,
            split_mode="linear",
            linear_drops_number=4,
            linear_offset=2,
            linear_space_per_col=4,
            linear_space_per_row=0,
            linear_drop_shape=(1, 1),
            linear_direction=(0, 1),
            new_droplet_id=2,
        )
        return ad.plan
    finally:
        _close_simulator(system)


def demo_isometric_split():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (22, 22), (22, 22), width=4, height=4)
        ad.isometric_split(
            droplet_id=1,
            steps=[(0, 6), (5, 0)],
            simultaneous=True,
            new_droplet_id=2,
        )
        return ad.plan
    finally:
        _close_simulator(system)


def demo_merge():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (20, 14), (20, 14), width=2, height=2)
        ad.droplets.create_droplet(2, (20, 32), (20, 32), width=2, height=2)
        ad.merge(
            droplet_ids=[1, 2],
            target=(20, 23),
            forced_width=4,
            forced_height=2,
            hold_final_position=True,
        )
        return ad.plan
    finally:
        _close_simulator(system)


def demo_mix_2d_loop():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (22, 22), (22, 22), width=2, height=2)
        ad.mix(droplet_id=1, mode="2d_loop", mixing_area_size=8, cycles=2)
        return ad.plan
    finally:
        _close_simulator(system)


def demo_mix_split_recombine():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (22, 22), (22, 22), width=4, height=4)
        ad.mix(droplet_id=1, mode="split_recombine", cycles=1)
        return ad.plan
    finally:
        _close_simulator(system)


def demo_correction():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (10, 10), (22, 22), width=2, height=2)
        ad.move(mode="sipp", planning_timeout=30, max_iterations=20000, max_path_frames=60)
        ad.correct_droplet_position(1, (20, 26))
        return ad.plan
    finally:
        _close_simulator(system)


def demo_plan_extension():
    system = _fresh_simulator()
    try:
        ad = system.advanced_drop
        ad.droplets.create_droplet(1, (8, 8), (20, 20), width=2, height=2)
        ad.move(mode="sipp", planning_timeout=30, max_iterations=20000, max_path_frames=60)
        ad.droplets.update_droplet_target(1, (12, 30))
        ad.move(mode="sipp", planning_timeout=30, max_iterations=20000, max_path_frames=60)
        return ad.plan
    finally:
        _close_simulator(system)


DEMOS = {
    "droplet-management.gif": ("droplet management", demo_droplet_management),
    "move.gif": ("move", demo_move),
    "reservoir-extraction-1to2.gif": ("reservoir 1to2", demo_reservoir_extraction_1to2),
    "reservoir-extraction-1to3.gif": ("reservoir 1to3", demo_reservoir_extraction_1to3),
    "reservoir-extraction-linear.gif": ("linear extract", demo_reservoir_extraction_linear),
    "isometric-split.gif": ("isometric split", demo_isometric_split),
    "merge.gif": ("merge", demo_merge),
    "mix-2d-loop.gif": ("mix 2d loop", demo_mix_2d_loop),
    "mix-split-recombine.gif": ("split recombine", demo_mix_split_recombine),
    "correction.gif": ("correction", demo_correction),
    "plan-extension.gif": ("plan extension", demo_plan_extension),
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (title, builder) in DEMOS.items():
        plan = builder()
        _write_gif(OUTPUT_DIR / filename, plan, title)


if __name__ == "__main__":
    main()
