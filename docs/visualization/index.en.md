# Visualization

Visualization gives feedback while planning, executing, and debugging droplet protocols.

DropLogic currently has two main visualizer families:

- **MatrixVisualizer**: renders the electrode matrix, planned paths, breakpoints, and current frame state
- **StreamerVisualizer**: displays live camera or microscope frames, optionally with overlays

Recording is handled separately so execution-synchronized video can be owned by `PlanExecutor`.

## Where It Lives

- `droplogic/utils/visualizer/visualizer.py`
- `droplogic/utils/recording.py`
- `droplogic/visualization/visual_frame_explorer.py`
- `droplogic/utils/debug/plan_debugger.py`
