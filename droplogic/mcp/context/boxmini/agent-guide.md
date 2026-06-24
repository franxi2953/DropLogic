# BoxMini Agent Quick Guide

## Role
Control BoxMini through DropLogic MCP. Translate the user's protocol into DropLogic actions, execute only when allowed, and use visual or model feedback to confirm that the physical run matches the plan.

Prefer `AdvancedDrop`, `PlanExecutor`, runtime inspection, visualizer tools, and vision tools before direct module calls. Use raw electrode-matrix operations only for explicitly supervised debugging.

Tool boundaries:
- `load_system`, `close_system`, `restart_system`, `runtime_status`, `capabilities`, `state_summary`, visualizer tools, state tools, and executor tools are top-level MCP tools.
- `advanced_drop_call` is only for whitelisted `AdvancedDrop` planning methods such as `move`, `reservoir_extraction`, `mix`, `merge`, and `isometric_split`.
- Use `start_advanced_drop_call` for long AdvancedDrop/SIPP planning calls; poll `advanced_drop_job_status` until `running=false`.
- Never call `advanced_drop_call(method="load_system")`; start BoxMini with `load_system(system="boxmini")`.

## Machine
- System: `boxmini`
- Matrix: Acxel 16k cartridge, 128 rows x 128 columns
- Core modules: `electrode_matrix`, `xy_stage`, `camera`, `microscope`, `light`, `temperature`, `capacitive_feedback`
- `electrode_matrix` receives voltage and frame updates during plan execution.
- `xy_stage` moves the cartridge/imaging position. Use configured positions; do not invent absolute stage coordinates.
- `camera` and `microscope` provide physical feedback for inspection, droplet verification, condensate detection, and saved frames.
- `light` controls coaxial/ring illumination. Coaxial light is important for imaging and fluorescence; avoid leaving it high.
- `temperature` reads/controls temperature when available. Treat temperature changes as real hardware actions.

## Coordinates
- Use logical matrix coordinates as `[row, column]` unless a tool says otherwise.
- Logical matrix size is `128 x 128`; `(0, 0)` is logical top-left.
- The physical cartridge/camera view is rotated relative to the logical matrix. Current working assumption: the cartridge appears 90 degrees clockwise in the camera view.
- Use the matrix visualizer for logical plan inspection and the streamer/camera view for physical feedback. Account for rotation before correcting droplet positions.
- Never treat electrode coordinates, stage coordinates, and camera pixels as interchangeable.

## Startup And State
- First call `runtime_status`. If BoxMini is needed and no system is loaded, call `load_system(system="boxmini")`.
- `config.json` is configuration, calibration, defaults, and presets. It is not a live-state log.
- The last processed `electrode_matrix.matrix` is persisted separately in a local runtime-state sidecar such as `config.runtime-state.json`, not in `config.json`.
- By default BoxMini restores that last active matrix when hardware initializes. Do not assume startup means all electrodes are off.
- Runtime values such as `temperature.current`, `xy_stage.position`, camera/microscope settings, and light levels are session state and are not restored from the runtime-state sidecar.
- Use `reset_matrix=true` only when the user clearly wants an all-off startup; this also replaces the persisted matrix with zero/off after the reset command is processed.
- Use `state_summary()` for broad inspection; it summarizes large values such as the 128 x 128 matrix.
- Use `read_state(path="...")` for exact values. Useful paths: `temperature`, `temperature.current`, `xy_stage.position`, `xy_stage.position.Y`, `light_settings`, `microscope_settings`, `camera_settings`, `electrode_matrix.voltage`, `electrode_matrix.matrix`, and `calibration`.
- Avoid `read_state()` with no path unless the user really needs the full raw state.
- State reads are cached snapshots. For fresh measurements, call the relevant module method, such as `module_call(module="temperature", method="get_temperature")`, then read state if needed.

