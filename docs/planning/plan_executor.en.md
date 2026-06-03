# Plan Executor

`PlanExecutor` runs a `DropletPlan` against a system.

It is responsible for synchronized execution: advancing frame by frame, updating droplet positions, sending matrix commands to the system, coordinating visualizers, and optionally recording synchronized output.

## What It Does

- runs plans asynchronously in a worker thread
- sends frame updates to the system at a controlled `frame_delay`
- tracks execution state and progress
- supports pause, resume, stop, and breakpoints
- updates droplet positions as frames execute
- coordinates matrix and streamer visualizers
- records executor-synchronized video through `SegmentedVideoWriter`
- writes diagnostic reports when breakpoint execution times out

## Typical Use

```python
system.advanced_drop.move(mode="sipp")

system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

For hardware, use a slower `frame_delay` that matches voltage actuation and fluid response. For the simulator, shorter delays are usually fine.

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

Arguments:

- `plan`: plan to execute. If `None`, uses `system.advanced_drop.plan`.
- `frame_delay`: seconds between frames.
- `verify_positions`: enable vision-based validation if the system supports it.
- `enable_visualizers`: start/update matrix and streamer visualizers.
- `save_to_file`: path, or list of paths, where the plan and droplets are pickled.
- `record_matrix`: record matrix visualizer frames in executor sync.
- `record_streamer`: record streamer visualizer frames in executor sync.
- `matrix_filename`: output path for matrix video.
- `streamer_filename`: output path for streamer video.

## Save the Protocol

Use `save_to_file` when you want a protocol snapshot that can be reopened later in the plan debugger.

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

You can save to multiple places:

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file=[
        "runs/protocol.pkl",
        "backup/protocol.pkl",
    ],
)
```

The saved pickle contains a dictionary with:

- `plan`
- `droplets`

## Save Synchronized Video

Recording should be done through the executor, not directly through the visualizer loop.

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

If the system has a streamer visualizer:

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

The recording FPS is derived from `frame_delay`, so one movie frame corresponds to one executed plan frame.

For long runs, set segment metadata on the visualizer before starting:

```python
system.visualizers.matrix.movie_segment_duration_seconds = 60
system.visualizers.matrix.movie_segment_frame_limit = None

system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

Segments are written next to the requested movie path, and an `.ffconcat` manifest is maintained for later stitching.

## Pause, Resume, Stop

```python
executor = system.advanced_drop.executor

executor.pause()
print(executor.status())

executor.resume()
executor.stop()
```

`status()` returns:

- `is_executing`
- `current_frame`
- `total_frames`
- `frames_executed`
- `execution_time`
- `progress`
- `breakpoints`
- `breakpoint_reached`

On Windows, the executor also has a keyboard listener: space pauses/resumes and `q` stops while paused. On non-Windows systems this keyboard path is disabled.

## Breakpoints

Breakpoints pause execution after a frame has been executed.

```python
executor = system.advanced_drop.executor

executor.add_breakpoint(25)
executor.start(frame_delay=0.5, enable_visualizers=True)

executor.execute_until_breakpoint()
print(executor.status()["current_frame"])
```

Breakpoints are one-shot: the executor removes a breakpoint after reaching it.

To continue:

```python
executor.resume()
```

To remove breakpoints manually:

```python
executor.remove_breakpoint(25)
executor.clear_breakpoints()
```

## Breakpoint Wait With Diagnostics

For protocols or tests, prefer `execute_until_breakpoint_or_raise()`.

```python
executor.add_breakpoint(50)
executor.start(
    frame_delay=0.5,
    save_to_file="runs/debug_protocol.pkl",
)

executor.execute_until_breakpoint_or_raise(
    label="move reagent to merge point",
)
```

If the executor stalls or times out, it writes `executor_timeout_reports.log` next to the saved protocol when possible.

The report includes:

- executor status
- pending breakpoints
- save paths
- queue status if the system exposes it
- XY stage state if present

## Dynamic Plan Extension

You can pause at a breakpoint, add new operations, then resume.

```python
executor.add_breakpoint(20)
executor.start(frame_delay=0.5, save_to_file="runs/protocol.pkl")
executor.execute_until_breakpoint_or_raise(label="first move")

system.advanced_drop.droplets.update_droplet_target(1, (60, 60))
system.advanced_drop.move(mode="sipp")

executor.resume()
```

When `resume()` sees a newer `system.advanced_drop.plan`, it reloads the plan and refreshes any save files configured through `save_to_file`.

## Runtime Droplet Position

```python
pos = system.advanced_drop.executor.get_droplet_position(1)
```

This returns the last executed position, not necessarily the final planned position.

Use `system.advanced_drop.get_droplet_position(1)` for the final planned position.

## Manual Stage Target

If a matrix visualizer is enabled, clicking an electrode can set a manual stage target through the executor callback.

You can also call it directly:

```python
system.advanced_drop.executor.set_manual_stage_target((42, 17))
```

The manual target lasts for a short focus cycle, then normal droplet-following behavior resumes.

## Where It Lives

- `droplogic/utils/advanced_drop/plan_executor.py`
- `droplogic/utils/recording.py`

## Design Boundary

The executor is the only layer that should do synchronized plan saving and recording. Visualizers can expose frames and snapshots, but executor-level recording keeps matrix and streamer output aligned with the plan timeline.
