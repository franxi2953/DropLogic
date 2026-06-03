# Move

`move()` plans coordinated movement for droplets whose current position differs from their target.

To move an existing droplet again, update its target first:

```python
system.advanced_drop.droplets.update_droplet_target(1, (60, 20))
system.advanced_drop.move(mode="sipp")
```

```python
plan = system.advanced_drop.move(mode="sipp")
```

The returned `DropletPlan` is also stored as `system.advanced_drop.plan`.

## Public Signature

```python
system.advanced_drop.move(
    mode="sipp",
    remove_duplicate_frames=False,
    merge_on_failure=True,
    **kwargs,
)
```

`kwargs` are forwarded to the lower-level SIPP planner.

## Modes

Currently, `mode="sipp"` is the only implemented movement mode.

SIPP means Safe Interval Path Planning. In DropLogic, it routes droplets through space and time while reserving droplet bodies, vital-space halos, and edge transitions to reduce collisions.

If another mode is passed, the planner raises:

```python
ValueError: Unsupported mode
```

## Basic Move

```python
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(8, 8), target=(40, 40), width=2, height=2)
plan = ad.move(mode="sipp")

print(plan.frame_count)
print(plan.targets_reached)
```

## Multi-Droplet Move

```python
ad.droplets.add_droplets([
    {"id": 1, "origin": (10, 10), "target": (40, 40), "width": 2, "height": 2},
    {"id": 2, "origin": (10, 30), "target": (40, 10), "width": 2, "height": 2},
])

plan = ad.move(
    mode="sipp",
    planning_timeout=120,
    max_iterations=50000,
)
```

Only droplets whose `origin_corner != target_corner` are planned. Droplets already at target are kept as active droplets when extending plans.

## Useful Planner Options

- `planning_timeout`: maximum planning time in seconds before stopping.
- `max_iterations`: search iteration limit per droplet.
- `max_frames`: cap the number of generated frames.
- `max_path_frames`: cap path length inside the SIPP search.
- `reservation_horizon`: number of future frames used when reserving initial and final positions.
- `reserve_final_positions`: keep final positions reserved after a path finishes.
- `ignore_vital_space_pairs`: set of droplet-id pairs allowed to ignore vital-space separation.
- `debug_visualization`: mark reserved or vital-space areas in generated frames.

Example:

```python
plan = ad.move(
    mode="sipp",
    planning_timeout=60,
    max_path_frames=200,
    reservation_horizon=250,
    ignore_vital_space_pairs={(1, 2)},
)
```

## Failure Handling

By default, `merge_on_failure=True` means partial planning output can still be appended to the current plan.

If you want to inspect a failed attempt without mutating `ad.plan`, use:

```python
candidate = ad.move(
    mode="sipp",
    merge_on_failure=False,
)

if not candidate.planning_success:
    print(candidate.targets_reached)
```

With `merge_on_failure=False`, droplets that failed planning are reverted to their previous logical corners and the returned plan is not assigned to `ad.plan`.

## Re-Target After Execution

```python
ad.droplets.update_droplet_target(1, (60, 20))
ad.move(mode="sipp")
ad.executor.start(frame_delay=0.5, enable_visualizers=True)
```

The planner reads the last plan state and extends from there.

## Duplicate Frames

```python
ad.move(mode="sipp", remove_duplicate_frames=True)
```

Treat this as development-oriented and potentially unstable. It can shorten plans, but it may also merge event boundaries that are useful for debugging, breakpoints, and protocol inspection.

For now, prefer leaving `remove_duplicate_frames=False` in production workflows unless you have inspected the resulting plan and are confident that the removed frames do not matter.