## Visualizers
- For real BoxMini runs, prepare both visualizers early unless the user says not to. `load_system(system="boxmini")` should auto-prepare them without forcing OS focus; if they are not visible, call `visualizer_status`, then `bring_visualizer_to_front("streamer")` or `bring_visualizer_to_front("matrix")`.
- The matrix visualizer shows the logical electrode plan and PlanExecutor progression.
- The streamer should use the `microscope` feed by default, with electrode overlay enabled and coordinates disabled unless debugging requires coordinates.
- Use `set_streamer_source(source="microscope")` for droplet/matrix work and `set_streamer_source(source="camera")` for wide whole-chip camera view.
- Use `visualizer_frame(visualizer="streamer", frame_source="processed")` for the annotated human-like view and `frame_source="raw"` for unannotated microscope frames when available.
- If no live frame appears after warmup, pause hardware work and ask the user.
- If a protocol starts `PlanExecutor` with `enable_visualizers=true`, still prepare the streamer first so it uses the expected source and overlay settings.
- Stop visualizers with `stop_visualizer("streamer")` and `stop_visualizer("matrix")` when finished or before closing; `close_system` should also release them.

## Calibration
- `config.json` is the source of truth for measured machine calibration: pixel calibration, chip origin, electrode-to-stage mapping, backlash, and named presets.
- Cartridge JSON should hold cartridge-specific geometry such as input holes or blocked regions, not measured machine calibration.
- Use `droplogic.utils.hardware_utils` helpers instead of hand-written conversion math:
  - `electrode_to_stage(row, col)`
  - `stage_to_electrode((x, y))` and `stage_to_electrode_float((x, y))`
  - `pixels_to_microns(...)`, `microns_to_pixels(...)`, `get_pixel_calibration_info(...)`
  - `pixels_to_volume_nl(pixel_area, height_microns=50)` and `area_pixels_to_radius_microns(pixel_area)`
- For image distances, use active pixel calibration from `config.json`.
- For planned droplet distances, compare electrode coordinates. If physical displacement is requested, convert both electrode positions to stage positions and state that the result depends on active calibration.
- For image-derived volume estimates, use the DMLite gap assumption `height_microns=50`: `pixel_area * microns_per_pixel^2 * 50 / 1_000_000` nL.

## Cartridge And Injection
- Default cartridge family: Acxel 16k.
- User injections enter from lateral input holes; hole definitions belong in cartridge JSON.
- Manual injection/loading position is `config.json.presets.stage.manual_injection.position`; current BoxMini preset is `Y=47000`.
- Unless user or cartridge JSON defines blocked/no-go regions, assume the matrix is usable.
- Reservoirs for injected liquid should be near the relevant border but not on the border. Leave at least one row/column margin.
- After moving to the injection/loading position, wait for user confirmation that injection is complete; this may take several minutes.
- After confirmation, return to the previous Y position unless the active protocol profile defines a named operating/imaging position.
- Keep experiment-specific stage or imaging overrides in a protocol profile.
- Users can adapt this context by supplying their own `--context-dir` override directory.

## Light Handling
Cartridges can leak or degrade under strong light. Use low coaxial light and longer exposure while moving or monitoring droplets. Higher illumination may be acceptable for static fluorescence imaging, but restore conservative settings as soon as possible.

Rules:
- Use conservative illumination during movement.
- Avoid leaving high coaxial light on after fluorescence capture.
- Restore previous microscope/light settings after special imaging steps when possible.

## Default Workflow
1. Call `runtime_status`.
2. Load BoxMini with `load_system(system="boxmini")` only if needed.
3. Call `capabilities` and `state_summary`.
4. Read `agent-guide.md`, the active cartridge JSON, and the active protocol profile with `read_context_file`.
5. Prepare visualizers for real hardware.
6. Check input holes, usable/no-go regions, imaging notes, and protocol constraints.
7. Create droplets/reservoirs only in valid regions.
8. Plan only the next physical action or checkpoint segment unless the user clearly asks for batch/offline planning.
9. Inspect `plan_summary`, add a breakpoint at the segment target, execute with `start_plan`/`resume_plan`, then wait using `start_execute_until_breakpoint` plus `execution_wait_status` polling.
10. Before real execution, use `visualizer_frame` and/or `verify_droplets` at key physical transitions.
11. If physical feedback disagrees with the plan, stop, correct logical droplet position, or ask the user.

NOTE: By default, execute every real-hardware action immediately after planning that segment. The user cannot see a planned-only action in the visualizers, and you cannot adapt to physical results if you plan everything from the beginning and execute it from start to end. Prefer plan -> breakpoint -> execute -> verify -> next plan. A request for many final droplets or targets is not permission to plan one large coordinated move unless the user clearly asks for batch/offline planning.

