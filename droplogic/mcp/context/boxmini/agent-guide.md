# BoxMini Agent Quick Guide

## Mission And Tool Boundaries
Control BoxMini through DropLogic MCP. Turn user protocols into real DropLogic actions, execute only valid and understood plans, and confirm physical state with visual, model, or user feedback.

Prefer top-level MCP tools over generic or low-level calls:
- Session and context: `load_system`, `close_system`, `restart_system`, `runtime_status`, `health_check`, `capabilities`, `context_status`, `list_context_files`, `read_context_file`, `emergency_stop`.
- Observation: `execution_status_summary`, `execution_scene`, `state_summary`, `read_state`, `matrix_summary`, visualizer tools, `executor_status`, `plan_summary`, `droplets_summary`.
- Droplets and planning: `create_droplet`, `add_droplets`, `update_droplet_target(s)`, `update_droplet_position`, `delete_droplet`, `trim_plan_tail`, `plan_activation_frame`, `plan_move`, `plan_reservoir_extraction`, `plan_isometric_split`, `plan_mix`, `plan_merge`.
- Execution: prefer `execute_segment_to_breakpoint`; use direct `start_plan`, `resume_plan`, breakpoint tools, and `start_execute_until_breakpoint` only for recovery or non-default breakpoint control.
- Imaging, light, and temperature: prefer `set_streamer_source`, `configure_microscope_imaging`, `capture_droplet_images`, `verify_droplets`, `detect_condensates`, `set_light_state`, `light_off`, `temperature_hold`, and background temperature routines.
- Generic `advanced_drop_call`, `start_advanced_drop_call`, `advanced_drop_job_status`, `cancel_advanced_drop_job`, `system_call`, raw large-state reads, and unsafe state writes are debug-only surfaces when explicitly enabled. Do not use them in normal BoxMini operation.

Start BoxMini with `load_system(system="boxmini")`. Never call AdvancedDrop or module APIs to load or restart the system.

## Hardware And Coordinates
- System: `boxmini`; matrix: Acxel 16k, `128 x 128` logical electrodes.
- Core modules: `electrode_matrix`, `xy_stage`, `camera`, `microscope`, `light`, `temperature`, `capacitive_feedback`.
- Use logical matrix coordinates as `[row, column]`; `(0, 0)` is logical top-left.
- Camera and microscope views are rotated relative to logical matrix. Current working assumption: cartridge appears 90 degrees clockwise in camera view.
- Never treat electrode coordinates, stage coordinates, and camera pixels as interchangeable. Use configured presets and calibration helpers; do not invent absolute stage coordinates.

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

## Calibration And Geometry
- `config.json` is source of truth for machine calibration: pixel calibration, chip origin, electrode-to-stage mapping, backlash, named presets.
- Cartridge JSON stores cartridge geometry such as input holes and blocked/no-go regions.
- Use `droplogic.utils.hardware_utils` helpers instead of hand-written conversion math when writing code or interpreting calibrated quantities:
  - `electrode_to_stage(row, col)`
  - `stage_to_electrode((x, y))`, `stage_to_electrode_float((x, y))`
  - `pixels_to_microns(...)`, `microns_to_pixels(...)`, `get_pixel_calibration_info(...)`
  - `pixels_to_volume_nl(pixel_area, height_microns=50)`, `area_pixels_to_radius_microns(pixel_area)`
- For image-derived DMLite volume, use `height_microns=50`: `pixel_area * microns_per_pixel^2 * 50 / 1_000_000` nL.

## Visualizers, Cockpit, And Stage
- In cockpit mode, the browser/dashboard is the visualizer surface. Do not raise OpenCV windows unless the user explicitly asks for external windows.
- For real BoxMini runs outside cockpit mode, prepare both visualizers early unless the user says not to. `load_system(system="boxmini")` should auto-prepare them without forcing OS focus.
- If external visualizer windows are needed and not visible, call `visualizer_status`, then `bring_visualizer_to_front("streamer")` or `bring_visualizer_to_front("matrix")`.
- The matrix visualizer shows logical electrode plan/executor progression. The streamer shows live physical feedback from microscope or whole-chip camera.
- Use `set_streamer_source(source="microscope")` for droplet-scale work and `set_streamer_source(source="camera")` for whole-chip overview.
- Streamer should default to microscope feed, electrode overlay enabled, coordinates disabled unless debugging.
- Use `visualizer_frame(visualizer="streamer", frame_source="processed")` for annotated views and `frame_source="raw"` for unannotated frames when available.
- If no live frame appears after warmup, pause hardware work and ask the user.
- Stop visualizers with `stop_visualizer("streamer")` and `stop_visualizer("matrix")` when finished or before closing; `close_system` should also release them.

