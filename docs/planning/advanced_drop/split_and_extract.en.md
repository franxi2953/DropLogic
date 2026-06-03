# Split and Extract

DropLogic has two public split-style operations:

- `reservoir_extraction()`: create one or more droplets from a reservoir droplet.
- `isometric_split()`: split one droplet into symmetric subdroplets.

Both functions extend `system.advanced_drop.plan` and return the IDs of newly created droplets.

## Reservoir Extraction

```python
new_ids = system.advanced_drop.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to2",
    steps=(0, 5),
    split_size={(0, 0)},
    new_droplet_id=10,
)
```

Arguments:

- `reservoir_droplet_id`: ID of the reservoir droplet.
- `split_mode`: `"1to2"`, `"1to3"`, or `"linear"`.
- `steps`: displacement from reservoir corner for `"1to2"` and `"1to3"`.
- `split_size`: extracted droplet shape or size.
- `new_droplet_id`: optional first new ID. If omitted, IDs are generated.
- `halo_size`: inactive halo around extracted droplet for `"1to2"`.
- `separation_steps`: separation distance for `"1to3"`.
- `remove_duplicate_frames`: trim repeated frames after extension.

`steps` are `(row_delta, col_delta)`. Negative row moves upward. Positive column moves rightward.

## `1to2`

Extract one droplet from the reservoir.

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to2",
    steps=(-5, 0),
    split_size={(0, 0), (0, 1)},
    halo_size=1,
)
```

Use this when you want a reservoir to keep most of its footprint while producing one smaller droplet.

## `1to3`

Extract a central droplet and separate the resulting pieces.

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to3",
    steps=(0, 6),
    split_size=(1, 2),
    separation_steps=3,
)
```

For `"1to3"`, `split_size` is interpreted as `(height, width)`.

## `linear`

Create multiple droplets in a linear sweep from a reservoir.

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="linear",
    linear_drops_number=4,
    linear_offset=2,
    linear_space_per_col=4,
    linear_space_per_row=0,
    linear_drop_shape=(1, 1),
    linear_direction=(0, 1),
)
```

Use `linear_direction=(0, 1)` for a horizontal sweep to the right, `(1, 0)` for downward, and negative values for the opposite direction.

## Isometric Split

`isometric_split()` recursively splits a droplet into equal subdroplets and moves them symmetrically.

```python
new_ids = ad.isometric_split(
    droplet_id=1,
    steps=[(0, 5), (3, 0)],
    simultaneous=True,
)
```

The example above:

- splits once horizontally and moves subdroplets left/right by 5 columns.
- splits each result vertically and moves subdroplets up/down by 3 rows.
- produces four subdroplets if enough electrodes are available.

Arguments:

- `droplet_id`: source droplet.
- `steps`: list of `(row_delta, col_delta)` displacement steps.
- `simultaneous`: move subdroplets within a split step together or sequentially.
- `new_droplet_id`: optional first new ID.
- `event_id`: optional event label for the plan.
- `remove_duplicate_frames`: trim repeated frames after extension.

## Common Failure Cases

- The source droplet or reservoir ID does not exist.
- `steps` would place new droplets outside the matrix.
- The extracted droplet overlaps the reservoir.
- The source droplet does not have enough electrodes for the requested split.
- The surrounding area is too constrained for separation movement.