## Droplets And Planning
- Planning only updates the logical plan. Hardware (including the active matrix) moves only through `start_plan`, `resume_plan`, or explicit hardware calls.
- Default real-hardware rhythm is: plan one physical segment, execute that segment, verify/checkpoint, then plan the next segment. Keep planning and execution at roughly the same pace.
- Do not accumulate multiple planned physical actions without execution. Batch/offline planning is allowed only when the user clearly asks for it, for example "plan the whole protocol first" or "make an offline batch plan".
- When the user asks for N droplets, treat N as the final experimental goal, not as an instruction to solve one N-droplet SIPP move. Extract and route in small physical batches by default, executing and verifying each batch before planning the next.
- If the next decision depends on visual feedback, temperature, injection state, droplet success, or user confirmation, plan only up to that decision point, execute to a breakpoint, verify, and then continue planning.
- Use `create_droplet(droplet_id=1, origin=[row, col], target=[row, col], width=1, height=1)` for one droplet.
- Use `add_droplets(droplets=[...])` for batches. Each entry must include `id` or `droplet_id`, `origin`, and optionally `target`, `width`, `height`, `shape`, `priority`, and `vital_space`.
- Valid batch entry: `{"id": 1, "origin": [42, 1], "target": [30, 30], "width": 1, "height": 1}`.
- After `add_droplets`, verify `created_count == requested_count` and `droplets.total_droplets` increased. If not, stop and report the returned error.
- Reservoir sizing tip: when the user asks for a reservoir and the intended number/size of extracted droplets is reasonably clear, size the reservoir for the electrodes that will be consumed plus at least `20` extra electrodes unless the user says otherwise. For example, extracting `N` one-electrode droplets should use a reservoir area of at least `N + 20` electrodes.
- For larger droplets, estimate consumed area as `count * width * height`, then add at least `20` electrodes of excess reservoir area. Include this margin for residual liquid, edge loss, imperfect splitting, and dead volume near the reservoir body.
- For droplets larger than `1 x 1`, use `vital_space=2` by default and keep at least `2` electrodes of separation between extraction targets/reservoir exits unless the user gives another spacing.
- For many target changes, use `update_droplet_targets(targets=[{"id": 1, "target": [30, 30]}, ...])` or `update_droplet_targets(targets={"1": [30, 30], "2": [31, 30]})`. Do not delete/recreate droplets just to change targets.
- `update_droplet_targets` returns a compact count/id summary by default. Set `include_summary=true` only when a full droplet summary is needed.
- SIPP path planning gets expensive with many droplets, dense routes, narrow corridors, or overlapping vital spaces. Prefer smaller batches when possible, especially more than about 5 active droplets or any complex crossing/reordering task.
- Use `advanced_drop_call` only for short planning calls expected to finish well inside the client request timeout. Blocking `move` calls are guarded for small moves only; do not bypass this on real hardware.
- Planning tool responses are compact by default. Use summaries, visualizer frames, and executor status; do not request full frame matrices unless doing explicit local debugging.
- If a larger coordinated move is necessary, use `start_advanced_drop_call(method="move", arguments={"planning_timeout": 1200})`, then poll `advanced_drop_job_status()` until `running=false`. This keeps the MCP request short while SIPP works in the background.
- `advanced_drop_job_status()` returns a compact result and `plan_summary`, not the full frame matrices. Use `plan_summary`, `visualizer_frame`, and execution tools to inspect the plan.
- If the background job fails, times out internally, or returns `planning_success=false`, split the move into intermediate waypoints or smaller droplet groups.
- If a long blocking call times out and the next tool says `No system loaded`, assume the MCP process was restarted by the client. Reload BoxMini only after confirming the physical state is safe, then reconstruct logical droplets from physical/visual state.
- `cancel_advanced_drop_job()` only requests cooperative cancellation. CPU-bound SIPP may keep running until the current planning call returns.
- If a step needs verification, plan and execute that segment to a breakpoint, verify it, then continue planning.

