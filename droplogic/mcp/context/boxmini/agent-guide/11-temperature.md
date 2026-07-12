## Temperature
- Use `temperature_hold(target_c=..., hold_seconds=...)` for short single-setpoint waits.
- Use the high-level temperature tools for setting, holding, cooling down, and curves. Do not call `module_call(module="temperature", method="set_temperature", ...)` unless the user explicitly asks for low-level debugging; its Python argument names are not the MCP interface.
- Temperature holds and melting-curve steps default to `tolerance_c=0.2`: the tool sets the target, waits until the measured temperature is within 0.2 C of the target, then starts counting `hold_seconds`. Only override this when the user explicitly asks for a different stability window.
- For temperature-only long ramps, per-degree waits, `require_settle=true`, or multi-minute holds with no per-step imaging, use `start_temperature_routine(steps=[...], require_settle=true)` and poll `temperature_routine_status()`.
- Do not use `start_temperature_routine` for melting curves or time series that require photos at each step; that routine only controls temperature and does not trigger camera captures. Use `start_melting_curve_capture` instead.
- Use `cancel_temperature_routine()` before changing strategy or closing if a background routine is active.
- Do not keep one MCP call open for a long ramp. If no background routine exists, drive the ramp with short set/poll calls.
