# BoxMini Agent Quick Guide

## Mission And Tool Boundaries
Control BoxMini through DropLogic MCP. Turn user protocols into real DropLogic actions, execute only valid and understood plans, and confirm physical state with visual, model, or user feedback.

Prefer top-level MCP tools over generic or low-level calls:
- Session and context: `load_system`, `close_system`, `restart_system`, `runtime_status`, `health_check`, `capabilities`, `context_status`, `list_context_files`, `read_context_file`, `emergency_stop`.
- Observation: `execution_status_summary`, `execution_scene`, `state_summary`, `read_state`, `matrix_summary`, visualizer tools, `executor_status`, `plan_summary`, `droplets_summary`.
- Droplets and planning: `clear_droplet_state`, `create_droplet`, `add_droplets`, `update_droplet_target(s)`, `update_droplet_position`, `delete_droplet`, `trim_plan_tail`, `plan_activation_frame`, `plan_move`, `plan_reservoir_extraction`, `plan_isometric_split`, `plan_mix`, `plan_merge`.
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
- Use `set_streamer_source(source="microscope")` for droplet-scale work. Do not treat `set_streamer_source(source="camera")` alone as whole-cartridge visualization; it changes the video source but does not by itself choose the correct fixed stage/executor view.
- Streamer should default to microscope feed, electrode overlay enabled, coordinates disabled unless debugging.
- Use `visualizer_frame(visualizer="streamer", frame_source="processed")` for annotated views and `frame_source="raw"` for unannotated frames when available.
- If no live frame appears after warmup, pause hardware work and ask the user.
- Stop visualizers with `stop_visualizer("streamer")` and `stop_visualizer("matrix")` when finished or before closing; `close_system` should also release them.

Stage movement:
- Prefer `move_stage(...)` for direct stage moves. Examples: `move_stage(preset="manual_injection")` or `move_stage(preset="whole_chip_camera")`.
- Prefer execution view modes for viewing during execution: `execute_segment_to_breakpoint(execution_view_mode="follow_droplets")` or `execute_segment_to_breakpoint(execution_view_mode="whole_chip_camera", verify_positions=false)`.
- Use `set_execution_view_mode(mode="follow_droplets")` before microscope verification or droplet-scale imaging.
- Use `set_execution_view_mode(mode="whole_chip_camera")` for whole-cartridge/whole-chip overview before a fixed-view segment. This applies the camera source, camera/light preset, fixed stage position, and disables droplet-follow stage tracking.
- Never call guessed stage methods such as `xy_stage.move_to`. If a low-level fallback is unavoidable, first read the named preset from `config.json` and pass that value; do not use memorized absolute stage coordinates.

## Planning And Execution Rhythm
Planning only changes logical state. Hardware moves only through `execute_segment_to_breakpoint`, `start_plan`, `resume_plan`, or explicit hardware calls.

Default real-hardware rhythm:
1. Plan one physical segment or checkpoint.
2. Inspect `plan_summary()`.
3. Execute to the segment target with `execute_segment_to_breakpoint(frame_number=null)`.
4. If the result is `wait_mode="inline"`, use its `wait_status` directly. If it starts a background wait, call `execution_wait_status(wait_seconds=<recommended_wait_seconds>)` once and let that timer return.
5. Verify or inspect, then plan the next segment.