## Execution
- Default real-hardware cadence is `1.0` second between frames unless the active protocol sets another delay.
- A plan that has not been passed to the executor has not happened physically. After each planned real-hardware segment, execute it before assuming any droplet moved.
- `start_plan` starts the current plan from frame `0`. Do not call it to continue a paused or partially executed run.
- To continue from the current frame, use `resume_plan` plus background breakpoint polling. If `start_plan` reports that it would restart from frame `0`, treat that as a safety stop and resume instead.
- For MCP sessions, the default wait pattern is non-blocking: `start_execute_until_breakpoint(...)`, then poll `execution_wait_status()` until `running=false`.
- Do not use blocking `execute_until_breakpoint` for real hardware segments that may take more than a few seconds. Treat it as local-script/short-wait only, because client request timeouts can restart the MCP process while hardware keeps its last electrode state.
- `cancel_execution_wait()` cancels only the MCP wait job; it does not pause or stop physical execution. Use `pause_plan()` or `stop_plan()` for the hardware executor.
- Only use `start_plan(restart_from_beginning=true)` when the user explicitly wants to replay the plan from the beginning.
- Default execution view mode is `follow_droplets`: PlanExecutor may move the XY stage to keep active droplets under microscope view.
- Use `set_execution_view_mode(mode="whole_chip_camera")` or `start_plan(execution_view_mode="whole_chip_camera")` when the user wants whole-chip camera overview during execution. This applies `config.json.presets.imaging.whole_chip_camera`, switches streamer to camera, moves to the fixed overview stage position, and disables droplet-follow tracking.
- Use `set_execution_view_mode(mode="follow_droplets")` or `start_plan(execution_view_mode="follow_droplets")` before microscope droplet checks, visual correction, or model verification.
- `whole_chip_camera` and `follow_droplets` are mutually exclusive execution modes. Do not switch the streamer/stage back and forth while a segment is running. Pause at a breakpoint before microscope checks, then switch mode deliberately.
- In `whole_chip_camera` or fixed-stage execution, call `start_plan(..., verify_positions=false)`. Executor verification is not passive: it calls microscope droplet verification, changes light to brightfield settings, and moves the stage to each droplet. Verify only after pausing at a breakpoint and deliberately switching to a microscope/follow mode.
- For `whole_chip_camera` execution, let `start_plan(..., execution_view_mode="whole_chip_camera", prepare_execution_view=true)` prepare and verify the fixed view once. Do not separately request droplet-follow tracking or extra executor visualizer startup for the same segment.
- `start_plan` waits for the requested execution view/stage position before execution. If it returns `started=false` with `reason="execution_view_not_ready"`, do not restart or reinitialize hardware; inspect the returned `execution_view_ready`/`execution_view`, wait or correct the view, then call `start_plan` again.
- In `whole_chip_camera`, execution should not move the XY stage frame-by-frame and should not change the camera/light preset. If frames take far longer than `frame_delay`, the view goes black, the stage moves, or light changes, pause/stop and inspect diagnostics; do not declare the slow pace normal.
- If the stage moves but the matrix visualizer or physical matrix does not update, stop or pause immediately. Inspect `executor_status`, `runtime_status` queue state, `state_summary(path="electrode_matrix.matrix")`, and `visualizer_status` before continuing.
- Empty hardware queues only mean there are no pending commands; they do not prove that the last command succeeded. If execution is unexpectedly slow or the active matrix is not changing, inspect `executor_status.last_frame`, `runtime_status.system.queues.*.last_command_error`, and the logs before calling the pace normal.
- Do not verify every frame. Use visual/model feedback after injection/reservoir setup, extraction batches, split/merge operations, recovery moves, and before long unattended imaging.
- Droplet visual checks are reliable only for droplets up to `2 x 2` electrodes. For larger reservoirs or irregular shapes, use human inspection, saved frames, or protocol-specific checks.
- For slow/risky moves, prefer breakpoints and explicit confirmation over unchecked execution.

## Breakpoint Pattern
Use this rhythm for capillary-velocity and other inspect-between-segments protocols:
- Add a breakpoint at the target frame, often `len(plan.frames) - 1`.
- Start the executor once at the beginning of a run. After that, resume when paused/idle and frames remain.
- Start a background wait with `start_execute_until_breakpoint()` immediately after `start_plan()`/`resume_plan()`.
- Poll `execution_wait_status()` in short calls; proceed only when `running=false` and the returned `executor_status` shows `breakpoint_reached=true` or `current_frame >= target_frame`.
- Canonical MCP sequence: `add_breakpoint(target_frame)` -> `start_plan(...)` or `resume_plan()` -> `start_execute_until_breakpoint()` -> poll `execution_wait_status()` -> verify/inspect -> `clear_breakpoints()`.
- Keep the executor paused while moving the microscope, inspecting frames, verifying droplets, or waiting for user confirmation.
- Clear breakpoints and resume after checks; do not call `start_plan` again unless intentionally replaying from frame `0`.
- Use blocking wait helpers only for local scripts or very short waits. In MCP sessions, background wait plus polling avoids client request timeouts and server restarts.
- If a restored/edited plan leaves `current_frame` beyond the last frame, clamp it before resuming.
- Do not use `is_executing` alone to decide whether it is safe to inspect or resume.

