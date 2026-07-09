# Plan Executor

`PlanExecutor` runs a `DropletPlan` against a system.

It is responsible for synchronized execution: advancing frame by frame, updating droplet positions, sending matrix commands to the system, coordinating visualizers, and optionally recording synchronized output.

The executor is also the best runtime authority for external applications that need to visualize or inspect an active protocol. It owns the execution cursor, the currently loaded plan, the last applied frame, breakpoints, stage tracking state, and synchronized recording state.

## What It Does

- runs plans asynchronously in a worker thread
- sends frame updates to the system at a controlled `frame_delay`
- tracks execution state and progress
- supports pause, resume, stop, and breakpoints
- updates droplet positions as frames execute
- coordinates matrix and streamer visualizers
- records executor-synchronized video through `SegmentedVideoWriter`
- writes diagnostic reports when breakpoint execution times out
- exposes compact runtime state that dashboards or other apps can render without reading raw hardware internals

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
- `last_update`
- `breakpoints`
- `breakpoint_reached`
- `stage_tracking_mode`
- `fixed_stage_position`
- `verify_positions`
- `last_stage_target_position`
- `last_frame`
- `last_applied_frame`

`current_frame` is the next frame the executor intends to execute. External apps must not render `current_frame` or the final planned frame as the physical chip state. To show the matrix that is actually synchronized with hardware, use `status()["last_applied_frame"]["index"]` plus the executor's recorded last-applied frame matrix. This matters at breakpoints and during planning changes: after frame `N` is applied, the executor may pause with `current_frame == N + 1`, while future frames may already exist in the plan but have not been sent to the matrix.

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

## Plan State For External Apps

External UIs should treat the executor and the plan as a structured scene source, not as screenshots. The useful runtime inputs are:

- `executor.status()` for the execution cursor, progress, breakpoints, stage tracking mode, and last applied frame.
- `executor.current_plan` for the plan currently being executed. If the executor has not started yet, use `system.advanced_drop.plan`.
- the executor's last-applied frame matrix for the physical electrode state. Use `plan.frames[frame_index]` only when `frame_index` is the executor's last applied frame for that same plan.
- `plan.droplet_trajectories` for droplet paths over time.
- `plan.active_droplets_per_frame` for which droplets are active at each frame.
- `plan.events` and `plan.event_id_per_frame` for protocol step labels.
- `system.advanced_drop.droplets` for droplet shape, target, priority, and vital-space metadata.

Use a compact DTO for browser dashboards or other apps. Do not stream the full 128 x 128 matrix as raw nested JSON on every update if the app only needs rendering; encode active electrodes as row ranges or active-cell spans.

Example shape:

```json
{
  "available": true,
  "scene_mode": "advanced_drop",
  "revision": "compact-state-hash",
  "matrix": {
    "shape": [128, 128],
    "encoding": "active_ranges_by_row",
    "rows": {
      "40": [[1, 6]],
      "41": [[1, 6]]
    }
  },
  "executor": {
    "is_executing": true,
    "current_frame": 42,
    "last_frame": {"index": 41},
    "total_frames": 180,
    "stage_tracking_mode": "follow_droplets"
  },
  "plan": {
    "planning_success": true,
    "current_event": [41, "move", {"event_id": 3}]
  },
  "droplets": [
    {
      "id": 204,
      "position": [40, 1],
      "target": [70, 20],
      "bbox": {"row_min": 40, "row_max": 43, "col_min": 1, "col_max": 4},
      "path": [[40, 1], [41, 1], [42, 2]]
    }
  ]
}
```

This is the pattern used by dashboard-style integrations: the app renders its own matrix canvas from plan/executor state, while OpenCV visualizer frames remain a fallback for debugging or direct snapshots. In MCP, `execution_scene` exposes this same idea as a compact, bounded state tool. Agents should still prefer smaller summaries such as `plan_summary`, `executor_status`, `droplets_summary`, and `matrix_summary` when they do not need the combined scene.

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
