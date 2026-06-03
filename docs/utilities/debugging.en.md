# Debugging and Diagnostics

Debugging tools help inspect plans, runtime failures, and local installation issues.

## Main Pieces

- `plan_debugger.py`: visual frame explorer for saved plans
- `doctor.py`: checks for required native runtime files
- `logging_config.py`: shared logger setup and log-level helpers
- executor timeout reports: diagnostic logs written when breakpoint execution stalls

## Where It Lives

- `droplogic/utils/debug/plan_debugger.py`
- `droplogic/utils/doctor.py`
- `droplogic/utils/logging_config.py`
- `droplogic/utils/advanced_drop/plan_executor.py`

The most useful debugging artifacts are usually saved plans, executor diagnostics, and screenshots or recordings from synchronized visualizer output.

## Save a Plan for Debugging

Use the executor to save the plan and droplets in the debugger format.

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/debug_plan.pkl",
)
```

The pickle stores:

- `plan`
- `droplets`

## Open the Plan Debugger

From Python:

```python
from droplogic.utils.debug.plan_debugger import open_explorer

open_explorer("runs/debug_plan.pkl")
```

From the command line:

```bash
python -m droplogic.utils.debug.plan_debugger runs/debug_plan.pkl
```

The debugger is a PyQt UI for inspecting frames, droplet positions, active droplets, event labels, and possible occupancy conflicts.

## What to Look For

- Frame where a droplet first diverges from expectation.
- Event label around the failure.
- Active droplet list for that frame.
- Body/vital-space overlap on a suspicious electrode.
- Trajectory discontinuities after split, merge, or correction events.

## Breakpoint Debugging

Use executor breakpoints to stop at a known frame before running the next operation.

```python
executor = system.advanced_drop.executor

executor.add_breakpoint(40)
executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    save_to_file="runs/breakpoint_debug.pkl",
)

executor.execute_until_breakpoint_or_raise(label="before merge")
```

At the breakpoint, inspect:

```python
print(executor.status())
print(executor.get_droplet_position(1))
```

Then either correct, replan, or resume:

```python
system.advanced_drop.correct_droplet_position(1, (35, 22))
executor.resume()
```

## Timeout Reports

If `execute_until_breakpoint_or_raise()` times out, the executor writes `executor_timeout_reports.log`.

The report includes executor state, pending breakpoints, save paths, queue status when available, and XY stage state when present.

## Runtime Doctor

On Windows, use the runtime doctor to check native runtime files:

```bash
python -m droplogic.utils.doctor
```

It checks native components through the runtime resolver. Expected runtime locations include:

- `DROPLOGIC_RUNTIME_DIR`
- runtime folder next to the DropLogic package
- installer-provided registry path
- `%ProgramData%/DropLogic/runtime`

## Logging

```python
from droplogic.utils.logging_config import (
    enable_debug_logging,
    enable_info_logging,
    enable_error_only_logging,
)

enable_debug_logging()
```

Debug logs are useful during planning failures because the planner and executor write detailed messages to the shared DropLogic loggers.
