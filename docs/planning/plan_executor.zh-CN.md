# Plan Executor

`PlanExecutor` 在系统上运行 `DropletPlan`。

它负责同步执行：逐 frame 前进、更新液滴位置、向系统发送矩阵命令、协调 visualizers，并可选录制同步输出。

## 它做什么

- 在 worker thread 中异步运行 plans
- 按受控 `frame_delay` 向系统发送 frame updates
- 跟踪执行状态和进度
- 支持 pause、resume、stop 和 breakpoints
- 随 frames 执行更新液滴位置
- 协调 matrix 和 streamer visualizers
- 通过 `SegmentedVideoWriter` 录制 executor-synchronized video
- breakpoint 执行超时时写诊断 reports

## 典型用法

```python
system.advanced_drop.move(mode="sipp")

system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

硬件上应使用更慢的 `frame_delay`，以匹配电压驱动和流体响应。模拟器通常可以使用更短 delay。

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

参数：

- `plan`：要执行的 plan。为 `None` 时使用 `system.advanced_drop.plan`。
- `frame_delay`：frames 之间的秒数。
- `verify_positions`：如果系统支持，启用 vision-based validation。
- `enable_visualizers`：启动或更新 matrix/streamer visualizers。
- `save_to_file`：保存 plan 和 droplets pickle 的路径或路径列表。
- `record_matrix`：以 executor sync 录制 matrix visualizer frames。
- `record_streamer`：以 executor sync 录制 streamer visualizer frames。
- `matrix_filename`：matrix video 输出路径。
- `streamer_filename`：streamer video 输出路径。

## 保存协议

当希望之后在 plan debugger 中重新打开协议 snapshot 时，使用 `save_to_file`。

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

保存的 pickle 包含：

- `plan`
- `droplets`

## 保存同步视频

录制应通过 executor 完成，而不是直接从 visualizer loop 录制。

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

如果系统有 streamer visualizer：

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

录制 FPS 来自 `frame_delay`，因此一个 movie frame 对应一个已执行 plan frame。

## Pause, Resume, Stop

```python
executor = system.advanced_drop.executor

executor.pause()
print(executor.status())

executor.resume()
executor.stop()
```

`status()` 返回执行状态、当前 frame、总 frames、进度、breakpoints 和是否到达 breakpoint。

## Breakpoints

Breakpoints 会在某个 frame 执行后暂停。

```python
executor = system.advanced_drop.executor

executor.add_breakpoint(25)
executor.start(frame_delay=0.5, enable_visualizers=True)

executor.execute_until_breakpoint()
print(executor.status()["current_frame"])
```

breakpoint 是 one-shot：到达后会被移除。继续执行用 `executor.resume()`。

## 带诊断的 Breakpoint 等待

协议和测试中优先使用 `execute_until_breakpoint_or_raise()`。

```python
executor.add_breakpoint(50)
executor.start(frame_delay=0.5, save_to_file="runs/debug_protocol.pkl")
executor.execute_until_breakpoint_or_raise(label="move reagent to merge point")
```

如果 executor 卡住或超时，会尽可能在已保存协议旁写 `executor_timeout_reports.log`。报告包含 executor status、pending breakpoints、save paths、queue status 和 XY stage state。

## 动态扩展 Plan

你可以在 breakpoint 暂停，添加新操作，然后 resume。

```python
executor.add_breakpoint(20)
executor.start(frame_delay=0.5, save_to_file="runs/protocol.pkl")
executor.execute_until_breakpoint_or_raise(label="first move")

system.advanced_drop.droplets.update_droplet_target(1, (60, 60))
system.advanced_drop.move(mode="sipp")

executor.resume()
```

`resume()` 看到新的 `system.advanced_drop.plan` 时会重新加载 plan，并刷新通过 `save_to_file` 配置的保存文件。

## 运行时液滴位置

```python
pos = system.advanced_drop.executor.get_droplet_position(1)
```

这返回最后执行的位置，不一定是最终计划位置。最终计划位置用 `system.advanced_drop.get_droplet_position(1)`。

## 代码位置

- `droplogic/utils/advanced_drop/plan_executor.py`
- `droplogic/utils/recording.py`

## 设计边界

executor 是唯一应负责同步 plan 保存和录制的层。Visualizers 可以暴露 frames 和 snapshots，但 executor-level recording 能让 matrix 和 streamer 输出与 plan timeline 对齐。
