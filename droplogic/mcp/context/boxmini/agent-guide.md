# BoxMini Agent Guide

This is the pinned BoxMini operating guide entrypoint. It should be sent on every agent turn as authoritative context, outside the compactable event log. Detailed rules live in `agent-guide/*.md` and may be attached for one turn by the dashboard guide selector or read explicitly with `read_context_file(path)`.

## Guide Expansion Protocol
- Treat this file as the stable operating contract and index.
- Before hardware work, refresh detailed knowledge by selecting or reading the relevant `agent-guide/*.md` files.
- Detailed guide expansions are turn-scoped: do not assume a section expanded in a previous turn is still present.
- If a tool result shows `ok=false`, `planning_success=false`, `primitive_validation.ok=false`, `target_validation.ok=false`, `large_move_batch`, `pending_targets_not_in_request`, `suggested_targets`, `targets_reached`, execution-view trouble, imaging trouble, or any safety/fault condition, expand the relevant guide files before continuing.
- If the user asks for routing, extraction, merging, splitting, mixing, whole-cartridge visualization, matrix visualization, imaging, temperature, calibration, or recovery from a failed plan, expand the matching guide files before acting.
- If no expanded guide section covers the next risky action, call `read_context_file(path)` for the relevant shard.

## Core Operating Rules
- Control BoxMini through top-level MCP tools. Avoid generic AdvancedDrop/module/raw calls unless explicitly debugging.
- Start with `runtime_status()`; call `load_system(system="boxmini")` only when needed. Do not reset the matrix unless the user clearly asks.
- Compact `runtime_status()` includes `system.queue_summary`: the aggregate unfinished-command count and CRITICAL/HIGH/MEDIUM/LOW worker liveness, pending counts, and configured intervals. Use full detail when command-error diagnostics are needed.
- Before hardware actions, use a fresh `execution_status_summary()` or a targeted status tool unless a recent tool result already proves the needed state.
- Do not claim physical success unless execution/status/vision/user feedback confirms it.
- Use logical matrix coordinates `[row, column]`. Do not mix electrode, stage, and camera coordinates.
- Use presets for stage and imaging. Do not invent absolute stage coordinates, exposure/gain/light values, or calibration math.
- Normal executor operation is microscope brightfield with `follow_droplets`. Do not switch to `whole_chip_camera` unless the user explicitly asks for whole-cartridge/whole-chip visualization or the protocol clearly needs a fixed-view segment.

## Hardware And Coordinates
- System: `boxmini`; matrix: Acxel 16k, `128 x 128` logical electrodes.
- Core modules: `electrode_matrix`, `xy_stage`, `camera`, `microscope`, `light`, `temperature`, `capacitive_feedback`.
- Use logical matrix coordinates as `[row, column]`; `(0, 0)` is logical top-left.
- Camera and microscope views are rotated relative to logical matrix. Current working assumption: cartridge appears 90 degrees clockwise in camera view.
- Never treat electrode coordinates, stage coordinates, and camera pixels as interchangeable. Use configured presets and calibration helpers; do not invent absolute stage coordinates.

## Cockpit And Dashboard Mode
- The browser is the visual surface. Do not raise OpenCV windows unless asked.
- Use `visualizer_status` and `visualizer_frame` for what the dashboard sees.
- Image bytes are attached once; after inspection rely on artifact metadata and written observations.
- Tool events marked `called_by_user` or `tool_invocation_origin="dashboard_user"` are user actions.
- If runtime health fails, stop hardware execution and inspect health before continuing.

## Planning And Execution Contract
- Planning changes logical state only. Hardware moves through `execute_segment_to_breakpoint`, `start_plan`/`resume_plan`, or explicit hardware tools.
- Default rhythm: plan one physical segment, inspect `plan_summary()`, execute to breakpoint, wait using recommended `wait_seconds`, verify/inspect, then plan the next segment.
- Prefer `execute_segment_to_breakpoint`. If it starts a background wait, call `execution_wait_status(wait_seconds=<recommended>)` once; repeat only with the returned recommendation.
- If background planning is running, call `planning_job_status()` and wait according to its returned `recommended_wait_seconds`; do not poll status every few seconds.
- Do not plan all legs of multi-step physical work at once. Plan to the next check, injection confirmation, extraction validation, user decision, or risky transition.
- For a clean new protocol, use `emergency_stop(deactivate_electrodes=true)` when needed, then `clear_droplet_state(reset_executor=true)`, and confirm no active old plan/droplets.
- Do not use `start_plan` to continue a partial run. Treat restart-from-frame-0 warnings as safety stops.
- If `planning_success=false`, `primitive_validation.ok=false`, `result=null`, or `ok=false`, do not execute that primitive.

