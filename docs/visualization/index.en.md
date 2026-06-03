# Visualization

Visualization gives feedback while planning, executing, and debugging droplet protocols.

DropLogic currently has two main visualizer families:

- **MatrixVisualizer**: renders the electrode matrix, planned paths, breakpoints, and current frame state
- **StreamerVisualizer**: displays live camera or microscope frames, optionally with overlays

Recording is handled separately so execution-synchronized video can be owned by `PlanExecutor`.

## Recommended Pattern

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

Use visualizers for display and snapshots. Use the executor for synchronized video.

## Where It Lives

- `droplogic/utils/visualizer/visualizer.py`
- `droplogic/utils/recording.py`
- `droplogic/visualization/visual_frame_explorer.py`
- `droplogic/utils/debug/plan_debugger.py`
