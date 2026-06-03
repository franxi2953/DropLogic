# DMLite

`DMLite` is a minimal real system in this library centered on a physical electrode matrix from [Acxel](https://www.acxel.com/). The hardware is provided by Acxel; this repository contains the Python system and module adapter used to control it.

The name `DMLite` is used both for the top-level DropLogic system and for the electrode-matrix module version inside that system. In this section, **the system** means `droplogic.hardware.DMLite`; **the module version** means `droplogic.hardware.modules.electrode_matrix.versions.DMLite`.

Compared with larger machines, it keeps the hardware surface intentionally small. That makes it a useful reference system for understanding how a real machine can be assembled from modules in this library.

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

Because `DMLite` is a real hardware-backed system, its module composition is documented explicitly in the pages nested under this section. At the moment, that composition is intentionally simple: the system consists of the Acxel `DMLite` electrode-matrix module plus the shared DropLogic planning and visualization layers.