Stage movement:
- Prefer `move_stage(...)` for direct stage moves. Examples: `move_stage(preset="manual_injection")`, `move_stage(preset="whole_chip_camera")`, or `move_stage(position={"Y": 47000})`.
- Prefer execution view modes for viewing during execution: `execute_segment_to_breakpoint(execution_view_mode="follow_droplets")` or `execute_segment_to_breakpoint(execution_view_mode="whole_chip_camera", verify_positions=false)`.
- Use `set_execution_view_mode(mode="follow_droplets")` before microscope verification or droplet-scale imaging.
- Use `set_execution_view_mode(mode="whole_chip_camera")` for whole-chip overview before a fixed-view segment.
- Never call guessed stage methods such as `xy_stage.move_to`. Low-level fallback only: `module_call(module="xy_stage", method="move_axis_to_position", arguments={"axis": "Y", "target_position": 47000}, wait_if_busy=true)`.

## Planning And Execution Rhythm
Planning only changes logical state. Hardware moves only through `execute_segment_to_breakpoint`, `start_plan`, `resume_plan`, or explicit hardware calls.

Default real-hardware rhythm:
1. Plan one physical segment or checkpoint.
2. Inspect `plan_summary()`.
3. Execute to the segment target with `execute_segment_to_breakpoint(frame_number=null)`.
4. If the result is `wait_mode="inline"`, use its `wait_status` directly. If it starts a background wait, call `execution_wait_status(wait_seconds=<recommended_wait_seconds>)` once and let that timer return.
5. Verify or inspect, then plan the next segment.

Rules:
- For real hardware, dry electrode-only primitive tests, and matrix display tests, execute each planned physical segment before retargeting or planning the next segment unless the user explicitly asks for offline/batch planning.
- Planned-only actions are invisible to the physical system, and batch planning prevents adaptation to physical feedback.
- Do not plan all legs of a square path and execute once. Create/activate and execute; retarget leg 1, plan, execute, inspect; repeat for remaining legs.
- Treat requested final droplet count as the experimental goal, not permission for one large SIPP move. Extract and route in small physical batches.
- Plan only to the next visual/temperature check, injection confirmation, extraction validation, user decision, or risky transition.
- Leave `remove_duplicate_frames=false` during normal real-hardware operation. Use it only for explicit duplicate-frame debugging after inspecting the resulting plan.
- Prefer `execute_segment_to_breakpoint` for normal segment execution. It clears old breakpoints by default, adds the target breakpoint, chooses `start_plan` for a new run or `resume_plan` for a partial run, and uses `wait_mode="auto"` so short segments finish inline and long segments run as a background wait.
- Default execution frame delay is `1.0` second, and that is the correct normal operating pace. Omit `frame_delay` unless the user explicitly asks for another speed; never invent sub-second execution.
- For background execution waits, do not make repeated immediate `execution_wait_status()` calls. Use the returned `recommended_wait_seconds`, `next_check_after_seconds`, or `recommended_status_call`; if the timer returns `running=true`, repeat one timer wait using the new recommendation.
- Use manual `add_breakpoint` plus `start_plan`/`resume_plan` plus `start_execute_until_breakpoint` only when you need non-default breakpoint handling.
- `start_plan` starts from frame `0`. Never use it directly to continue a paused or partially executed run.
- `resume_plan` is for unusual recovery/debug cases. If `start_plan` says it would restart from frame `0`, treat that as a safety stop.
- `current_frame` is the next frame to execute; `executor_status.last_frame.index` is the last physical frame sent. After a breakpoint, resume should continue from the next unexecuted frame.
- `start_plan`, `resume_plan`, and `execute_segment_to_breakpoint` refuse `planning_success=false` by default. Fix the plan first; use `allow_failed_plan=true` only for explicit supervised debugging.
- Long blocking waits can exceed client timeouts while hardware keeps its last state. Use the bounded background timer form `execution_wait_status(wait_seconds=...)` instead of immediate polling.
- If `executor_status` reports `is_executing=false` and `current_frame >= total_frames`, execution is already stopped/complete. Do not call `stop_plan` as a final confirmation; use status as completion evidence.
- `cancel_execution_wait()` cancels only the MCP wait job. Use `pause_plan()` or `stop_plan()` to affect hardware execution.
- `cancel_planning_job()` requests cooperative cancellation; CPU-bound SIPP may finish its current planning call first.
- If a long call times out and later tools say `No system loaded`, assume MCP may have restarted. Reload only after physical state is safe, then reconstruct logical droplets from physical/visual state.

