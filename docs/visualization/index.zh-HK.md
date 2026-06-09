# 視覺化

視覺化喺規劃、執行同除錯液滴 protocol 時提供回饋。

DropLogic 目前有兩類主要 visualizer：

- **MatrixVisualizer**：渲染電極矩陣、計劃路徑、breakpoints 同目前 frame 狀態
- **StreamerVisualizer**：顯示 live camera 或 microscope frames，並可選擇疊加 overlays

錄影會分開處理，咁同執行同步嘅影片可以由 `PlanExecutor` 管理。

## 推薦模式

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

用 visualizers 做顯示同 snapshots。用 executor 做同步影片錄製。

## 位置

- `droplogic/utils/visualizer/visualizer.py`
- `droplogic/utils/recording.py`
- `droplogic/visualization/visual_frame_explorer.py`
- `droplogic/utils/debug/plan_debugger.py`
