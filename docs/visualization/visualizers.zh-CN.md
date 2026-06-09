# Visualizers

Visualizers 通过 `system.visualizers` 连接到 systems。

Simulator 和 DMLite 会自动初始化 matrix visualizer：

```python
system.visualizers.matrix
```

带 camera 或 microscope 模块的系统也可以暴露：

```python
system.visualizers.streamer
```

## MatrixVisualizer

`MatrixVisualizer` 显示电极矩阵和执行状态。它适合仿真、调试和 plan inspection。

它可以显示：

- 当前 matrix frame
- 液滴 paths
- breakpoint positions
- 被点击的 electrode positions
- 用于 recording 或 diagnostics 的 snapshot frames

## 启用 Matrix Visualization

最简单的方式是通过 executor：

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

也可以手动 start/stop：

```python
system.visualizers.matrix.start()
system.visualizers.matrix.stop()
```

visualizer 读取 `system.state["electrode_matrix"]["matrix"]`，因此反映系统状态当前包含的内容。

## Matrix 方向

matrix visualizer 接收 AdvancedDrop 标准 `(row, col)` 逻辑坐标，然后旋转显示窗口。

默认：

- `matrix_rotation_degrees=90`
- 矩阵顺时针显示 90 度
- 逻辑 `(0, 0)` 出现在 visualizer 右上附近
- `row` 增大在默认显示中向左移动
- `col` 增大在默认显示中向下移动

这只是绘制方式，规划代码仍使用 0-indexed `(row, col)`。

修改显示旋转：

```python
system.visualizers.matrix.set_matrix_rotation(0)
system.visualizers.matrix.set_matrix_rotation(90)
system.visualizers.matrix.set_matrix_rotation(180)
system.visualizers.matrix.set_matrix_rotation(270)
```

点击会在 callback 前转换回逻辑 `(row, col)`。

## Matrix 公共方法

- `start(stop_condition=None)`: 打开显示窗口。
- `stop()`: 关闭显示 loop。
- `is_running()`: 返回 visualizer 是否 active。
- `set_background(frame)`: 在电极网格后混合图像。
- `set_matrix_rotation(degrees)`: 旋转显示矩阵。
- `set_paths(paths)`, `add_path(path)`, `clear_paths()`: 管理显示轨迹。
- `set_breakpoint_positions(positions)`: 显示 breakpoint 液滴位置。
- `set_current_frame(frame_num)`: 更新当前 frame 高亮。
- `set_electrode_click_callback(callback)`: 以 `(row, col)` 接收点击电极。
- `get_snapshot_frame()`: 渲染当前 frame。
- `save_snapshot(output_path)`: 保存 snapshot 图像。

## StreamerVisualizer

`StreamerVisualizer` 显示来自 camera 或 microscope 等 capture device 的 live frames。

它可以显示：

- raw 和 processed frames
- electrode overlays
- droplet detection overlays
- condensate detection overlays
- field-of-view electrode mapping

如果系统创建了 streamer visualizer，executor 可以与 matrix visualizer 一起启动它。

```python
system.advanced_drop.executor.start(
    frame_delay=1.0,
    enable_visualizers=True,
)
```

手动构建：

```python
from droplogic.utils.visualizer import StreamerVisualizer

system.visualizers.streamer = StreamerVisualizer(
    device=system.camera,
    box=system,
    window_name="Camera Stream",
)

system.visualizers.streamer.start()
```

`device` 必须暴露 `capture_image() -> numpy.ndarray`。

## Detection Overlays

```python
streamer = system.visualizers.streamer
streamer.enable_droplet_detection(confidence_threshold=0.25)
streamer.enable_condensate_detection(crop_droplet=True)
```

关闭 overlays：

```python
streamer.disable_droplet_detection()
streamer.disable_condensate_detection()
```

## Snapshots

`get_snapshot_frame()` 是 executor-synchronized recording 使用的 frame source。Matrix visualizer 会渲染当前电极矩阵和 overlays；streamer visualizer 会返回最新 processed frame、raw frame，或在没有 camera frame 时返回 placeholder。

## 平台行为

Visualizers 通过父 `DropSystem` 检测 host platform。macOS 上 OpenCV windows 需要运行在 main thread，因此显示行为更保守。Windows 上 visualizers 可以使用 background display threads。