Planning primitive tools:
- Use `plan_activation_frame(event_type="activation")` after creating a reservoir or droplets that only need footprint activation.
- Use `plan_move(...)` after setting droplet targets with `update_droplet_target(s)`.
- Use `trim_plan_tail(keep_frames=N)` only to delete unexecuted planned tail frames. It rejects cuts that would remove already executed/applied frames; after trimming, inspect the timeline before planning new frames.
- For large coordinated moves, use `plan_move(planning_timeout=1200, background=true)`, then poll `planning_job_status()`. Dashboard agent calls may force `background=true` with a bounded timeout for safety.
- Do not put labels, checkpoints, notes, or other metadata in `plan_move(options=...)`. Only documented planner options belong there; unknown options are ignored by MCP and reported as `ignored_options`.
- Use `plan_reservoir_extraction(...)` for extracting one or more droplets from a reservoir.
- Use `plan_isometric_split(...)`, `plan_mix(...)`, and `plan_merge(...)` for those named operations.
- These tools only append/update the logical plan. Always inspect the tool result/`plan_summary()` before execution.
- For `plan_reservoir_extraction`, `plan_isometric_split`, `plan_mix`, and `plan_merge`, treat `ok=false`, `primitive_validation.ok=false`, `result=null`, or `planning_success=false` as a failed primitive. Do not execute it, do not continue as if it succeeded, and do not use it as completion evidence.
- If planning fails, times out, or returns `planning_success=false`, split into waypoints or smaller groups.
- For `plan_merge`, first move non-merge droplets away from the merge target and avoid targets inside another droplet's vital space. Prefer merging into an open hub 4-8 electrodes away from nearby droplets, then execute the merge segment before any `plan_mix` or final routing.
- A successful `plan_merge` must return the merged droplet id. The merged-away input droplets can remain in `droplets_summary()` for history, but their `active=false` flag and absence from `plan.active_droplet_ids` means they are not planning candidates. Plan only active droplets unless the user explicitly asks to restore or correct an inactive one.
- After a failed merge/split/mix attempt, refresh `execution_status_summary(include_droplets=true, include_plan=true)` and reason from the last executed frame. Do not trust logical droplet positions from a failed, unexecuted plan; correct them only from visual/user confirmation.
- SIPP reserves active droplets' current/initial footprints while planning. Do not expect one droplet to move into another active droplet's starting footprint in the same `plan_move()` call just because that other droplet will eventually leave.
- For swaps, crossings, reordering, or any move where a target/vital space overlaps another moving droplet's current footprint, use staged moves: first retarget the blocking droplets to intermediate parking positions that free the contested starts/targets, plan and execute that segment, then retarget from those intermediate positions to the final targets in one or more later `plan_move()` calls.
- For visual crossing tests, use intermediate staging lanes or parking cells to make space first, then route through the crossing area. A successful crossing may require multiple executed move segments; do not force all crossings and final targets into one coordinated move.

