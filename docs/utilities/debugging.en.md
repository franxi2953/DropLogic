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
