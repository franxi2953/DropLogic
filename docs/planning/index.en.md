# Planning

Planning is the layer that turns droplet intent into executable matrix frames.

In DropLogic, this is mostly handled by `AdvancedDrop`: it stores droplets, builds plans, checks constraints, and hands frames to the executor.

## Main Pieces

- **AdvancedDrop**: user-facing planning API attached to each system as `system.advanced_drop`
- **Droplet state**: droplets, positions, targets, shapes, events, and frame metadata
- **Movement planning**: SIPP-based routing for collision-aware multi-droplet movement
- **Operations**: movement, splitting, merging, mixing, and reservoir extraction
- **PlanExecutor**: runtime execution of planned frames against a system

## Public Workflow

Most scripts follow the same shape:

```python
from droplogic.hardware.simulator import Simulator

system = Simulator(log_level="INFO")
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(10, 10), target=(30, 40), width=2, height=2)
ad.move(mode="sipp")

ad.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    save_to_file="runs/simple_plan.pkl",
)
```

`AdvancedDrop` builds the plan. `PlanExecutor` executes and records it. Visualizers show or capture what the executor is doing.

## Typical Flow

```python
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2,
    height=2,
)

system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

The planner should stay hardware-agnostic. Hardware-specific behavior belongs in systems and modules; planning should only reason about frames, droplets, constraints, and execution timing.
