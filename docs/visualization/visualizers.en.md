# Visualizers

Visualizers are attached to systems through `system.visualizers`.

Simulator and DMLite initialize a matrix visualizer automatically:

```python
system.visualizers.matrix
```

Systems with camera or microscope modules can also expose:

```python
system.visualizers.streamer
```

## MatrixVisualizer

`MatrixVisualizer` displays the electrode matrix and execution state. It is useful for simulation, debugging, and plan inspection.

It can show:

- current matrix frame
- droplet paths
- breakpoint positions
- clicked electrode positions
- snapshot frames for recording or diagnostics

## Enable Matrix Visualization

The easiest path is through the executor:

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

Manual start/stop is also possible:

```python
system.visualizers.matrix.start()
system.visualizers.matrix.stop()
```

The visualizer reads `system.state["electrode_matrix"]["matrix"]`, so it reflects whatever the system state currently contains.

## Matrix Public Methods

- `start(stop_condition=None)`: open the display window.
- `stop()`: close the display loop.
- `is_running()`: return whether the visualizer is active.
- `set_background(frame)`: blend an image behind the electrode grid.
- `set_paths(paths)`: replace displayed droplet trajectories.
- `add_path(path)`: append one trajectory.
- `clear_paths()`: remove displayed trajectories.
- `set_breakpoint_positions(positions)`: show breakpoint droplet positions.
- `set_current_frame(frame_num)`: update the highlighted current frame.
- `set_electrode_click_callback(callback)`: receive clicked electrodes as `(row, col)`.
- `get_snapshot_frame()`: render the current matrix visualizer frame.
- `save_snapshot(output_path)`: save a rendered snapshot image.

Example:

```python
matrix_viz = system.visualizers.matrix
matrix_viz.set_paths(list(system.advanced_drop.plan.droplet_trajectories.values()))
matrix_viz.save_snapshot("runs/matrix_snapshot.png")
```

## StreamerVisualizer

`StreamerVisualizer` displays live frames from a capture device such as a camera or microscope.

It can show:

- raw and processed frames
- electrode overlays
- droplet detection overlays
- condensate detection overlays
- field-of-view electrode mapping

## Enable Streamer Visualization

If your system creates a streamer visualizer, the executor can start it alongside the matrix visualizer:

```python
system.advanced_drop.executor.start(
    frame_delay=1.0,
    enable_visualizers=True,
)
```

To construct one manually for a custom system:

```python
from droplogic.utils.visualizer import StreamerVisualizer

system.visualizers.streamer = StreamerVisualizer(
    device=system.camera,
    box=system,
    window_name="Camera Stream",
)

system.visualizers.streamer.start()
```

The `device` must expose `capture_image() -> numpy.ndarray`.

## Streamer Public Methods

- `start(stop_condition=None)`: start capture and display.
- `stop()`: stop capture and display threads.
- `is_running()`: return whether capture or display is active.
- `set_device(device)`: switch capture device.
- `set_processor(fn)`: add a frame processor callback.
- `get_raw_frame()`: return latest raw frame.
- `get_processed_frame()`: return latest processed frame with overlays.
- `get_snapshot_frame()`: return a stable frame for snapshots or executor recording.
- `get_electrodes_in_fov()`: return electrode coordinates currently drawn in the field of view.

## Detection Overlays

Droplet detection:

```python
streamer = system.visualizers.streamer
streamer.enable_droplet_detection(confidence_threshold=0.25)
streamer.set_detection_style(box_color=(0, 255, 0), text_color=(255, 255, 255))
```

Condensate detection:

```python
streamer.enable_condensate_detection(
    confidence_threshold=0.25,
    crop_droplet=True,
    crop_padding=50,
)
streamer.set_condensate_detection_style(box_color=(255, 0, 255))
```

Disable overlays:

```python
streamer.disable_droplet_detection()
streamer.disable_condensate_detection()
```

## Snapshots

`get_snapshot_frame()` is the frame source used by executor-synchronized recording.

For the matrix visualizer, it renders the current electrode matrix plus overlays.

For the streamer visualizer, it returns the latest processed frame, then raw frame, then a placeholder if no camera frame has arrived yet.

## Platform Behavior

Visualizers detect the host platform through the parent `DropSystem`. On macOS, OpenCV windows need to run on the main thread, so display behavior is more conservative. On Windows, visualizers can run in background display threads.