## Droplets, Reservoirs, And Injection
Droplet tools:
- Use `create_droplet(droplet_id=1, origin=[row, col], target=[row, col], width=1, height=1)` for one droplet.
- Use `add_droplets(droplets=[...])` for batches. Each entry needs `id`/`droplet_id` and `origin`; include `target` unless explicitly optional.
- Valid batch entry: `{"id": 1, "origin": [42, 1], "target": [30, 30], "width": 1, "height": 1}`.
- After `add_droplets`, verify `created_count == requested_count` and `droplets.total_droplets` increased; otherwise stop and report the error.
- Retarget with `update_droplet_targets(targets=[{"id": 1, "target": [30, 30]}])` or `update_droplet_targets(targets={"1": [30, 30]})`; do not delete/recreate just to retarget.
- Use `update_droplet_position` only after visual/user confirmation that the physical droplet is at that coordinate.
- `update_droplet_targets` returns compact count/id summary by default. Set `include_summary=true` only when the full droplet summary is needed.
- `delete_droplet(droplet_id=...)` removes the logical droplet and, by default, clears that droplet's electrodes in the next plan frame (`persist_electrodes=false`). Use `persist_electrodes=true` only for explicit supervised debugging where the physical/electrical footprint must remain active; otherwise it leaves ghost electrodes that can confuse later planning and visual interpretation.
- For droplets larger than `1 x 1`, default `vital_space=2` and at least `2` electrodes between extraction targets/reservoir exits unless specified otherwise.
- SIPP gets expensive with many droplets, dense routes, narrow corridors, overlapping vital spaces, or crossing/reordering. Prefer smaller batches, especially above about 10 active droplets.
- Check that intended final positions and vital spaces do not intersect current droplet positions. If they do, do not ask SIPP to solve the swap in one call; move the blockers to intermediate parking positions first.

Reservoir and injection rules:
- Default cartridge family: Acxel 16k.
- User injections enter from lateral input holes; hole definitions belong in cartridge JSON.
- Manual injection/loading position is `config.json.presets.stage.manual_injection.position`; current BoxMini preset is `Y=47000`.
- Unless user or cartridge JSON defines blocked/no-go regions, assume the matrix is usable.
- Reservoirs for injected liquid should be near the relevant border but not on the border. Leave at least one row/column margin.
- Before asking the user to inject, reservoir electrodes must already be active on the real matrix. Create reservoir, execute activation, verify/inspect it, then move to injection position or tell the user to inject.
- Create-only reservoir activation is a valid physical segment when the plan is executable; do not add fake moves just to make an activation visible.
- After moving to manual injection position, wait for user confirmation that injection is complete.
- After confirmation, return to the previous Y position unless the protocol profile defines another operating/imaging position.
- Before extraction/downstream operations, move injected reservoir `5-10` electrodes from the edge. Execute and verify this relocation before extracting.
- Keep experiment-specific stage or imaging overrides in a protocol profile.

Reservoir sizing:
- Size reservoirs for consumed electrode area plus at least `20` extra electrodes unless specified otherwise.
- Consumed area is approximately `count * width * height`. Example: `20` droplets of `2 x 2` consume `80` electrodes, so use at least `100` reservoir electrodes.
- Extra area covers residual liquid, edge loss, imperfect splitting, and dead volume.

## Reservoir Extraction
Choose mode from user intent/liquid behavior:
- `split_mode="linear"`: default fast extraction of several droplets.
- `split_mode="1to2"`: one-by-one validation, volume checking, or tighter manual control.
- `split_mode="1to3"`: difficult liquids, repeated failure of `linear`/`1to2`, or explicit user request.

Extraction workflow:
1. If reservoir was just injected near an input hole, relocate it `5-10` electrodes from edge, execute, and verify.
2. Plan the next extraction batch or single-droplet extraction only.
3. Inspect `plan_summary()`; if `planning_success=false`, do not execute. Reduce batch size, change spacing/offsets, or ask.
4. Execute the segment with `execute_segment_to_breakpoint(frame_number=null)`.
5. If execution starts a background wait, call `execution_wait_status(wait_seconds=<recommended_wait_seconds>)` and repeat only if the timer returns `running=true`.
6. Verify extracted droplets before routing unless the user explicitly requested unattended execution.

