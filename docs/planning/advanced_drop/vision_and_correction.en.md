# Vision and Correction

Vision helpers are optional. They only work when the system has the required camera, microscope, and/or XY stage modules.

Simulator and DMLite workflows can still use debug modes and logical correction utilities.

## Verify Droplets

`verify_droplets()` checks whether droplets are where the plan expects them to be.

```python
results, frame_files = system.advanced_drop.verify_droplets(
    frame_idx=20,
    droplet_ids=[1, 2],
    save_frames_path="runs/verification_frames",
)
```

Returns:

- `results`: dictionary mapping `droplet_id` to `True` or `False`.
- `frame_files`: dictionary mapping `droplet_id` to saved image paths when `save_frames_path` is provided.

Requirements:

- XY stage module.
- camera or microscope module.
- an initialized `DropletPositionValidator`.

Use debug mode to test recovery logic without hardware vision:

```python
results, frame_files = ad.verify_droplets(
    frame_idx=10,
    droplet_ids=[1],
    debug=True,
    save_frames_path="runs/debug_verification",
)
```

## Correct Logical Position

Use `correct_droplet_position()` when the physical droplet is at a different electrode than the planner believes.

```python
ad.correct_droplet_position(
    droplet_id=1,
    correct_pos=(34, 42),
)
```

This appends a correction frame, updates the droplet trajectory, and updates the droplet object's current corner.

Do this instead of assigning `droplet.origin_corner = ...` in a protocol script.

## Move Stage to Droplet Center

```python
ok = ad.move_to_droplet_center(
    droplet_id=1,
    wait_before_check=0.5,
    wait_after_check=0.5,
)
```

This computes the droplet center, converts it to stage coordinates, updates `xy_stage.position`, and waits for motion completion.

It returns `True` on success and `False` if the droplet is missing, motion times out, or the stage command fails.

## Detect Condensates

`detect_condensates()` runs droplet and condensate detection on a supplied frame or on newly captured microscope frames.

```python
results, annotated = ad.detect_condensates(
    confidence_threshold=0.25,
    crop_droplet=True,
    crop_padding=50,
    return_annotated=True,
    save_image_path="runs/condensates.png",
)
```

Returns:

- `results`: dictionary keyed by normalized droplet center coordinates.
- `annotated`: annotated image when `return_annotated=True`.

Debug mode creates mock detections:

```python
results, annotated = ad.detect_condensates(
    debug=True,
    return_annotated=True,
)
```

## Capture Settings

When `frame=None`, `detect_condensates()` captures fluorescence and brightfield frames using the system camera/microscope pathway, then attempts to restore the previous microscope and light settings.

The main capture options are:

- `fluo_exposure`
- `fluo_light`
- `brightfield_exposure`
- `brightfield_light`

Use explicit frames when you want full control over acquisition:

```python
frame = system.visualizers.streamer.get_raw_frame()
results, annotated = ad.detect_condensates(frame=frame, return_annotated=True)
```
