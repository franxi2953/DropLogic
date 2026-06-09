# 录制

录制被有意与 visualizer 显示代码分开。

`SegmentedVideoWriter` 按需写 frames，轮换输出 segments，并维护一个可用于之后拼接的 `ffconcat` manifest。

## 为什么存在

长实验会产生大视频。分段录制更安全，因为它：

- 限制每个 video segment 的大小
- 保留 recorded parts 的 live manifest
- 当 `frame_delay` 变化时允许 executor 干净地改变 FPS
- 避免在 visualizers 中重复录制逻辑

## 与执行同步的录制

executor-synchronized recording 由 `PlanExecutor` 协调，而不是由 visualizers 自己协调。这样 movie frames 会与 plan frames 对齐。

Visualizer snapshots 仍适合手动捕获和诊断，但连续同步视频应由 executor 驱动。

## 录制 Matrix View

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

executor 每执行一个 frame 渲染一张 matrix snapshot。

## 录制 Streamer View

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_streamer=True,
    streamer_filename="runs/streamer.mp4",
)
```

这要求 `system.visualizers.streamer` 存在。

## 同时录制两个视图

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    record_streamer=True,
    matrix_filename="runs/matrix.mp4",
    streamer_filename="runs/streamer.mp4",
)
```

video FPS 来自 `frame_delay`。

## 分段录制

长实验中，在启动 executor 前先在 visualizer 上设置 segment limits。

```python
system.visualizers.matrix.movie_segment_duration_seconds = 120
system.visualizers.matrix.movie_segment_frame_limit = None

system.advanced_drop.executor.start(
    frame_delay=1.0,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

segments 会写入相邻的 `_segments` 文件夹。每当 segment 关闭时，live `.ffconcat` manifest 会更新。

## 手动 Snapshots

```python
system.visualizers.matrix.save_snapshot("runs/matrix_snapshot.png")
```

Streamer snapshot：

```python
frame = system.visualizers.streamer.get_snapshot_frame()
```

诊断时使用 snapshots。需要与 protocol timeline 对齐的视频时使用 executor recording。