Extraction parameters:
- For linear extraction of `2 x 2` or larger droplets, pass `linear_drop_shape=[2, 2]`, `linear_space_per_row=2`, `linear_space_per_col=2`, and `linear_vital_space=2`. Do not rely on `split_size` alone for linear mode.
- Linear extraction positions must fit fully inside the reservoir footprint before severing. Large `linear_offset` values can create logical droplets outside the reservoir and should fail. For compact reservoirs such as `8 x 6` extracting four `2 x 2` droplets with spacing `2`, prefer `linear_offset=0`; if extraction fails, reduce offset/count/spacing or use a larger reservoir/different direction.

Validation:
- If execution used `whole_chip_camera`, do not run microscope/YOLO verification during movement. Pause, switch deliberately to `follow_droplets`/microscope, then verify.
- Otherwise, verify extracted droplets with `verify_droplets` at the current executor frame. Use up to `3` short checks for a newly extracted droplet before declaring it missing.
- If found, mark the droplet valid and route it in a later segment.
- If missing, delete that logical droplet or execute an explicit planned cleanup if the protocol defines one, then retry extraction.
- If the same extraction fails more than `3` times, stop and ask unless user requested unattended full-protocol run. For unattended runs, log/return force-accepted/skipped and continue by protocol.
- Do not route unverified droplets unless protocol/user allows force-accepting failed checks.

## Execution View Modes And Diagnostics
- Default execution view: `follow_droplets`. PlanExecutor may move the XY stage to keep active droplets under microscope view.
- Use `execute_segment_to_breakpoint(execution_view_mode="whole_chip_camera", verify_positions=false)` for fixed whole-chip execution. This applies `config.json.presets.imaging.whole_chip_camera`, switches streamer to camera, moves to fixed overview stage position, and disables droplet-follow tracking.
- Use `execute_segment_to_breakpoint(execution_view_mode="follow_droplets")` for normal microscope-follow execution.
- Use `set_execution_view_mode(mode="follow_droplets")` before microscope droplet checks, visual correction, or model verification.
- `whole_chip_camera` and `follow_droplets` are mutually exclusive. Do not switch streamer/stage while a segment is running.
- In `whole_chip_camera` or fixed-stage execution, keep `verify_positions=false`. Executor verification is not passive: it moves stage, changes light, and calls microscope droplet verification.
- If execution returns `started_wait=false` or `reason="execution_view_not_ready"`, do not restart hardware. Inspect diagnostics, wait/correct the view, then retry execution.
- In `whole_chip_camera`, execution should not move XY stage frame-by-frame or change camera/light preset. If frames are far slower than `frame_delay`, view goes black, stage moves, or light changes, pause/stop and inspect diagnostics.
- If stage moves but matrix visualizer/physical matrix does not update, pause/stop. Inspect `executor_status`, `runtime_status(detail="full")`, `matrix_summary(source="state")`, and `visualizer_status`.
- Empty queues mean no pending commands, not command success. Check `executor_status.last_frame` and `runtime_status(detail="full").system.queues.*.last_command_error` before calling slow pace normal.
- Executor retries a failed `electrode_matrix.matrix` frame write once. If `executor_status.last_frame.matrix_queue_wait.successful_attempt` is set, report transient retry. If all attempts fail, stop and diagnose before manual retry.
- Do not verify every frame. Verify after injection/reservoir setup, extraction batches, split/merge, recovery moves, and before long unattended imaging.
- Droplet vision checks are reliable only up to about `2 x 2` electrodes. For larger reservoirs/irregular shapes, use human inspection, saved frames, or protocol-specific checks.

## Imaging, Light, And Vision
Light safety:
- Cartridges can leak or degrade under strong light. Use low coaxial light and longer exposure while moving or monitoring droplets.
- Higher illumination may be acceptable for static fluorescence; restore conservative settings quickly.
- Avoid leaving high coaxial light on after fluorescence capture.
- To turn illumination off, call top-level `light_off()`. Do not guess low-level `module_call(module="light", method="switch_light", ...)`.
- To set illumination outside an imaging capture, call `set_light_state(light_on=..., coaxial_intensity=..., ring_intensity=...)`. Intensities are `0` to `99`; positive coaxial/ring values turn the master light on automatically. Passing both intensities as `0` turns the master light off.

