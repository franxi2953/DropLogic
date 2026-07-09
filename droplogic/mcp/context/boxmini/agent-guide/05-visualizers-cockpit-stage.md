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
