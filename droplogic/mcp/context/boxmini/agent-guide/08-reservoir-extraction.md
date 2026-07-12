## Reservoir Extraction
Choose mode from user intent/liquid behavior:
- `split_mode="linear"`: default fast extraction of several droplets.
- `split_mode="1to2"`: one-by-one validation, volume checking, or tighter manual control.
- `split_mode="1to3"`: difficult liquids, repeated failure of `linear`/`1to2`, or explicit user request.

Extraction workflow:
1. If reservoir was just injected near an input hole, relocate it `5-10` electrodes from edge, execute, and verify.
2. Plan the next extraction batch or single-droplet extraction only. Do not append several extraction batches before executing and inspecting the current batch.
3. Inspect `plan_summary()`; if `planning_success=false`, do not execute. Reduce batch size, use a larger reservoir, change direction, or adjust/increase the stagger/spacing. On BoxMini hardware, do not make a failed linear extraction fit by reducing row/column spacing below the droplet-scaled safe minimum.
4. Execute the segment with `execute_segment_to_breakpoint(frame_number=null)`.
5. If execution starts a background wait, call `execution_wait_status(wait_seconds=<recommended_wait_seconds>)` and repeat only if the timer returns `running=true`.
6. Verify extracted droplets before routing unless the user explicitly requested unattended execution.

Extraction parameters:
- For linear extraction, pass `linear_drop_shape` matching the intended footprint, choose `linear_space_per_row`/`linear_space_per_col` from the footprint dimensions, set `linear_vital_space` to the droplet vital space, keep `linear_post_separation_steps=3`, and use a staggered `linear_offset` unless the user explicitly asks for denser packing. Linear extraction is much more reliable when the extraction grid uses well-spaced rows and columns; do not pack a dense one-electrode/two-electrode chain and then declare extraction failure from vision alone.
- `2 x 2` is the hardest-tested BoxMini extraction footprint. Smaller `1 x 1` extractions can be harder, not easier, because the droplet has less volume/contact margin and may be less stable during separation. Use `1 x 1` only when the protocol needs it, and be ready to slow down, increase separation/inspection, or switch mode if it behaves poorly.
- In linear extraction, `linear_space_per_row` and `linear_space_per_col` are clear side-to-side gaps between droplets, not the pitch from one droplet origin to the next. The placement pitch is droplet size plus gap. Required minimum clear gap scales with footprint: at least `2 * droplet height` for rows and `2 * droplet width` for columns, unless the protocol defines a more conservative liquid-specific value.
- `linear_post_separation_steps` makes the reservoir keep sweeping a few electrodes after the last droplet has severed. Keep the BoxMini default at `3` so the reservoir tail clears the extracted droplets before inspection or the next extraction batch.
- Use staggered linear extraction geometry for multi-droplet batches when it stays inside the reservoir sweep strip. Choose `linear_offset` from the droplet footprint, commonly around one droplet dimension or half the placement pitch. With `linear_direction=[0, 1]` or `[0, -1]`, `linear_offset` shifts the starting row on alternating columns. With `linear_direction=[1, 0]` or `[-1, 0]`, it shifts the starting column on alternating rows. This creates an even/odd column or row stagger instead of perfectly aligned extracted droplets.
- Linear extraction droplets only need to fit inside the moving reservoir sweep, not inside the initial reservoir footprint along the sweep direction. It is valid for later columns/rows to be created once the reservoir reaches them, and the last row/column does not need to be exhausted before planning the next one. Large `linear_offset` values that move droplets outside the orthogonal sweep strip should still fail. For compact reservoirs, reduce droplet count per extraction batch, use a larger reservoir, extract in multiple smaller batches, or choose a different direction/mode. Do not reduce `linear_space_per_row` or `linear_space_per_col` below the droplet-scaled safe minimum on BoxMini hardware just to make a batch fit, unless the user explicitly asks for a dense/simulation-only layout.
- For `split_mode="1to2"` or `split_mode="1to3"`, `steps` is one two-integer offset `[row_offset, col_offset]`, not a list of step vectors. Example: `steps=[0, 8]` extracts east/right of the reservoir; `steps=[8, 0]` extracts south/down. Set `split_size` to the intended central droplet footprint and tune `separation_steps` for harder liquids.
- `1to3` extracts one droplet per call. If linear extraction repeatedly fails, plan one `1to3` extraction, execute, verify, then repeat from the updated reservoir state instead of asking `1to3` for many droplets at once.

Validation:
- If execution used `whole_chip_camera`, do not run microscope/YOLO verification during movement. Pause, switch deliberately to `follow_droplets`/microscope, then verify.
- Otherwise, verify extracted droplets with `verify_droplets` at the current executor frame. Always save verification frames by passing `save_frames_path` to a run-specific debug folder; in cockpit/dashboard mode this path may be added automatically, but still check `frame_files` in the result before trusting a failed check.
- Use up to `3` short checks for a newly extracted droplet before declaring it missing. If `frame_files` are missing/null or the user says they can see electrodes/droplets, treat the result as inconclusive and inspect saved frames or ask for confirmation instead of deleting logical droplets.
- If found, mark the droplet valid and route it in a later segment.
- If missing, delete that logical droplet or execute an explicit planned cleanup if the protocol defines one, then retry extraction.
- If the same extraction fails more than `3` times, stop and ask unless user requested unattended full-protocol run. For unattended runs, log/return force-accepted/skipped and continue by protocol.
- Do not route unverified droplets unless protocol/user allows force-accepting failed checks.
