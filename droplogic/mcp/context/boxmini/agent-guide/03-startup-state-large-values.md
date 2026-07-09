## Startup, State, And Large Values
Startup sequence:
1. Call `runtime_status()`; compact status is the default.
2. If needed, call `load_system(system="boxmini")`.
3. Call `capabilities()` and compact `state_summary()`.
4. Read active context files: this guide, cartridge JSON, protocol profile, and cockpit context when present.

Persistence rules:
- `config.json` stores configuration, calibration, defaults, and presets, not live state.
- The last processed `electrode_matrix.matrix` persists in a runtime sidecar such as `config.runtime-state.json`.
- BoxMini restores the last active matrix by default. Startup does not mean all electrodes are off.
- Use `reset_matrix=true` only when the user clearly wants an all-off startup; this sends an all-off command and persists zero/off afterward.
- Runtime telemetry such as `temperature.current`, `xy_stage.position`, light, camera, and microscope settings are session state, not sidecar-restored.

State inspection:
- Trust the latest tool result inside the same action sequence. Do not refresh status after every tool call unless the next decision depends on fresh state that was not already returned.
- Prefer one compact snapshot: use `execution_status_summary()` for runtime, executor, plan, droplets, matrix, planning-job, and execution-wait state. Use `execution_scene()` when you need visualizer geometry, current-frame droplet bboxes, paths, or action-path rendering.
- Use targeted status reads only when you need a specific missing field: `execution_wait_status(wait_seconds=...)` while a background execution wait is running, `planning_job_status()` while a background planning job is running, `matrix_summary()` for exact matrix ranges, or a module method for fresh hardware telemetry.
- Fresh status is required before the first hardware action, after a background wait/job reports completion, after errors or timeouts, before declaring the goal complete, and whenever the user or physical hardware may have changed state externally.
- Use `state_summary()` for broad inspection and `read_state(path="...")` for exact small values.
- Useful small paths: `temperature`, `temperature.current`, `xy_stage.position`, `xy_stage.position.Y`, `light_settings`, `microscope_settings`, `camera_settings`, `electrode_matrix.voltage`, `calibration`.
- Use `set_matrix_voltage(values=[...])` to change matrix voltage profiles; pass 9 channel values for DMLite/BoxMini profiles.
- Numeric path parts index list-like values: `electrode_matrix.matrix.42` reads row 42; `electrode_matrix.matrix.42.99` reads one electrode.
- Do not call `read_state(path="advanced_drop")` or `state_summary(path="advanced_drop")`; AdvancedDrop is not in `system.state`. Use droplet, plan, executor, and planning-job tools.
- Avoid `read_state()` with no path unless the user explicitly needs full raw state.
- State reads are cached snapshots. For fresh measurements, call the relevant tool or module method first, such as `module_call(module="temperature", method="get_temperature")`.

Large matrix guardrails:
- The matrix has `16,384` cells. Raw JSON can be duplicated through MCP `content` plus `structuredContent`; one raw matrix read can add hundreds of thousands of context characters.
- For matrix reasoning, use `matrix_summary(source="state", include_ranges=true)`.
- For combined plan/executor/matrix/droplet reasoning, use `execution_status_summary()` first. Use `execution_scene()` for rendering-focused geometry; it returns compact active-row encoding, executor cursor, current/last frame, droplet bboxes, targets, and bounded paths.
- `state_summary(path="electrode_matrix.matrix")` and matrix visualizer frames are also compact options.
- Raw full-matrix access requires explicit large-state permission. Do not request it during normal agent operation.
- If diagnosing queue failures, call `runtime_status(detail="full")`; compact `runtime_status()` intentionally omits queue internals.
