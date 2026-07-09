## Imaging, Light, And Vision
Light safety:
- Cartridges can leak or degrade under strong light. Use low coaxial light and longer exposure while moving or monitoring droplets.
- Higher illumination may be acceptable for static fluorescence; restore conservative settings quickly.
- Avoid leaving high coaxial light on after fluorescence capture.
- To turn illumination off, call top-level `light_off()`. Do not guess low-level `module_call(module="light", method="switch_light", ...)`.
- To set illumination outside an imaging capture, call `set_light_state(light_on=..., coaxial_intensity=..., ring_intensity=...)`. Intensities are `0` to `99`; positive coaxial/ring values turn the master light on automatically. Passing both intensities as `0` turns the master light off.

Preset-based imaging settings:
- `config.json.presets` is the source of truth for imaging, light, and named stage positions. Do not copy numeric exposure, gain, illumination, or stage coordinates from this guide or from old run history.
- For FAM fluorescence, melting curves, or fluorescence time series, use the current `config.json.presets.imaging.microscope_fam` preset. Inspect or apply the preset at run time; do not hardcode FAM exposure/gain/light values in tool arguments unless the user explicitly overrides them.
- For brightfield inspection or droplet verification, use the current `config.json.presets.imaging.microscope_brightfield` preset unless a tool documents its own internal verification settings.
- For melting-curve captures, pass a channel name such as `channels=["FAM"]` or a preset reference; let the tool resolve current saved preset values. Do not restate or send exposure/gain/light numbers just because an older document or run mentioned them.
- For fixed whole-cartridge overview, use `config.json.presets.imaging.whole_chip_camera` via `execute_segment_to_breakpoint(execution_view_mode="whole_chip_camera", verify_positions=false)`, `set_execution_view_mode(mode="whole_chip_camera")`, or `move_stage(preset="whole_chip_camera")` as appropriate. Return to microscope before droplet/model checks.
- Manual injection monitoring should use the configured brightfield/manual-injection presets where available. If hardware rejects an exposure/gain change, do not retry blindly; inspect state and only use low-level `module_call(...)` with values read from the current preset or explicit user instructions.
- IVT RNA condensate detection is protocol-specific. Use `detect_condensates` with its documented arguments and current imaging presets rather than embedding fixed FAM/Brightfield camera values.

Batch imaging:
- For repeated droplet imaging, prefer `capture_droplet_images(...)` over raw `module_call(... capture_image ...)`.
- `capture_droplet_images` moves to each droplet, applies channel/exposure/gain/light, turns light master on when needed, waits for hardware, discards/warmups frames, captures, and writes files with OpenCV.
- Do not assume low-level `capture_image(save_path=...)` saves a file; some modules return arrays without writing.
- Do not save images with bare filenames or repo-root paths such as `cartridge_30C.png` or `run_images`. Use the managed capture output returned by the tool, or an explicit absolute user/run artifact path. Relative image paths are resolved under `DROPLOGIC_CAPTURE_ROOT` or, by default, `Documents/DropLogic/captures`.
- If metadata points to missing files, retake those captures with `capture_droplet_images`.
- Default `capture_source="streamer"` captures from the warmed live stream after discard/warmup frames.
- Use `capture_source="pause_streamer"` only for direct/full-resolution microscope capture; it stops/restarts streamer and restores low light.
- During multi-channel capture, light stays configured through all channels for the current droplet and is restored after that droplet's channel set.
- Each capture includes requested settings and best-effort exposure/gain readback; use it to audit melting curves.
- For melting curves/time series with a photo at every step, prefer `start_melting_curve_capture(...)` so the runtime itself performs `set/wait/hold -> capture -> next step`. Use `capture_mode="droplets", channels=["FAM"]` for per-droplet fluorescence with current saved presets, or `capture_mode="whole_chip_camera"` when the user explicitly wants whole-cartridge overview photos. Poll `melting_curve_capture_status()` until complete; use `cancel_melting_curve_capture()` to stop.
- If you do not use `start_melting_curve_capture`, you must explicitly repeat one step at a time: `temperature_hold(...)`, wait for that single step to complete, then `capture_droplet_images(droplet_ids=[...], channels=["FAM"], output_dir=..., temperature_label=..., metadata={...})`. Do not start one long background temperature routine for a curve that needs images at every step.
- Do not batch-image while executor is moving or `whole_chip_camera` fixed-stage execution is active. Pause at breakpoint and switch to microscope/follow mode first.

Vision tools:
- `verify_droplets`: moves to expected positions, checks brightfield droplet presence, restores previous settings when possible.
- `detect_condensates`: IVT RNA condensates only; uses FAM fluorescence plus brightfield cropping when `crop_droplet=true`.
- Default models: droplets `droplogic/utils/drop_vision/models/droplets.pt`; condensates `droplogic/utils/drop_vision/models/condensates.pt`.
- If feedback disagrees with the plan, do not trust the planner position. Use `update_droplet_position` only after visual/user confirmation; otherwise pause and ask or save frames.
