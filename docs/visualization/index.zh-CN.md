# 可视化

可视化在规划、执行和调试液滴协议时提供反馈。

DropLogic 目前有两类主要 visualizer：

- **MatrixVisualizer**：渲染电极矩阵、计划路径、breakpoints 和当前 frame 状态
- **StreamerVisualizer**：显示 live camera 或 microscope frames，并可选择叠加 overlays

录制单独处理，这样与执行同步的视频可以由 `PlanExecutor` 管理。

## 推荐模式

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

使用 visualizers 做显示和 snapshots。使用 executor 做同步视频录制。

## 位置

- `droplogic/utils/visualizer/visualizer.py`
- `droplogic/utils/recording.py`
- `droplogic/visualization/visual_frame_explorer.py`
- `droplogic/utils/debug/plan_debugger.py`
