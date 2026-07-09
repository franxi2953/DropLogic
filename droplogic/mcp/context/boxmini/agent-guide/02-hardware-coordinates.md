## Hardware And Coordinates
- System: `boxmini`; matrix: Acxel 16k, `128 x 128` logical electrodes.
- Core modules: `electrode_matrix`, `xy_stage`, `camera`, `microscope`, `light`, `temperature`, `capacitive_feedback`.
- Use logical matrix coordinates as `[row, column]`; `(0, 0)` is logical top-left.
- Camera and microscope views are rotated relative to logical matrix. Current working assumption: cartridge appears 90 degrees clockwise in camera view.
- Never treat electrode coordinates, stage coordinates, and camera pixels as interchangeable. Use configured presets and calibration helpers; do not invent absolute stage coordinates.
