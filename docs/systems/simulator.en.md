# Simulator

`Simulator` is the default software-only system in DropLogic. It is the best place to start when you want to validate protocols, test planning logic, or inspect matrix behavior without connecting to physical hardware.

## What It Provides

The simulator currently bundles:

- a simulated electrode matrix
- a simulated XY stage interface
- a `MatrixVisualizer`
- the `AdvancedDrop` planning layer

This makes it useful for most early development work, especially when iterating on droplet routing or debugging state transitions.

## Why It Matters

The simulator preserves the same system-level structure used by real machines:

- it derives from `DropSystem`
- it routes commands through the same queue-based mechanism
- it exposes system components through familiar attributes

That means protocols written against the simulator can often be moved to a real system with minimal changes.

## Main Use Cases

- development without hardware attached
- planning and execution debugging
- visual validation of droplet movement
- testing state transitions and command routing

## Current Scope

The simulator is intentionally lightweight. It focuses on the pieces most useful for algorithm development:

- electrode activation state
- XY position state
- matrix visualization

It does not try to emulate every physical effect of a real machine.

## Typical Entry Point

```python
from droplogic.hardware.simulator import Simulator

system = Simulator(log_level="INFO")
```

From there, you can use the standard `advanced_drop` workflow and the matrix visualizer exactly as you would in a system-backed script.