Rules:
- For a clean new matrix protocol, benchmark, or user-requested reset, do not delete droplets one by one and continue from the old executor cursor. First stop/deactivate hardware if needed with `emergency_stop(deactivate_electrodes=true)`, then call `clear_droplet_state(reset_executor=true)`. Confirm `plan.frame_count=0`, no active droplets, and executor `current_frame=0,total_frames=0` before creating the first new droplet. This prevents new plan frames from being appended after an already executed previous run.
- For real hardware, dry electrode-only primitive tests, and matrix display tests, execute each planned physical segment before retargeting or planning the next segment unless the user explicitly asks for offline/batch planning.
- Planned-only actions are invisible to the physical system, and batch planning prevents adaptation to physical feedback.
- Do not plan all legs of a square path and execute once. Create/activate and execute; retarget leg 1, plan, execute, inspect; repeat for remaining legs.
- Treat requested final droplet count as the experimental goal, not permission for one large SIPP move. Extract and route in small physical batches.
- For `plan_move` on real hardware, retarget and plan at most `5-10` active droplets per call. Prefer `5` when droplets are `2 x 2`, routes cross/reorder, the layout is dense, or targets are near another droplet's vital space. Execute and inspect each movement batch before assigning targets for the next batch. This limit still applies to benchmarks, display tests, and well-spaced-looking layouts. Do not override a batching warning from `update_droplet_targets`; split into executed batches instead.
- Plan only to the next visual/temperature check, injection confirmation, extraction validation, user decision, or risky transition.
- Leave `remove_duplicate_frames=false` during normal real-hardware operation. Use it only for explicit duplicate-frame debugging after inspecting the resulting plan.
- Prefer `execute_segment_to_breakpoint` for normal segment execution. It clears old breakpoints by default, adds the target breakpoint, chooses `start_plan` for a new run or `resume_plan` for a partial run, and uses `wait_mode="auto"` so short segments finish inline and long segments run as a background wait.
- Default execution frame delay is `1.0` second, and that is the correct normal operating pace. Omit `frame_delay` unless the user explicitly asks for another speed; never invent a faster or slower non-default delay.
- For background execution waits, do not make repeated immediate `execution_wait_status()` calls. Use the returned `recommended_wait_seconds`, `next_check_after_seconds`, or `recommended_status_call`; if the timer returns `running=true`, repeat one timer wait using the new recommendation.
- Use manual `add_breakpoint` plus `start_plan`/`resume_plan` plus `start_execute_until_breakpoint` only when you need non-default breakpoint handling.
- Use `resume_timeline(reason=...)` before starting a new active work block if `timeline_status()` says the logical timeline is paused and `system_loaded` is not `false`. If `system_loaded=false`, load the DropLogic system first; the timeline is intentionally off while no system exists. Use `pause_timeline(reason=...)` when the user goal is complete, when you are about to stop working, or when waiting for a human decision. This records a stopped interval in the dashboard timeline without adding plan frames or pausing hardware execution; use `pause_plan()` for real hardware execution pauses.
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
- For large coordinated moves that are still within the `5-10` droplet hardware batch limit, use `plan_move(planning_timeout=1200, background=true)`, then poll `planning_job_status()`. Dashboard agent calls may force `background=true` with a bounded timeout for safety. If a request involves more droplets, split it into executed movement batches instead of increasing the timeout and planning all droplets together.
- Do not put labels, checkpoints, notes, or other metadata in `plan_move(options=...)`. Only documented planner options belong there; unknown options are ignored by MCP and reported as `ignored_options`.
- Use `plan_reservoir_extraction(...)` for extracting one or more droplets from a reservoir.
- Use `plan_isometric_split(...)`, `plan_mix(...)`, and `plan_merge(...)` for those named operations.
- These tools only append/update the logical plan. Always inspect the tool result/`plan_summary()` before execution.
- For `plan_reservoir_extraction`, `plan_isometric_split`, `plan_mix`, and `plan_merge`, treat `ok=false`, `primitive_validation.ok=false`, `result=null`, or `planning_success=false` as a failed primitive. Do not execute it, do not continue as if it succeeded, and do not use it as completion evidence.
- If planning fails, times out, or returns `planning_success=false`, split into waypoints or smaller groups.
- `plan_move` plans every active droplet whose target differs from its current position. It does not only plan the droplets named in the most recent `update_droplet_targets` call. Before each movement batch, reset non-batch droplets to their current positions or include them deliberately in the staged move.
- `update_droplet_target(s)` validates the proposed final active-droplet layout and current-space reservations before mutating targets. Read `target_validation`: if `ok=false`, do not call `plan_move`; use `target_validation.suggested_targets` when present, or choose different targets/intermediate parking positions. Warnings such as `pending_targets_not_in_request` mean an older pending target will still move if you call `plan_move`.
- After each `plan_move`/`planning_job_status`/execution result, treat `targets_reached` as authoritative for that segment. If only droplets `2-6` are listed as reached, only that batch moved; do not claim or proceed as if droplets `7-26` reached final positions until their own batches have been retargeted, planned, executed, and reported in `targets_reached`.
- For `plan_merge`, first move non-merge droplets away from the merge target and avoid targets inside another droplet's vital space. Prefer merging into an open hub 4-8 electrodes away from nearby droplets, then execute the merge segment before any `plan_mix` or final routing. If a failed merge returns `primitive_validation.merge_target_validation`, follow it: move any `blocker_parking_suggestions` first, or retry with `suggested_target.retry_arguments` when present, falling back to `suggested_target.target` only when `retry_arguments` is absent.
- A successful `plan_merge` must return the merged droplet id. The merged-away input droplets can remain in `droplets_summary()` for history, but their `active=false` flag and absence from `plan.active_droplet_ids` means they are not planning candidates. Plan only active droplets unless the user explicitly asks to restore or correct an inactive one.
- After a failed merge/split/mix attempt, refresh `execution_status_summary(include_droplets=true, include_plan=true)` and reason from the last executed frame. Do not trust logical droplet positions from a failed, unexecuted plan; correct them only from visual/user confirmation.
- SIPP reserves active droplets' current/initial footprints while planning. Do not expect one droplet to move into another active droplet's starting footprint in the same `plan_move()` call just because that other droplet will eventually leave.
- For swaps, crossings, reordering, or any move where a target/vital space overlaps another moving droplet's current footprint, use staged moves: first retarget the blocking droplets to intermediate parking positions that free the contested starts/targets, plan and execute that segment, then retarget from those intermediate positions to the final targets in one or more later `plan_move()` calls.
- For visual crossing tests, use intermediate staging lanes or parking cells to make space first, then route through the crossing area. A successful crossing may require multiple executed move segments; do not force all crossings and final targets into one coordinated move.

