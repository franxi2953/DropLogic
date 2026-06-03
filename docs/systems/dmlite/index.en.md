# DMLite

`DMLite` is a minimal real DropLogic system centered on a physical electrode matrix.

Compared with larger machines, it keeps the hardware surface intentionally small. That makes it a useful reference system for understanding how a real DropLogic machine is assembled from modules.

## What It Includes

The current `DMLite` system includes:

- the `ElectrodeMatrixModule`
- a `MatrixVisualizer`
- the `AdvancedDrop` planning layer

It does **not** currently bundle camera, microscope, temperature, or lighting modules.

## Why It Is Important

`DMLite` shows the core pattern for a real system:

- inherit from `DropSystem`
- load the machine state from configuration
- instantiate the required hardware modules
- route high-level state updates into module commands
- keep the planning layer independent from the hardware driver details

In other words, it is a small but real example of the DropLogic system architecture.

## Hardware Focus

This system is focused on electrode actuation:

- setting matrix state
- updating operating voltage
- passing matrix changes to the low-level implementation

The concrete hardware implementation sits behind the module layer, so the system stays readable and replaceable.

## Typical Entry Point

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

## Modules

Because `DMLite` is a real hardware-backed system, its module composition is documented explicitly in the pages nested under this section.
