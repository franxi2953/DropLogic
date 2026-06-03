# Recording

Recording is intentionally separated from visualizer display code.

`SegmentedVideoWriter` writes frames on demand, rotates output segments, and maintains an `ffconcat` manifest that can be used to stitch segments later.

## Why It Exists

Long experiments can create large videos. Segmentation keeps recording safer by:

- limiting the size of each video segment
- preserving a live manifest of recorded parts
- allowing the executor to change FPS cleanly when `frame_delay` changes
- avoiding duplicated recording logic in visualizers

## Execution-Synchronized Recording

Executor-synchronized recording is coordinated by `PlanExecutor`, not by the visualizers themselves. This keeps movie frames aligned with plan frames.

Visualizer snapshots remain useful for manual capture and diagnostics, but continuous synchronized recording should be driven by the executor.

## Record the Matrix View

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

The executor renders one matrix snapshot per executed frame.

## Record the Streamer View

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_streamer=True,
    streamer_filename="runs/streamer.mp4",
)
```

This requires `system.visualizers.streamer` to exist.

## Record Both Views

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

The video FPS is derived from `frame_delay`.

## Segmented Recording

For long experiments, set segment limits on the visualizer before starting the executor.

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

Segments are written into a sibling `_segments` folder. A live `.ffconcat` manifest is updated as segments close.

## Manual Snapshots

```python
system.visualizers.matrix.save_snapshot("runs/matrix_snapshot.png")
```

For streamer snapshots:

```python
frame = system.visualizers.streamer.get_snapshot_frame()
```

Use snapshots for diagnostics. Use executor recording for videos that must stay aligned to the protocol timeline.
