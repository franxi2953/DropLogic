# DMLite Module: Electrode Matrix

The `DMLite` system is currently built around a single real hardware module: the electrode matrix.

`DMLite` is an Acxel hardware platform. This page documents the Python adapter around that hardware; the hardware itself is not part of this repository. See [Acxel](https://www.acxel.com/) for the hardware provider.

## Role in the System

This module is responsible for translating system-level electrode commands into the concrete low-level implementation used by Acxel DMLite hardware.

At the system level, `DMLite` uses the module to:

- apply matrix updates
- set operating voltage
- deactivate electrodes
- push droplet-related actuation patterns

## Layering

The electrode stack is intentionally split in layers:

1. **System layer**: `droplogic.hardware.DMLite`
2. **Module wrapper**: `droplogic.hardware.modules.electrode_matrix.ElectrodeMatrixModule`
3. **Version implementation**: `droplogic.hardware.modules.electrode_matrix.versions.DMLite`

This separation is important because it keeps the system definition clean while allowing the underlying hardware implementation to change later.

## Backends

The `DMLite` system currently uses one electrode-matrix backend:

| Backend | Where it runs | Use case |
| --- | --- | --- |
| `DMLite` | Windows | Native control through the vendor DLL/SDK. |

On Windows, the system uses the native `DMLite` backend:

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

On macOS, `DMLite()` currently raises a clear runtime error. macOS hardware support is intentionally left as a placeholder until a supported macOS backend exists.

## Why a Module Wrapper Exists

The wrapper is not just extra structure. It makes it possible to:

- standardize the public API seen by systems
- swap implementations later without rewriting the system
- keep version-specific details out of the high-level machine definition

## Current Behavior

In the current DMLite setup, the module exposes operations such as:

- `set_chip(...)`
- `set_voltage(...)`
- `deactivate_all()`
- `set_droplet(...)`
- `set_droplets(...)`
- `send_ascii_command(...)`

These are enough for the system to drive the electrode surface while letting `AdvancedDrop` stay focused on planning rather than on hardware protocol details.

## Design Takeaway

This page is a good example of the DropLogic pattern:

- the **system** defines what the machine is
- the **module** defines what capability block is present
- the **version** defines how that capability is implemented on a specific device