Default imaging settings:
- Manual injection monitoring: `Brightfield`, auto exposure `False`, exposure `3600` us, coaxial `5`, ring `0`. If `set_exposure` fails, do not retry blindly; use state updates or `module_call(module="microscope", method="set_parameter", arguments={"param_type":"float_value","node_name":"ExposureTime","node_value":3600})`.
- Brightfield droplet verification: `Brightfield`, auto exposure `False`, exposure `72000` us, gain `0`, coaxial `4`, ring `0`.
- Whole-chip camera overview: source of truth `config.json.presets.imaging.whole_chip_camera`; current preset `X=84480`, `Y=5029`, `Z=4202`; streamer `camera`; camera auto exposure `False`; exposure `72000` us; gain `0`; coaxial `0`; ring `30`. Return to microscope before droplet/model checks.
- IVT RNA condensate detection only: prefer `configure_microscope_imaging(channel="FAM", exposure_time=4800000, gain=0, coaxial_intensity=99, ring_intensity=0)`. FAM: exposure `4800000` us, gain `0`, coaxial `99`, ring `0`, auto exposure `False`. Brightfield crop: exposure `72000` us, gain `0`, coaxial `4`, ring `0`. Crop droplets `true`, padding `50`, confidence `0.25`.

Batch imaging:
- For repeated droplet imaging, prefer `capture_droplet_images(...)` over raw `module_call(... capture_image ...)`.
- `capture_droplet_images` moves to each droplet, applies channel/exposure/gain/light, turns light master on when needed, waits for hardware, discards/warmups frames, captures, and writes files with OpenCV.
- Do not assume low-level `capture_image(save_path=...)` saves a file; some modules return arrays without writing.
- If metadata points to missing files, retake those captures with `capture_droplet_images`.
- Default `capture_source="streamer"` captures from the warmed live stream after discard/warmup frames.
- Use `capture_source="pause_streamer"` only for direct/full-resolution microscope capture; it stops/restarts streamer and restores low light.
- During multi-channel capture, light stays configured through all channels for the current droplet and is restored after that droplet's channel set.
- Each capture includes requested settings and best-effort exposure/gain readback; use it to audit melting curves.
- Defaults: channels `["Brightfield", "FAM"]`; Brightfield exposure `72000` us, gain `0`, coaxial `4`, ring `0`; FAM exposure `4800000` us, gain `0`, coaxial `99`, ring `0`.
- For melting curves/time series, call `capture_droplet_images(droplet_ids=[...], channels=["Brightfield","FAM"], output_dir=..., temperature_label=..., metadata={...})` at each temperature/time point.
- Do not batch-image while executor is moving or `whole_chip_camera` fixed-stage execution is active. Pause at breakpoint and switch to microscope/follow mode first.

Vision tools:
- `verify_droplets`: moves to expected positions, checks brightfield droplet presence, restores previous settings when possible.
- `detect_condensates`: IVT RNA condensates only; uses FAM fluorescence plus brightfield cropping when `crop_droplet=true`.
- Default models: droplets `droplogic/utils/drop_vision/models/droplets.pt`; condensates `droplogic/utils/drop_vision/models/condensates.pt`.
- If feedback disagrees with the plan, do not trust the planner position. Use `update_droplet_position` only after visual/user confirmation; otherwise pause and ask or save frames.

## Temperature
- Use `temperature_hold(target_c=..., hold_seconds=...)` for short single-setpoint waits.
- For long ramps, per-degree waits, `require_settle=true`, or multi-minute holds, use `start_temperature_routine(steps=[...], require_settle=true)` and poll `temperature_routine_status()`.
- Use `cancel_temperature_routine()` before changing strategy or closing if a background routine is active.
- Do not keep one MCP call open for a long ramp. If no background routine exists, drive the ramp with short set/poll calls.

## Faults And Safety Stops
- Use `emergency_stop()` for urgent hardware stop/deactivation situations.
- Do not continue after a visual/vision mismatch without correction or user confirmation.
- Do not restart or reinitialize real hardware automatically after a fault.
- Do not clear the restored matrix at startup unless the user explicitly asks for `reset_matrix=true` or an all-off start.
- Do not use unsafe raw matrix writes unless explicitly supervised.
- Do not assume reagent identity from hole labels.
- Do not invent stage coordinates for loading, imaging, or recovery.
- Do not leave high illumination on longer than needed.
