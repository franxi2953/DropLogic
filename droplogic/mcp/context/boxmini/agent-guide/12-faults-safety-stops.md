## Faults And Safety Stops
- Use `emergency_stop()` for urgent hardware stop/deactivation situations.
- Do not continue after a visual/vision mismatch without correction or user confirmation.
- Do not restart or reinitialize real hardware automatically after a fault.
- Do not clear the restored matrix at startup unless the user explicitly asks for `reset_matrix=true` or an all-off start.
- Do not use unsafe raw matrix writes unless explicitly supervised.
- Do not assume reagent identity from hole labels.
- Do not invent stage coordinates for loading, imaging, or recovery.
- Do not leave high illumination on longer than needed.
