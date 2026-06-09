# Plan Executor

`PlanExecutor` 喺系統上運行 `DropletPlan`。

佢負責同步執行：逐 frame 前進、更新液滴位置、向系統發送矩陣命令、協調 visualizers，並可選錄製同步輸出。

## 佢做咩

- 喺 worker thread 中異步運行 plans
- 按受控 `frame_delay` 向系統發送 frame updates
- 跟蹤執行狀態同進度
- 支援 pause、resume、stop 同 breakpoints
- 隨 frames 執行更新液滴位置
- 協調 matrix 同 streamer visualizers
- 透過 `SegmentedVideoWriter` 錄製 executor-synchronized video
- breakpoint 執行超時時寫診斷 reports

## 典型用法

```python
system.advanced_drop.move(mode="sipp")

system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

硬件上應使用較慢嘅 `frame_delay`，以匹配電壓驅動同流體響應。模擬器通常可以用較短 delay。

## `start()`

```python
system.advanced_drop.executor.start(
    plan=None,
    frame_delay=1.0,
    verify_positions=True,
    enable_visualizers=False,
    save_to_file=None,
    record_matrix=False,
    record_streamer=False,
    matrix_filename=None,
    streamer_filename=None,
)
```

參數包括要執行嘅 `plan`、frames 之間嘅 `frame_delay`、是否啟用 visualizers、保存 pickle 嘅 `save_to_file`，以及 matrix/streamer 錄影輸出路徑。

## 保存 Protocol

當想之後喺 plan debugger 重新打開 protocol snapshot 時，使用 `save_to_file`。

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

保存嘅 pickle 包含 `plan` 同 `droplets`。

## 保存同步影片

錄影應透過 executor 完成，而唔係直接由 visualizer loop 錄製。

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

如果系統有 streamer visualizer：

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

錄影 FPS 來自 `frame_delay`，所以一個 movie frame 對應一個已執行 plan frame。

## Pause, Resume, Stop

```python
executor = system.advanced_drop.executor

executor.pause()
print(executor.status())

executor.resume()
executor.stop()
```

`status()` 返回執行狀態、目前 frame、總 frames、進度、breakpoints 同是否到達 breakpoint。

## Breakpoints

Breakpoints 會喺某個 frame 執行後暫停。

```python
executor.add_breakpoint(25)
executor.start(frame_delay=0.5, enable_visualizers=True)
executor.execute_until_breakpoint()
```

breakpoint 係 one-shot：到達後會被移除。繼續執行用 `executor.resume()`。

## 帶診斷嘅 Breakpoint 等待

protocol 同測試中優先使用 `execute_until_breakpoint_or_raise()`。

```python
executor.add_breakpoint(50)
executor.start(frame_delay=0.5, save_to_file="runs/debug_protocol.pkl")
executor.execute_until_breakpoint_or_raise(label="move reagent to merge point")
```

如果 executor 卡住或超時，會盡可能寫 `executor_timeout_reports.log`。報告包含 executor status、pending breakpoints、save paths、queue status 同 XY stage state。

## 動態擴展 Plan

你可以喺 breakpoint 暫停，加入新操作，然後 resume。

```python
executor.add_breakpoint(20)
executor.start(frame_delay=0.5, save_to_file="runs/protocol.pkl")
executor.execute_until_breakpoint_or_raise(label="first move")

system.advanced_drop.droplets.update_droplet_target(1, (60, 60))
system.advanced_drop.move(mode="sipp")

executor.resume()
```

`resume()` 見到新嘅 `system.advanced_drop.plan` 時會重新載入 plan，並刷新透過 `save_to_file` 設定嘅保存檔。

## 程式位置

- `droplogic/utils/advanced_drop/plan_executor.py`
- `droplogic/utils/recording.py`

## 設計邊界

executor 係唯一應負責同步 plan 保存同錄影嘅層。Visualizers 可以暴露 frames 同 snapshots，但 executor-level recording 可以令 matrix 同 streamer 輸出同 plan timeline 對齊。
