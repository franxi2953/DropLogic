# Hardware Utilities

Hardware utilities provide common conversions and configuration helpers used by real systems.

## Main Responsibilities

- load and save `config.json`
- convert electrode coordinates to stage coordinates
- convert stage coordinates back to electrode coordinates
- convert pixels, microns, and estimated volumes
- expose calibration metadata for camera models

## Where It Lives

- `droplogic/utils/hardware_utils/utils.py`

These helpers should stay small and deterministic. System-specific logic belongs in systems and modules, while these utilities should remain reusable across hardware integrations.