## Imaging Defaults
Use these defaults unless user, protocol profile, or cartridge context says otherwise.

Manual injection monitoring:
- Channel: `Brightfield`
- Auto exposure: `False`
- Exposure: `3000` us
- Coaxial light: `5`
- Ring light: `0`
- Prefer state updates or `module_call(module="microscope", method="set_parameter", arguments={"param_type":"float_value","node_name":"ExposureTime","node_value":3000})`. If `set_exposure` fails on the live object, do not retry blindly.

Brightfield droplet verification:
- Channel: `Brightfield`
- Auto exposure: `False`
- Exposure: `60000` us
- Gain: `12`
- Coaxial light: `4`
- Ring light: `0`

Whole-chip camera overview:
- Use only for whole-cartridge/chip viewing, not droplet verification.
- Source of truth: `config.json.presets.imaging.whole_chip_camera`
- Current preset: `X=84480`, `Y=5029`, `Z=4202`
- Streamer source: `camera`
- Camera auto exposure: `False`; exposure: `60000` us; gain: `0`
- Coaxial light: `0`; ring light: `20`
- Return to `set_streamer_source(source="microscope")` before microscope droplet checks or vision model calls.

Condensate detection for IVT RNA condensates:
- Use only for RNA condensates generated for IVT.
- Requires `FAM` imaging.
- Prefer `configure_microscope_imaging(channel="FAM", exposure_time=4000000, gain=12, coaxial_intensity=99, ring_intensity=0)` instead of raw microscope calls. It temporarily stops/restarts the streamer when needed.
- FAM fluorescence: exposure `4000000` us, gain `12`, coaxial `99`, ring `0`, auto exposure `False`
- Brightfield crop: exposure `60000` us, gain `12`, coaxial `4`, ring `0`
- Crop droplets: `true`; crop padding: `50`; confidence threshold: `0.25`

## Temperature
- Use `temperature_hold(target_c=..., hold_seconds=...)` only for short single-setpoint waits.
- Use blocking `temperature_sweep(...)` only for short sweeps that will finish comfortably inside the MCP/client request timeout.
- For long ramps, per-degree waits, `require_settle=true`, or multi-minute holds, use the background routine: `start_temperature_routine(steps=[...], require_settle=true)`, then poll `temperature_routine_status()` until `running=false`.
- Use `cancel_temperature_routine()` before changing temperature strategy or closing the run if a background routine is still active.
- Do not keep one MCP tool call open for a long temperature ramp. Long blocking calls can exceed the client request timeout even though the hardware is still working.
- If no background routine is available, drive long ramps manually with short calls: set one target, poll `module_call(module="temperature", method="get_temperature")`, then move to the next target.

## Feedback And Vision
Use feedback for two jobs: plan/executor health and physical confirmation.

Available paths:
- `verify_droplets`: moves to expected droplet positions and checks brightfield droplet presence. It uses verification defaults and restores previous settings when possible.
- `detect_condensates`: for IVT RNA condensates only; uses `FAM` fluorescence plus brightfield cropping when `crop_droplet=true`.
- Streamer overlays can enable droplet or condensate detection for live inspection.

Default models:
- Droplet detection: `droplogic/utils/drop_vision/models/droplets.pt`
- Condensate detection: `droplogic/utils/drop_vision/models/condensates.pt`

If feedback fails:
- Do not assume the droplet is where the planner says it is.
- If the physical droplet is visible at a different electrode coordinate, use `correct_droplet_position`.
- If the droplet is not visible or the model is uncertain, pause and ask the user or save frames for inspection.

## Never Do
- Do not use unsafe raw matrix writes unless explicitly supervised.
- Do not clear the restored matrix at startup unless the user explicitly asks for `reset_matrix=true` or an all-off start.
- Do not assume reagent identity from hole labels.
- Do not invent stage coordinates for loading, imaging, or recovery.
- Do not continue after a visual/vision mismatch without correction or confirmation.
- Do not leave high illumination on longer than needed.
- Do not restart or reinitialize real hardware automatically after a fault without user confirmation.
