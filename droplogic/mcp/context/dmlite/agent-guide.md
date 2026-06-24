# DMLite Agent Quick Guide

## Role
You control DMLite through DropLogic MCP. Translate the user's requested droplet plan into matrix actions, keep the plan coherent, and use the matrix visualizer and plan state to check execution.

Prefer `AdvancedDrop`, `PlanExecutor`, runtime inspection, matrix visualizer, and plan summaries before direct module calls. Use raw electrode-matrix operations only when a human explicitly asks for supervised debugging.

## Machine
- System: `dmlite`
- Hardware surface: electrode matrix only
- Matrix: 128 rows x 128 columns
- Core module: `electrode_matrix`

Module meaning:
- `electrode_matrix`: actuates the matrix, sets voltage, clears the chip, and receives frame updates during plan execution.

## Coordinate Rules
- Use matrix coordinates as `[row, column]` unless a specific tool says otherwise.
- The logical matrix is 128 x 128.
- `(0, 0)` is the logical top-left of the matrix.
- Use the matrix visualizer for logical plan inspection.
- There is no stage, camera, microscope, light, or temperature context in DMLite MCP.

## Calibration And Measurements
- `config.json` is the source of truth for measured matrix calibration and voltage defaults.
- Use `electrode_to_stage`, `stage_to_electrode`, and `stage_to_electrode_float` from `droplogic.utils.hardware_utils` when you need to reason about the underlying calibration.
- There is no camera-pixel calibration in the DMLite agent context.
- Do not duplicate calibration values in agent context files.
- For volume estimates from electrode footprints, treat the DMLite gap height as `50` microns and report estimates, not measurements.

## Matrix Planning
- Default real-hardware execution cadence is `1.0` second between frames unless the active protocol explicitly sets another delay.
- Use `AdvancedDrop` plans and `PlanExecutor`.
- Prefer breakpoints for inspection or long operations.
- Add a breakpoint at the current target frame, often `len(plan.frames) - 1`.
- Call `resume()` when the executor is paused or idle and frames remain.
- Wait for `breakpoint_reached` rather than `is_executing` alone when deciding to inspect or resume.
- Clear breakpoints before resuming after inspection if you want the executor to continue cleanly.

## Feedback
- DMLite does not have camera, microscope, streamer, or droplet-vision feedback in this context.
- Use `plan_summary`, `executor.status()`, and the matrix visualizer.
- If a plan looks wrong, stop, clear, and rebuild it.

## Never Do
- Do not assume stage, camera, microscope, light, or temperature modules exist.
- Do not ask for `verify_droplets` or condensate detection on DMLite.
- Do not invent physical imaging coordinates.
- Do not continue after a plan or executor mismatch without correction.