## Droplets, Reservoirs, And Injection
Droplet tools:
- Use `clear_droplet_state(reset_executor=true)` to start a clean logical protocol: it clears all AdvancedDrop droplets, removes old plan frames, and resets the PlanExecutor cursor. It does not replace visual verification or physical deactivation; use `emergency_stop(deactivate_electrodes=true)` first when electrodes must be turned off.
- Use `create_droplet(droplet_id=1, origin=[row, col], target=[row, col], width=1, height=1)` for one droplet.
- Use `add_droplets(droplets=[...])` for batches. Each entry needs `id`/`droplet_id` and `origin`; include `target` unless explicitly optional.
- Valid batch entry: `{"id": 1, "origin": [42, 1], "target": [30, 30], "width": 1, "height": 1}`.
- After `add_droplets`, verify `created_count == requested_count` and `droplets.total_droplets` increased; otherwise stop and report the error.
- Retarget with `update_droplet_targets(targets=[{"id": 1, "target": [30, 30]}])` or `update_droplet_targets(targets={"1": [30, 30]})`; do not delete/recreate just to retarget.
- Choose all movement targets so final footprints and vital spaces do not overlap any active droplet's current or final footprint. If the final target for a droplet uses space currently occupied or protected by another active droplet, first move the blocker to an intermediate parking position, execute that segment, then retarget to the final layout.
- Keep movement batch target grids conservatively away from cartridge edges. Passing target validation only proves the final footprint is legal; SIPP can still fail when a target is tight against an edge or leaves poor approach corridors. For `2 x 2` droplets, keep several electrodes of margin beyond vital space, and use nearer/intermediate targets after one failed edge-side target attempt.
- Use `update_droplet_position` only after visual/user confirmation that the physical droplet is at that coordinate.
- `update_droplet_targets` returns compact count/id summary by default. Set `include_summary=true` only when the full droplet summary is needed.
- `delete_droplet(droplet_id=...)` removes the logical droplet and, by default, clears that droplet's electrodes in the next plan frame (`persist_electrodes=false`). Use `persist_electrodes=true` only for explicit supervised debugging where the physical/electrical footprint must remain active; otherwise it leaves ghost electrodes that can confuse later planning and visual interpretation.
- For droplets larger than `1 x 1`, default `vital_space=2` and at least `2` electrodes between extraction targets/reservoir exits unless specified otherwise.
- SIPP gets expensive with many droplets, dense routes, narrow corridors, overlapping vital spaces, or crossing/reordering. For hardware, keep each movement planning batch to `5-10` droplets maximum and prefer `5` in crowded or crossing layouts.
- Check that intended final positions and vital spaces do not intersect current droplet positions. If they do, do not ask SIPP to solve the swap in one call; move the blockers to intermediate parking positions first.

