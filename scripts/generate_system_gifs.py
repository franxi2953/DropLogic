"""Generate system documentation GIFs from real simulator executor recordings."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "assets" / "systems"
BUILD_DIR = ROOT / "build" / "system-videos"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_advanced_drop_gifs import (  # noqa: E402
    _close_simulator,
    _convert_mp4_to_gif,
    _fresh_simulator,
    _prepare_visualizer,
    _record_plan_to_mp4,
    _seed_droplets_in_single_frame,
    _set_visualizer_paths_from_plan,
)


def _build_simulator_executor_demo(system):
    """Build a compact, deterministic multi-droplet simulator routing demo."""
    _prepare_visualizer(system)
    ad = system.advanced_drop

    droplet_specs = []
    droplet_id = 1
    for row in range(18, 58, 8):
        for col in range(18, 50, 8):
            droplet_specs.append(
                {
                    "id": droplet_id,
                    "origin": (row, col),
                    "target": (row + 26, col + 42),
                    "width": 1,
                    "height": 1,
                    "priority": droplet_id,
                    "vital_space": 1,
                }
            )
            droplet_id += 1

    _seed_droplets_in_single_frame(ad, droplet_specs)
    ad.move(
        mode="sipp",
        planning_timeout=45,
        max_path_frames=110,
        reservation_horizon=120,
    )

    for droplet in ad.droplets:
        row, col = droplet.origin_corner
        ad.droplets.update_droplet_target(
            droplet.id,
            (row - 20, col - 30),
        )

    ad.move(
        mode="sipp",
        planning_timeout=45,
        max_path_frames=110,
        reservation_horizon=120,
    )
    _set_visualizer_paths_from_plan(system)


DEMOS = {
    "simulator-executor-demo": _build_simulator_executor_demo,
}


DEMO_GIF_OPTIONS = {
    "simulator-executor-demo": {
        "duration_ms": 180,
        "frame_stride": 2,
    },
}


def generate_demo(slug, builder):
    system = _fresh_simulator()
    mp4_path = BUILD_DIR / f"{slug}.mp4"
    gif_path = OUTPUT_DIR / f"{slug}.gif"

    try:
        builder(system)
        _record_plan_to_mp4(system, mp4_path)
        _convert_mp4_to_gif(mp4_path, gif_path, **DEMO_GIF_OPTIONS.get(slug, {}))
        print(f"Wrote {gif_path.relative_to(ROOT)} from {mp4_path.relative_to(ROOT)}")
    finally:
        _close_simulator(system)


def main():
    logging.basicConfig(level=logging.INFO)
    slugs = sys.argv[1:] or list(DEMOS.keys())
    unknown_slugs = sorted(set(slugs) - set(DEMOS))
    if unknown_slugs:
        raise ValueError(f"Unknown demo slug(s): {', '.join(unknown_slugs)}")

    for slug in slugs:
        generate_demo(slug, DEMOS[slug])


if __name__ == "__main__":
    main()
