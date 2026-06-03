"""
Hardware utilities for DropLogic.

This module provides utility functions for hardware control and coordinate conversions,
including electrode row/column to stage coordinates.
"""

import json
import numpy as np
import time
import os


DEFAULT_MICRONS_PER_PIXEL = 0.51413882
DEFAULT_PIXELS_PER_MICRON = 1.94500000


PIXEL_CALIBRATIONS = {
    "AM16k": {
        "microns_per_pixel": DEFAULT_MICRONS_PER_PIXEL,
        "pixels_per_micron": DEFAULT_PIXELS_PER_MICRON,
        "reference_pixels": 200.0 * DEFAULT_PIXELS_PER_MICRON,
        "reference_microns": 200.0,
        "description": (
            f"AM16k camera calibration ({DEFAULT_MICRONS_PER_PIXEL:.8f} um/px, "
            f"{DEFAULT_PIXELS_PER_MICRON:.8f} px/um)"
        ),
    }
}


def _get_pixel_calibration(camera_model="AM16k", config_path=None):
    """Return pixel-to-micron calibration metadata for a camera model."""
    config_calibrations = {}
    try:
        config = load_config(config_path)
        config_calibrations = (
            config.get("calibration", {})
            .get("pixel_calibration", {})
        )
    except Exception:
        config_calibrations = {}

    calibration_source = {name: data.copy() for name, data in PIXEL_CALIBRATIONS.items()}
    for name, data in config_calibrations.items():
        calibration_source[name] = {
            **calibration_source.get(name, {}),
            **data,
        }

    if camera_model not in calibration_source:
        raise ValueError(
            f"Unknown camera model: {camera_model}. Available: {list(calibration_source.keys())}"
        )

    calibration = calibration_source[camera_model].copy()
    if "microns_per_pixel" not in calibration:
        calibration["microns_per_pixel"] = (
            calibration["reference_microns"] / calibration["reference_pixels"]
        )
    if "pixels_per_micron" not in calibration:
        calibration["pixels_per_micron"] = 1.0 / calibration["microns_per_pixel"]
    return calibration


def load_config(config_path=None):
    """
    Load the configuration file.

    Args:
        config_path: Path to the config file. If None, uses the default relative path.

    Returns:
        The loaded configuration as a dictionary.
    """
    if config_path is None:
        # Use relative path from the DropLogic library root
        config_path = os.path.join(os.path.dirname(__file__), '../../../config.json')

    with open(config_path, 'r') as f:
        return json.load(f)

def save_config(config_data, config_path=None):
    """
    Save the configuration to file.

    Args:
        config_data: The configuration dictionary to save
        config_path: Path to the config file. If None, uses the default relative path.
    """
    if config_path is None:
        # Use relative path from the DropLogic library root
        config_path = os.path.join(os.path.dirname(__file__), '../../../config.json')

    with open(config_path, 'w') as f:
        json.dump(config_data, f, indent=4)

def electrode_to_stage(row_i, column_i, config_path=None):
    """
    Convert electrode row and column to XYZ stage coordinates.
    
    Args:
        row_i: The electrode row (0-indexed)
        column_i: The electrode column (0-indexed)
        config_path: Path to the config file. If None, uses the default path.
        
    Returns:
        Dictionary with X, Y, Z stage coordinates for use with box.update_state()
    """
    # Load config
    if config_path is None:
        config = load_config()
    else:
        with open(config_path, 'r') as f:
            config = json.load(f)

    row = int(row_i)
    column = int(column_i)
    
    
    # Get electrode mapping parameters from config
    mapping = config['calibration']['electrode_mapping']
    chip_origin = config['calibration']['chip_origin']
    
    # Extract parameters
    inter_row = mapping['inter_row']
    inter_column = mapping['inter_column']
       
    # Calculate position relative to chip origin (0,0 electrode)
    x_offset = row * inter_row[0] + column * inter_column[0] + mapping['offset_x']
    y_offset = row * inter_row[1] + column * inter_column[1] + mapping['offset_y']
    z_offset = row * inter_row[2] + column * inter_column[2] if len(inter_row) > 2 and len(inter_column) > 2 else 0
    
    # Add chip origin to get stage coordinates
    x_stage = int(chip_origin['X'] + x_offset)
    y_stage = int(chip_origin['Y'] + y_offset)
    z_stage = int(chip_origin['Z'] + z_offset)
    
    return {
        'X': int(x_stage),
        'Y': int(y_stage),
        'Z': int(z_stage)
    }

def stage_to_electrode(coords, *, config_path=None):
    """
    Map stage (x, y [, z]) to the *nearest* 0-indexed electrode (row, col).

    If the rounded indices fall outside the chip dimensions the function
    returns None.
    """
    # ── unpack input ───────────────────────────────────────────────
    try:
        x, y = coords[:2]          # ignore Z component if present
    except Exception:
        raise ValueError("coords must be (x, y) or (x, y, z) iterable")

    # ── load calibration ───────────────────────────────────────────
    cfg     = load_config() if config_path is None else load_config(config_path)
    mapping = cfg["calibration"]["electrode_mapping"]
    origin  = cfg["calibration"]["chip_origin"]

    n_rows  = cfg["electrode_matrix"]["rows"]
    n_cols  = cfg["electrode_matrix"]["columns"]

    irx, iry = mapping["inter_row"][:2]       # ΔX, ΔY per +1 row (ignore Z if present)
    icx, icy = mapping["inter_column"][:2]    # ΔX, ΔY per +1 column (ignore Z if present)
    off_x    = mapping["offset_x"]
    off_y    = mapping["offset_y"]
    X0, Y0   = origin["X"], origin["Y"]

    # ── translate to chip coordinate system ───────────────────────
    dX = x - (X0 + off_x)
    dY = y - (Y0 + off_y)

    # matrix inverse (2×2)
    det = irx * icy - icx * iry
    if abs(det) < 1e-12:            # degenerate mapping
        return None

    row_f = ( icy * dX - icx * dY) / det
    col_f = (-iry * dX + irx * dY) / det

    # ── round to nearest integer electrode ────────────────────────
    row_i = int(round(row_f))
    col_i = int(round(col_f))

    # print(row_i, col_i)

    # ── bounds check ───────────────────────────────────────────────
    if 0 <= row_i < n_rows and 0 <= col_i < n_cols:  # Changed <= to < for proper bounds
        return row_i, col_i # 0-indexed
    else:
        return None

