# 錄影

錄影被有意同 visualizer 顯示程式碼分開。

`SegmentedVideoWriter` 按需寫 frames，輪換輸出 segments，並維護一個可用於之後拼接嘅 `ffconcat` manifest。

## 點解存在

長實驗會產生大影片。分段錄影更安全，因為佢：

- 限制每個 video segment 嘅大小
- 保留 recorded parts 嘅 live manifest
- 當 `frame_delay` 變化時容許 executor 乾淨咁改變 FPS
- 避免喺 visualizers 入面重複錄影邏輯

## 同執行同步嘅錄影

executor-synchronized recording 由 `PlanExecutor` 協調，而唔係由 visualizers 自己協調。咁 movie frames 會同 plan frames 對齊。

Visualizer snapshots 仍然適合手動擷取同診斷，但連續同步影片應該由 executor 驅動。

## 錄製 Matrix View

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

executor 每執行一個 frame 渲染一張 matrix snapshot。

## 錄製 Streamer View

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_streamer=True,
    streamer_filename="runs/streamer.mp4",
)
```

呢個要求 `system.visualizers.streamer` 存在。

## 同時錄製兩個視圖

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

video FPS 來自 `frame_delay`。

## 分段錄影

長實驗中，啟動 executor 前先喺 visualizer 上設定 segment limits。

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

segments 會寫入相鄰嘅 `_segments` 文件夾。每當 segment 關閉時，live `.ffconcat` manifest 會更新。

## 手動 Snapshots

```python
system.visualizers.matrix.save_snapshot("runs/matrix_snapshot.png")
```

Streamer snapshot：

```python
frame = system.visualizers.streamer.get_snapshot_frame()
```

診斷時使用 snapshots。需要同 protocol timeline 對齊嘅影片時使用 executor recording。
