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