## Droplet And Routing Contract
- Use `create_droplet`/`add_droplets`, `update_droplet_targets`, `plan_move`, `plan_reservoir_extraction`, `plan_isometric_split`, `plan_mix`, and `plan_merge`.
- Retarget droplets instead of deleting/recreating them.
- For real hardware, keep `plan_move` batches to `5-10` droplets. Prefer `5` when droplets have multi-electrode footprints, large `vital_space`, dense layouts, crossings, reordering, or targets near another droplet's vital space.
- `plan_move` moves every active droplet whose target differs from current position, not only recently retargeted droplets.
- Read `update_droplet_targets` `target_validation` every time. If `ok=false`, do not call `plan_move`; use `target_validation.suggested_targets` when present or choose staged parking/intermediate targets.
- Treat warnings such as `large_move_batch` and `pending_targets_not_in_request` as operational blockers for hardware unless you intentionally split/reset targets first.
- For swaps/crossings/overlaps, use staged parking moves. Do not expect SIPP to move one droplet into another active start footprint in one call.
- After each segment, trust `targets_reached` only for the droplets reported in that segment.
- Except for injection/loading regions and explicit waste/trash routing, when safely possible, place outer droplets within about `5` electrodes of the chip sides while avoiding the exact border electrodes.

## Reservoir, Injection, And Extraction Contract
- Injection holes and matrix geometry come from `cartridge.default.json`.
- Before asking the user to inject, create/activate the reservoir on the real matrix, execute activation, verify/inspect, then `move_stage(preset="manual_injection")`.
- Wait for user confirmation after manual injection.
- Before extraction, relocate an injected reservoir `5-10` electrodes from the edge, execute, and verify.
- Size reservoirs for consumed area plus at least `20` electrodes. Consumed area is approximately `count * width * height`; add extra area for residual liquid, edge loss, imperfect splitting, and dead volume.
- Use `plan_reservoir_extraction`. Default `split_mode="linear"` for fast batches; use `1to2`/`1to3` for validation or hard liquids.
- Plan only the next extraction batch, inspect, execute, then verify before routing unless the user explicitly asks to skip verification or sets a maximum number of verification steps.
- For linear extraction, set `linear_drop_shape` to the intended droplet footprint, set `linear_vital_space` to the droplet vital space, keep clear row/column gaps scaled to the droplet dimensions, use `linear_post_separation_steps=3`, and stagger with `linear_offset` when possible.
- `2 x 2` is the hardest-tested BoxMini extraction footprint. Smaller `1 x 1` extractions can be harder because the droplet has less volume/contact margin and may be less stable during separation.
- Do not reduce row/column clear spacing below the droplet-scaled safe minimum on BoxMini hardware just to make a batch fit.

## Views, Imaging, And Temperature Contract
- Normal execution should stay in `follow_droplets`/microscope brightfield. If the current executor view might have been changed earlier, explicitly restore `follow_droplets` before normal droplet execution instead of assuming omission will switch it back.
- Use `set_execution_view_mode(mode="whole_chip_camera")` or `execute_segment_to_breakpoint(execution_view_mode="whole_chip_camera", verify_positions=false)` only for user-requested whole-cartridge overview or another clearly fixed-view segment.
- `whole_chip_camera` and `follow_droplets` are mutually exclusive during execution.
- In `whole_chip_camera` fixed execution, keep `verify_positions=false`; verification moves the stage and changes imaging.
- Use `capture_droplet_images` for repeated droplet imaging and `start_melting_curve_capture` for temperature curves with photos at each step.
- Use `temperature_hold` for short single setpoints and `start_temperature_routine` only for temperature-only routines with no per-step imaging.

## Fault Handling Contract
- Use `emergency_stop` for urgent stop/deactivation.
- A BoxMini load is successful only after every core module, including the XY stage, initializes. A failed load releases the partial singleton and workers; report the error and do not retry real hardware automatically.
- Do not continue after visual/vision mismatch without correction or user confirmation.
- Do not automatically restart/reinitialize real hardware after a fault.
- If MCP restarts and state is lost, reload only after physical state is safe, then reconstruct logical droplets from current physical/visual state.

## Detailed Guide Files
- `agent-guide/01-mission-tool-boundaries.md`: MCP tool boundaries and unsafe/raw-tool limits.
- `agent-guide/02-hardware-coordinates.md`: matrix, stage, camera, and coordinate assumptions.
- `agent-guide/03-startup-state-large-values.md`: startup rhythm, state refresh, and large-value handling.
- `agent-guide/04-calibration-geometry.md`: calibration and geometry helpers.
- `agent-guide/05-visualizers-cockpit-stage.md`: dashboard visualizers, streamer, matrix view, and stage presets.
- `agent-guide/06-planning-execution-rhythm.md`: segment planning, execution rhythm, target validation, failed planning, and staged moves.
- `agent-guide/07-droplets-reservoirs-injection.md`: droplet creation/retargeting, reservoirs, injection, movement batch sizing, and overlap rules.
- `agent-guide/08-reservoir-extraction.md`: reservoir extraction modes, parameters, batch workflow, and troubleshooting.
- `agent-guide/09-execution-view-modes-diagnostics.md`: `whole_chip_camera`, `follow_droplets`, execution diagnostics, and executor/status checks.
- `agent-guide/10-imaging-light-vision.md`: imaging, capture tools, lights, YOLO/vision, and saved-image discipline.
- `agent-guide/11-temperature.md`: temperature tools, holds, routines, and thermal waits.
- `agent-guide/12-faults-safety-stops.md`: safety stops, fault handling, and recovery boundaries.
