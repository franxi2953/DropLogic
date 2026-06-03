# Droplet Management

Droplets are managed through `system.advanced_drop.droplets`.

This object behaves like a list, but adds helper methods for creating, updating, and inspecting `Droplet` objects.

## `create_droplet()`

Create one logical droplet and append a frame showing it at its origin.

```python
droplet = system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(40, 40),
    width=2,
    height=2,
    priority=0,
    vital_space=1,
)
```

Use either `width` and `height` for a rectangular droplet, or `shape` for a custom footprint:

```python
shape = {(0, 0), (0, 1), (1, 0)}

system.advanced_drop.droplets.create_droplet(
    droplet_id=2,
    origin=(20, 20),
    target=(30, 25),
    shape=shape,
)
```

Arguments:

- `droplet_id`: unique integer identifier.
- `origin`: current top-left `(row, col)` position.
- `target`: desired top-left `(row, col)` position.
- `shape`: optional set of relative `(row, col)` offsets.
- `width`, `height`: rectangular shape dimensions if `shape` is not provided.
- `priority`: routing order. The current SIPP planner sorts droplets from lowest to highest numeric value, so `priority=0` is planned before `priority=1`. Earlier-planned droplets reserve space first and often get the most direct route; later droplets route around those reservations.
- `vital_space`: minimum halo used for collision avoidance.

## Bulk Creation

Use `add_droplets()` when a protocol starts from a list of droplet definitions.

```python
system.advanced_drop.droplets.add_droplets([
    {"id": 1, "origin": (10, 10), "target": (30, 30), "width": 2, "height": 2},
    {"id": 2, "origin": (12, 40), "target": (50, 55), "width": 2, "height": 2},
])
```

## Update Targets

`update_droplet_target()` is the normal way to request a new move after a previous plan has executed.

```python
system.advanced_drop.droplets.update_droplet_target(1, (70, 20))
system.advanced_drop.move(mode="sipp")
```

Reminder: `move()` only plans droplets whose current position differs from their target. If a droplet is already at target, call `update_droplet_target()` first.

`update_droplet_position()` changes the logical current position. Prefer `system.advanced_drop.correct_droplet_position()` if you are correcting after a hardware mismatch, because that also appends a correction frame to the plan.

## Inspect Droplets

```python
droplet = system.advanced_drop.droplets.get_droplet(1)
info = system.advanced_drop.droplets.get_droplet_info(1)
summary = system.advanced_drop.droplets.get_droplets_summary()
```

`get_droplet_info()` returns a dictionary with the current position, target position, shape, priority, and vital-space settings.

`get_droplets_summary()` returns all droplets plus whether the `AdvancedDrop` object currently has a plan.

## Delete and Reset

```python
system.advanced_drop.droplets.delete_droplet(1)
system.advanced_drop.clear()
```

`delete_droplet()` removes the droplet object. It does not automatically rewrite old plan frames.

`clear()` resets the droplet list and the current plan. Use it when starting a new protocol in the same Python session.

## Push a Manual Frame

`push_frame()` paints the currently active droplets into a new plan frame and tags it as an event.

```python
system.advanced_drop.push_frame(
    event_type="manual_hold",
    event_data={"reason": "stabilize before imaging"},
)
```

This is useful when a protocol needs an explicit hold or synchronization point between operations.