Reservoir and injection rules:
- Default cartridge family: Acxel 16k.
- User injections enter from lateral input holes; hole definitions belong in cartridge JSON.
- Manual injection/loading position is `config.json.presets.stage.manual_injection.position`; use `move_stage(preset="manual_injection")` instead of hardcoded stage coordinates.
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
2. Plan the next extraction batch or single-droplet extraction only. Do not append several extraction batches before executing and inspecting the current batch.
3. Inspect `plan_summary()`; if `planning_success=false`, do not execute. Reduce batch size, use a larger reservoir, change direction, or adjust/increase the stagger/spacing. On BoxMini hardware, do not make a failed `2 x 2` linear extraction fit by reducing row/column spacing below `4`.
4. Execute the segment with `execute_segment_to_breakpoint(frame_number=null)`.
5. If execution starts a background wait, call `execution_wait_status(wait_seconds=<recommended_wait_seconds>)` and repeat only if the timer returns `running=true`.
6. Verify extracted droplets before routing unless the user explicitly requested unattended execution.

Extraction parameters:
- For linear extraction of `2 x 2` or larger droplets, pass `linear_drop_shape=[2, 2]`, `linear_space_per_row>=4`, `linear_space_per_col>=4`, `linear_vital_space=2`, `linear_post_separation_steps=3`, and a staggered `linear_offset` unless the user explicitly asks for denser packing. Linear extraction is much more reliable when the extraction grid uses well-spaced rows and columns; do not pack a dense one-electrode/two-electrode chain and then declare extraction failure from vision alone.
- In linear extraction, `linear_space_per_row` and `linear_space_per_col` are clear side-to-side gaps between droplets, not the pitch from one droplet origin to the next. The placement pitch is droplet size plus gap. Required minimum clear gap is `2 * droplet height` for rows and `2 * droplet width` for columns, so `2 x 2` droplets need row and column gaps of at least `4`.
- `linear_post_separation_steps` makes the reservoir keep sweeping a few electrodes after the last droplet has severed. Keep the BoxMini default at `3` so the reservoir tail clears the extracted droplets before inspection or the next extraction batch.
- Use staggered linear extraction geometry for multi-droplet `2 x 2` batches. Good default: `linear_offset=2` with `linear_space_per_row>=4` and `linear_space_per_col>=4`, if the stagger stays inside the reservoir sweep strip. With `linear_direction=[0, 1]` or `[0, -1]`, `linear_offset` shifts the starting row on alternating columns. With `linear_direction=[1, 0]` or `[-1, 0]`, it shifts the starting column on alternating rows. This creates an even/odd column or row stagger instead of perfectly aligned extracted droplets.
- Linear extraction droplets only need to fit inside the moving reservoir sweep, not inside the initial reservoir footprint along the sweep direction. It is valid for later columns/rows to be created once the reservoir reaches them, and the last row/column does not need to be exhausted before planning the next one. Large `linear_offset` values that move droplets outside the orthogonal sweep strip should still fail. For compact reservoirs, reduce droplet count per extraction batch, use a larger reservoir, extract in multiple smaller batches, or choose a different direction/mode. Do not reduce `linear_space_per_row` or `linear_space_per_col` below `4` on BoxMini hardware just to make a batch fit, unless the user explicitly asks for a dense/simulation-only layout.
- For `split_mode="1to2"` or `split_mode="1to3"`, `steps` is one two-integer offset `[row_offset, col_offset]`, not a list of step vectors. Example: `steps=[0, 8]` extracts east/right of the reservoir; `steps=[8, 0]` extracts south/down. Use `split_size=[2, 2]` for a `2 x 2` 1-to-3 central droplet and tune `separation_steps` for harder liquids.
- `1to3` extracts one droplet per call. If linear extraction repeatedly fails, plan one `1to3` extraction, execute, verify, then repeat from the updated reservoir state instead of asking `1to3` for many droplets at once.

