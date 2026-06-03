"""
Shared imaging capture utilities for drop_vision workflows.

This module centralizes microscope/camera capture behavior used by condensate
analysis and protocol imaging, including channel configuration, warmup/discard,
and retry/valid-frame logic.
"""

import time
from typing import Optional

import numpy as np


def _get_streamer(system):
    if hasattr(system, "visualizers") and hasattr(system.visualizers, "streamer"):
        return system.visualizers.streamer
    return None


def _ensure_streamer_started(streamer, frame_wait: float = 0.2) -> None:
    if streamer is None:
        return
    if hasattr(streamer, "capture_thread"):
        th = streamer.capture_thread
        if th is None or not th.is_alive():
            streamer.start()
            time.sleep(frame_wait)


def _capture_direct_frame(system) -> Optional[np.ndarray]:
    """Fallback frame capture directly from microscope/camera modules."""
    for dev_name in ("microscope", "camera"):
        dev = getattr(system, dev_name, None)
        if dev is None:
            continue
        try:
            if hasattr(dev, "capture_image"):
                frame = dev.capture_image()
            elif hasattr(dev, "capture_frame"):
                frame = dev.capture_frame()
            else:
                frame = None
            if frame is not None and getattr(frame, "size", 0) > 0:
                return frame
        except Exception:
            continue
    return None


def _grab_valid_frame_from_streamer(streamer, mode: str = "brightfield") -> Optional[np.ndarray]:
    if streamer is None or not hasattr(streamer, "get_raw_frame"):
        return None

    frame = streamer.get_raw_frame()
    if frame is None:
        return None

    total_px = frame.shape[0] * frame.shape[1]
    if frame.ndim == 3:
        non_black = np.sum(np.any(frame != 0, axis=-1))
    else:
        non_black = np.sum(frame != 0)

    if mode == "fluorescence":
        return frame if (non_black / total_px) * 100 > 0.001 else None
    return frame if non_black >= 100 else None


def _wait_for_new_frames(
    streamer,
    previous_frame,
    n: int = 1,
    timeout_per_frame: float = 6.0,
    poll: float = 0.05,
    mode: str = "brightfield",
):
    if streamer is None or not hasattr(streamer, "get_raw_frame"):
        return None

    last = previous_frame
    for _ in range(n):
        t0 = time.time()
        while time.time() - t0 < timeout_per_frame:
            frame = streamer.get_raw_frame()
            if frame is not None and (last is None or not np.array_equal(frame, last)):
                total_px = frame.shape[0] * frame.shape[1]
                if frame.ndim == 3:
                    non_black = np.sum(np.any(frame != 0, axis=-1))
                else:
                    non_black = np.sum(frame != 0)
                pct = (non_black / total_px) * 100

                if mode == "fluorescence":
                    if pct > 0.001:
                        last = frame
                        break
                else:
                    if non_black >= 100:
                        last = frame
                        break
            time.sleep(poll)
        else:
            return None
    return last


def configure_capture_channel(
    system,
    channel: str,
    exposure_time: int,
    gain: int = 12,
    coaxial_intensity: int = 30,
    ring_intensity: int = 0,
    frame_wait: float = 0.2,
    stabilization_wait: float = 0.2,
) -> None:
    """Apply microscope and light settings for one imaging channel."""
    if not (hasattr(system, "microscope") and system.microscope is not None):
        return

    system.update_state("microscope_settings.current_channel", channel)
    time.sleep(frame_wait)
    system.update_state("microscope_settings.auto_exposure", False)
    time.sleep(frame_wait)
    system.update_state("microscope_settings.exposure_time", exposure_time)
    time.sleep(frame_wait)
    system.update_state("microscope_settings.gain", gain)
    time.sleep(frame_wait)
    system.update_state("light_settings.coaxial_intensity", coaxial_intensity)
    system.update_state("light_settings.ring_intensity", ring_intensity)
    time.sleep(stabilization_wait)


def capture_channel_frame(
    system,
    channel: str,
    exposure_time: int,
    gain: int = 12,
    coaxial_intensity: int = 30,
    ring_intensity: int = 0,
    frame_wait: float = 0.2,
    timeout_per_frame: float = 10.0,
    mode: str = "brightfield",
) -> Optional[np.ndarray]:
    """
    Capture one valid frame using a channel profile.

    mode="brightfield" follows step6 brightfield behavior.
    mode="fluorescence" follows step6 FAM behavior.
    """
    if mode not in ("brightfield", "fluorescence"):
        raise ValueError(f"Unsupported capture mode: {mode}")

    stabilization_wait = 1.0 if mode == "fluorescence" else frame_wait
    configure_capture_channel(
        system,
        channel=channel,
        exposure_time=exposure_time,
        gain=gain,
        coaxial_intensity=coaxial_intensity,
        ring_intensity=ring_intensity,
        frame_wait=frame_wait,
        stabilization_wait=stabilization_wait,
    )

    streamer = _get_streamer(system)
    _ensure_streamer_started(streamer, frame_wait=frame_wait)

    if streamer is not None and hasattr(streamer, "get_raw_frame"):
        if mode == "brightfield":
            warmup = streamer.get_raw_frame()
            _wait_for_new_frames(
                streamer,
                warmup,
                n=5,
                timeout_per_frame=timeout_per_frame,
                mode="brightfield",
            )
            for _ in range(3):
                frame = _grab_valid_frame_from_streamer(streamer, mode="brightfield")
                if frame is not None:
                    return frame
                time.sleep(0.2)
        else:
            last_warmup = None
            for _ in range(45):
                time.sleep(0.1)
                warmup_frame = streamer.get_raw_frame()
                if warmup_frame is not None:
                    last_warmup = warmup_frame

            for _ in range(5):
                time.sleep(0.5)
                frame = streamer.get_raw_frame()
                if frame is None:
                    continue
                if last_warmup is None or not np.array_equal(frame, last_warmup):
                    total_px = frame.shape[0] * frame.shape[1]
                    if frame.ndim == 3:
                        non_black = np.sum(np.any(frame != 0, axis=-1))
                    else:
                        non_black = np.sum(frame != 0)
                    if (non_black / total_px) * 100 > 0.001:
                        return frame

            frame = streamer.get_raw_frame()
            if frame is not None and getattr(frame, "size", 0) > 0:
                return frame

    return _capture_direct_frame(system)
