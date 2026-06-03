# AdvancedDrop

`AdvancedDrop` is the high-level droplet manipulation layer attached to a `DropSystem`.

It is initialized by systems such as `Simulator` and `DMLite`, and then exposed as:

```python
system.advanced_drop
```

## Responsibilities

- manage droplets through `system.advanced_drop.droplets`
- build and update `DropletPlan` objects
- plan SIPP-based movement
- create operation plans for splitting, merging, mixing, and extraction
- connect planning output to `PlanExecutor`
- optionally connect to vision-based validation when the system has the required camera and stage modules

## Coordinate Convention

DropLogic uses matrix coordinates as `(row, col)` tuples.

For droplets, `origin_corner` and `target_corner` are the top-left corner of the droplet footprint. The droplet `shape` is stored as relative offsets from that top-left corner.

```python
ad.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(30, 40),
    width=2,
    height=2,
)
```

This creates a 2x2 droplet whose body starts at row `10`, column `10`, and whose target top-left corner is row `30`, column `40`.

## Public Surface

- **Droplet management**: create, update, inspect, and delete logical droplets.
- **Move**: plan SIPP movement for droplets whose target differs from their current position.
- **Split and extract**: extract droplets from reservoirs or split one droplet into symmetric subdroplets.
- **Merge**: route droplets into one target footprint.
- **Mix**: run split-recombine or 2D loop mixing patterns.
- **Vision and correction**: validate, detect condensates, correct logical position, and move the stage to a droplet.
- **Plan objects**: understand frames, trajectories, events, and plan extension.

## Minimal Example

```python
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(8, 8), target=(20, 20), width=2, height=2)
plan = ad.move(mode="sipp")

print(plan.frame_count)
print(plan.planning_success)
```

The result is stored as `ad.plan` and also returned from planning functions.

## Safety Notes

- Do not directly mutate `droplet.origin_corner` from protocol scripts unless you are deliberately bypassing planner state.
- If the physical droplet is somewhere else after a failed hardware move, use `correct_droplet_position()`.
- `move(mode="sipp")` is the only public movement mode currently implemented. Other `mode` values raise `ValueError`.
- Treat `remove_duplicate_frames=True` as development-oriented and potentially unstable. It can shorten plans, but may also merge event boundaries that are useful for debugging, breakpoints, and protocol inspection. For now, prefer leaving it off in production workflows unless you have inspected the resulting plan.

## Where It Lives

- `droplogic/utils/advanced_drop/__init__.py`
- `droplogic/utils/advanced_drop/common.py`
- `droplogic/utils/advanced_drop/move.py`
- `droplogic/utils/advanced_drop/splitting.py`
- `droplogic/utils/advanced_drop/merge.py`
- `droplogic/utils/advanced_drop/mixing.py`
- `droplogic/utils/advanced_drop/feedback.py`

## Design Boundary

`AdvancedDrop` should not know the low-level protocol of a hardware device. It creates and manipulates matrix-frame plans; systems and modules translate those plans into hardware commands.