Validation:
- If execution used `whole_chip_camera`, do not run microscope/YOLO verification during movement. Pause, switch deliberately to `follow_droplets`/microscope, then verify.
- Otherwise, verify extracted droplets with `verify_droplets` at the current executor frame. Always save verification frames by passing `save_frames_path` to a run-specific debug folder; in cockpit/dashboard mode this path may be added automatically, but still check `frame_files` in the result before trusting a failed check.
- Use up to `3` short checks for a newly extracted droplet before declaring it missing. If `frame_files` are missing/null or the user says they can see electrodes/droplets, treat the result as inconclusive and inspect saved frames or ask for confirmation instead of deleting logical droplets.
- If found, mark the droplet valid and route it in a later segment.
- If missing, delete that logical droplet or execute an explicit planned cleanup if the protocol defines one, then retry extraction.
- If the same extraction fails more than `3` times, stop and ask unless user requested unattended full-protocol run. For unattended runs, log/return force-accepted/skipped and continue by protocol.
- Do not route unverified droplets unless protocol/user allows force-accepting failed checks.

## Execution View Modes And Diagnostics
- Default execution view for a fresh run is `follow_droplets`. If a fixed view such as `whole_chip_camera` is already configured, omitting `execution_view_mode` preserves that current view; do not rely on omission to switch views.
- Use `execute_segment_to_breakpoint(execution_view_mode="whole_chip_camera", verify_positions=false)` for fixed whole-chip execution. This applies `config.json.presets.imaging.whole_chip_camera`, switches streamer to camera, moves to fixed overview stage position, and disables droplet-follow tracking.
- Use `execute_segment_to_breakpoint(execution_view_mode="follow_droplets")` for normal microscope-follow execution.
- Use `set_execution_view_mode(mode="follow_droplets")` before microscope droplet checks, visual correction, or model verification.
- `whole_chip_camera` and `follow_droplets` are mutually exclusive. Do not switch streamer/stage while a segment is running.
- In `whole_chip_camera` or fixed-stage execution, keep `verify_positions=false`. Executor verification is not passive: it moves stage, changes light, and calls microscope droplet verification.
- If the user asks for whole cartridge/chip visualization, call `set_execution_view_mode(mode="whole_chip_camera")` or execute with `execution_view_mode="whole_chip_camera", verify_positions=false`; do not compute a stage position from electrode calibration or camera/microscope geometry.
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

## Temperature
- Use `temperature_hold(target_c=..., hold_seconds=...)` for short single-setpoint waits.
- Use the high-level temperature tools for setting, holding, cooling down, and curves. Do not call `module_call(module="temperature", method="set_temperature", ...)` unless the user explicitly asks for low-level debugging; its Python argument names are not the MCP interface.
- Temperature holds and melting-curve steps default to `tolerance_c=0.2`: the tool sets the target, waits until the measured temperature is within 0.2 C of the target, then starts counting `hold_seconds`. Only override this when the user explicitly asks for a different stability window.
- For temperature-only long ramps, per-degree waits, `require_settle=true`, or multi-minute holds with no per-step imaging, use `start_temperature_routine(steps=[...], require_settle=true)` and poll `temperature_routine_status()`.
- Do not use `start_temperature_routine` for melting curves or time series that require photos at each step; that routine only controls temperature and does not trigger camera captures. Use `start_melting_curve_capture` instead.
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