def stage_to_electrode_float(coords, *, config_path=None):
    """
    Map stage (x, y [, z]) to floating-point electrode coordinates (row, col).

    Returns fractional electrode positions without rounding, useful for overlay positioning.
    """
    # ── unpack input ───────────────────────────────────────────────
    try:
        x, y = coords[:2]          # ignore Z component if present
    except Exception:
        # Return None if coords are invalid
        return None

    # ── load calibration ───────────────────────────────────────────
    try:
        cfg     = load_config() if config_path is None else load_config(config_path)
        mapping = cfg["calibration"]["electrode_mapping"]
        origin  = cfg["calibration"]["chip_origin"]

        irx, iry = mapping["inter_row"][:2]       # ΔX, ΔY per +1 row (ignore Z if present)
        icx, icy = mapping["inter_column"][:2]    # ΔX, ΔY per +1 column (ignore Z if present)
        off_x    = mapping["offset_x"]
        off_y    = mapping["offset_y"]
        X0, Y0   = origin["X"], origin["Y"]

        # ── translate to chip coordinate system ───────────────────────
        dX = x - (X0 + off_x)
        dY = y - (Y0 + off_y)

        # matrix inverse (2×2)
        det = irx * icy - icx * iry
        if abs(det) < 1e-12:            # degenerate mapping
            return None

        row_f = ( icy * dX - icx * dY) / det
        col_f = (-iry * dX + irx * dY) / det

        return row_f, col_f
    except Exception:
        # Return None if any error occurs during conversion
        return None

def pixels_to_microns(pixels, camera_model="AM16k", config_path=None):
    """
    Convert pixel measurements to microns based on camera calibration.

    Args:
        pixels: Number of pixels to convert
        camera_model: Camera model for calibration lookup (default: "AM16k")
        config_path: Optional config file containing calibration.pixel_calibration

    Returns:
        Distance in microns
    """
    calibration = _get_pixel_calibration(camera_model, config_path=config_path)
    return pixels * calibration["microns_per_pixel"]

def microns_to_pixels(microns, camera_model="AM16k", config_path=None):
    """
    Convert micron measurements to pixels based on camera calibration.

    Args:
        microns: Distance in microns to convert
        camera_model: Camera model for calibration lookup (default: "AM16k")
        config_path: Optional config file containing calibration.pixel_calibration

    Returns:
        Number of pixels
    """
    calibration = _get_pixel_calibration(camera_model, config_path=config_path)
    return microns * calibration["pixels_per_micron"]

def get_pixel_calibration_info(camera_model="AM16k", config_path=None):
    """
    Get calibration information for a camera model.

    Args:
        camera_model: Camera model name
        config_path: Optional config file containing calibration.pixel_calibration

    Returns:
        Dictionary with calibration details
    """
    return _get_pixel_calibration(camera_model, config_path=config_path)

def pixels_to_volume_nl(pixel_area, height_microns=50, camera_model="AM16k", config_path=None):
    """
    Convert pixel area to volume in nanoliters (nL) assuming cylindrical droplets.

    Args:
        pixel_area: Area in pixels from bounding box
        height_microns: Height of the droplet in microns (default: 50)
        camera_model: Camera model for pixel calibration (default: "AM16k")
        config_path: Optional config file containing calibration.pixel_calibration

    Returns:
        Volume in nanoliters (nL)
    """
    import math

    # Convert pixel area to physical area in microns²
    physical_area = (
        pixels_to_microns(pixel_area, camera_model, config_path=config_path)
        * pixels_to_microns(1, camera_model, config_path=config_path)
    )

    # Calculate radius from area (assuming circular cross-section)
    radius_microns = math.sqrt(physical_area / math.pi)

    # Calculate volume = π × r² × h
    volume_microns3 = math.pi * (radius_microns ** 2) * height_microns

    # Convert to nanoliters (1 nL = 1 × 10^-9 L = 1 × 10^6 μm³)
    volume_nl = volume_microns3 / 1_000_000  # Convert μm³ to nL

    return volume_nl

def area_pixels_to_radius_microns(pixel_area, camera_model="AM16k", config_path=None):
    """
    Convert pixel area to radius in microns (useful for droplet size analysis).

    Args:
        pixel_area: Area in pixels
        camera_model: Camera model for calibration
        config_path: Optional config file containing calibration.pixel_calibration

    Returns:
        Radius in microns
    """
    import math

    # Convert pixel area to physical area in microns²
    physical_area = (
        pixels_to_microns(pixel_area, camera_model, config_path=config_path)
        * pixels_to_microns(1, camera_model, config_path=config_path)
    )

    # Calculate radius
    radius_microns = math.sqrt(physical_area / math.pi)

    return radius_microns


    
    
