# Visualizers

## MatrixVisualizer

`MatrixVisualizer` displays the electrode matrix and execution state. It is useful for simulation, debugging, and plan inspection.

It can show:

- current matrix frame
- droplet paths
- breakpoint positions
- clicked electrode positions
- snapshot frames for recording or diagnostics

## StreamerVisualizer

`StreamerVisualizer` displays live frames from a capture device such as a camera or microscope.

It can show:

- raw and processed frames
- electrode overlays
- droplet detection overlays
- condensate detection overlays
- field-of-view electrode mapping

## Platform Behavior

Visualizers detect the host platform through the parent `DropSystem`. On macOS, OpenCV windows need to run on the main thread, so display behavior is more conservative. On Windows, visualizers can run in background display threads.
