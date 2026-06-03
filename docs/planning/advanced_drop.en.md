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

DropLogic uses 0-indexed matrix coordinates as `(row, col)` tuples.
This is intentionally the same ordering used by NumPy arrays: `matrix[row, col]`.

Do not read AdvancedDrop positions as Cartesian `(x, y)`. If you are thinking in
image or stage coordinates, the closest mental mapping is:

- `row` is the vertical matrix index, similar to `y`.
- `col` is the horizontal matrix index, similar to `x`.
- therefore a Cartesian-looking point `(x, y)` usually becomes `(row, col) = (y, x)`.

In the logical matrix convention, `(0, 0)` is the top-left electrode of the
unrotated matrix. Increasing `row` moves downward through the matrix. Increasing
`col` moves rightward through the matrix.

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

Examples:

```python
origin = (10, 20)  # row 10, column 20
target = (10, 30)  # same row, 10 columns to the right

shape = {(0, 0), (0, 1), (1, 0), (1, 1)}  # 2x2 footprint
absolute_cells = {
    (origin[0] + dr, origin[1] + dc)
    for dr, dc in shape
}
```

Low-level hardware helpers may expose their own indexing rules. For example,
some simulator electrode setters are 1-indexed because they mimic hardware
commands. AdvancedDrop plans, droplets, trajectories, breakpoints, and debugger
positions are 0-indexed `(row, col)`.

## Matrix Visualizer Orientation

The planner and plan debugger use the logical matrix convention above. The
interactive `MatrixVisualizer` displays that logical matrix rotated by default:

- default display rotation: `90` degrees clockwise.
- logical `(0, 0)` appears near the top-right of the matrix visualizer.
- increasing `row` moves left on the default visualizer display.
- increasing `col` moves down on the default visualizer display.

This default matches the orientation used by the Acxel DMLite/BOXMini-style
electrode matrix setup that originally drove the visualizer design. It is only a
display transform: it does not change how you write plans, create droplets, or
address electrodes in AdvancedDrop.

To use an unrotated display where logical `(0, 0)` appears top-left:

```python
system.visualizers.matrix.set_matrix_rotation(0)
```

Supported display rotations are `0`, `90`, `180`, and `270` clockwise degrees.
Clicks in the matrix visualizer are converted back to logical `(row, col)` before
callbacks receive them, so `set_electrode_click_callback()` always receives the
same coordinate convention used by AdvancedDrop.

`bg_rotation_deg` is separate. It applies a small correction to a background
camera image, not to the logical electrode matrix:

```python
system.visualizers.matrix.bg_rot = 0.0  # background image only
```

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
