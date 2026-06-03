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
