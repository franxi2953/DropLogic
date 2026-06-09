# Visualizers

Visualizers 透過 `system.visualizers` 連接到 systems。

Simulator 同 DMLite 會自動初始化 matrix visualizer：

```python
system.visualizers.matrix
```

帶 camera 或 microscope 模組嘅系統亦可以暴露：

```python
system.visualizers.streamer
```

## MatrixVisualizer

`MatrixVisualizer` 顯示電極矩陣同執行狀態。佢適合模擬、除錯同 plan inspection。

佢可以顯示：

- 目前 matrix frame
- 液滴 paths
- breakpoint positions
- 被點擊嘅 electrode positions
- 用於 recording 或 diagnostics 嘅 snapshot frames

## 啟用 Matrix Visualization

最簡單方式係透過 executor：

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

亦可以手動 start/stop：

```python
system.visualizers.matrix.start()
system.visualizers.matrix.stop()
```

visualizer 讀取 `system.state["electrode_matrix"]["matrix"]`，所以反映系統狀態目前包含嘅內容。

## Matrix 方向

matrix visualizer 接收 AdvancedDrop 標準 `(row, col)` 邏輯座標，然後旋轉顯示窗口。

預設：

- `matrix_rotation_degrees=90`
- 矩陣順時針顯示 90 度
- 邏輯 `(0, 0)` 出現喺 visualizer 右上附近
- `row` 增大喺預設顯示中向左移動
- `col` 增大喺預設顯示中向下移動

呢個只係繪圖方式，規劃程式仍使用 0-indexed `(row, col)`。

```python
system.visualizers.matrix.set_matrix_rotation(0)
system.visualizers.matrix.set_matrix_rotation(90)
system.visualizers.matrix.set_matrix_rotation(180)
system.visualizers.matrix.set_matrix_rotation(270)
```

點擊會喺 callback 前轉返做邏輯 `(row, col)`。

## Matrix 公共方法

- `start(stop_condition=None)`: 打開顯示窗口。
- `stop()`: 關閉顯示 loop。
- `is_running()`: 返回 visualizer 是否 active。
- `set_background(frame)`: 喺電極網格後混合圖像。
- `set_matrix_rotation(degrees)`: 旋轉顯示矩陣。
- `set_paths(paths)`, `add_path(path)`, `clear_paths()`: 管理顯示軌跡。
- `set_breakpoint_positions(positions)`: 顯示 breakpoint 液滴位置。
- `set_current_frame(frame_num)`: 更新目前 frame 高亮。
- `set_electrode_click_callback(callback)`: 以 `(row, col)` 接收點擊電極。
- `get_snapshot_frame()`: 渲染目前 frame。
- `save_snapshot(output_path)`: 保存 snapshot 圖像。

## StreamerVisualizer

`StreamerVisualizer` 顯示來自 camera 或 microscope 等 capture device 嘅 live frames。

佢可以顯示 raw/processed frames、electrode overlays、droplet detection overlays、condensate detection overlays 同 field-of-view electrode mapping。

```python
system.advanced_drop.executor.start(
    frame_delay=1.0,
    enable_visualizers=True,
)
```

手動建立：

```python
from droplogic.utils.visualizer import StreamerVisualizer

system.visualizers.streamer = StreamerVisualizer(
    device=system.camera,
    box=system,
    window_name="Camera Stream",
)

system.visualizers.streamer.start()
```

`device` 必須暴露 `capture_image() -> numpy.ndarray`。

## Detection Overlays

```python
streamer = system.visualizers.streamer
streamer.enable_droplet_detection(confidence_threshold=0.25)
streamer.enable_condensate_detection(crop_droplet=True)
```

關閉 overlays：

```python
streamer.disable_droplet_detection()
streamer.disable_condensate_detection()
```

## Snapshots

`get_snapshot_frame()` 係 executor-synchronized recording 使用嘅 frame source。Matrix visualizer 會渲染目前電極矩陣同 overlays；streamer visualizer 會返回最新 processed frame、raw frame，或者冇 camera frame 時嘅 placeholder。

## 平台行為

Visualizers 透過父 `DropSystem` 偵測 host platform。macOS 上 OpenCV windows 需要喺 main thread 運行，所以顯示行為較保守。Windows 上 visualizers 可以使用 background display threads。
