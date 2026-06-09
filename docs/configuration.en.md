# Configuration

`config.json` is the default state file used by DropLogic systems.

The public default lives at the repository root:

```text
config.json
```

When you instantiate a system without passing a custom path, the system loads `config.json` from the current working directory. If you run examples from the cloned repository root, this is the repository default:

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite(config_file="config.json")
```

If your script runs from another folder, pass an explicit path. You can keep the repository default and use a machine-specific copy instead:

```python
system = DMLite(config_file="local_config.json")
```

`local_config*.json`, `config.local.json`, and `calibration_data.json` are ignored by Git so private machine calibration can stay local.

`DMLite` and `BOXMini` are hardware platforms from [Acxel](https://www.acxel.com/). This repository contains Python adapters and shared control logic around supported hardware; vendor hardware and native runtime files are not part of the library.

## Should It Be In The Repository?

Yes. The base `config.json` is part of the public repository because it is the default schema and starting point for the library.

Do not put secrets, private SDK paths, native libraries, API keys, or personal credentials in it. Vendor SDK files and native runtime assets are intentionally excluded from the repository.

## What DMLite Needs

`DMLite` only needs the `electrode_matrix` block.

Required fields:

| Field | Meaning | Default |
| --- | --- | --- |
| `electrode_matrix.rows` | Matrix row count | `128` |
| `electrode_matrix.columns` | Matrix column count | `128` |
| `electrode_matrix.voltage` | Electrode actuation voltage | `55` |
| `electrode_matrix.version` | Low-level matrix implementation | `DMLite` |
| `electrode_matrix.matrix` | Runtime matrix state | `[]` at startup |

For the current DMLite setup, the repository defaults are suitable. The system resets `electrode_matrix.matrix` on startup, so users normally do not edit that field manually.

`electrode_matrix.version: "DMLite"` loads the native runtime for the current OS and CPU architecture. The supported DMLite runtimes are Windows x86_64, macOS Apple Silicon, Linux x86_64, Raspberry Pi OS 64-bit, and Raspberry Pi OS 32-bit. If the matching runtime file is not installed, `DMLite()` raises a clear error.

## What The Simulator Needs

`Simulator` uses:

| Field | Meaning |
| --- | --- |
| `electrode_matrix.rows` / `columns` | Simulated matrix size |
| `electrode_matrix.voltage` | Simulated voltage value |
| `xy_stage.position` | Initial mock stage position |

The rest of the file can remain at default values for simulator-only workflows.

## What BOXMini-Style Systems Need

Larger hardware systems use more blocks:

| Block | Used For | User Usually Edits |
| --- | --- | --- |
| `temperature` | Temperature serial module | `Port`, `version` |
| `xy_stage` | Stage position, motion parameters, limits | `safe_limits`, `position`, `motion_params` |
| `camera_settings` | MVS camera exposure/gain | `auto_exposure`, `exposure_time`, `gain`, `version` |
| `microscope_settings` | Microscope exposure/channel/serial | `Port`, `current_channel`, `total_channels` |
| `light_settings` | Ring/coaxial light controllers | `VID`, `PID`, `upled_serial`, intensities, `version` |
| `capacitive_feedback` | Feedback module selection | `version` |

Only fill these blocks if your selected system actually instantiates those modules.

## Calibration Block

`calibration` contains the measured values used at runtime for camera pixel conversion, electrode/stage conversion, and optional XY backlash compensation.

Current pixel calibration:

| Field | Value | Meaning |
| --- | --- | --- |
| `calibration.pixel_calibration.AM16k.microns_per_pixel` | `0.51413882` | um per pixel |
| `calibration.pixel_calibration.AM16k.pixels_per_micron` | `1.94500000` | pixels per um |

Stage/electrode mapping:

| Field | Meaning |
| --- | --- |
| `calibration.chip_origin` | Stage coordinate corresponding to electrode `(0, 0)` |
| `calibration.electrode_mapping.inter_row` | Stage delta for moving one electrode row |
| `calibration.electrode_mapping.inter_column` | Stage delta for moving one electrode column |
| `calibration.electrode_mapping.offset_x` / `offset_y` | Extra offsets applied before conversion |
| `calibration.backlash_steps` | Optional XY backlash compensation by direction |

Measure and update `chip_origin`, `inter_row`, and `inter_column` for each physical machine/chip alignment.

## Practical Editing Workflow

1. Start from the repository `config.json`.
2. Copy it to `local_config.json` for machine-specific edits.
3. Update only the blocks used by the system you instantiate.
4. Run a simulator or DMLite smoke test.
5. Commit only schema/default changes, not private machine-specific local calibration.
