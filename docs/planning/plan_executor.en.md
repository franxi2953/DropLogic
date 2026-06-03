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

## Where It Lives

- `droplogic/utils/advanced_drop/plan_executor.py`
- `droplogic/utils/recording.py`

## Design Boundary

The executor is the only layer that should do synchronized plan saving and recording. Visualizers can expose frames and snapshots, but executor-level recording keeps matrix and streamer output aligned with the plan timeline.
