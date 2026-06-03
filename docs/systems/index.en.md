# Systems and Modules

DropLogic is organized around a simple idea: a **system** is built by composing a set of reusable **modules**.

This structure keeps the library flexible. The same planning and control layer can be reused across simulation environments and real hardware, while each system only wires together the modules it actually needs.

## Core Concepts

### System

A **system** is the top-level machine definition exposed to the user.

Examples:

- `Simulator`: a software-only environment for development and testing.
- `DMLite`: a real hardware-backed system focused on the electrode matrix. The hardware platform is from [Acxel](https://www.acxel.com/); DropLogic provides the integration layer.

A system usually provides:

- a `DropSystem`-based control surface
- state and command routing
- the set of modules available on that machine
- visualizers, when relevant
- `AdvancedDrop` planning and execution

### Module

A **module** is a capability block inside a system.

Examples:

- electrode matrix
- camera
- microscope
- XY stage
- temperature controller
- lighting

Modules give systems their physical or simulated abilities. A system can be thought of as a curated bundle of modules.

### Version

A **version** is the concrete implementation behind a module.

Examples:

- `CameraV1`
- `DMLite`
- `TemperatureV1`

This lets DropLogic keep a stable high-level API while swapping out the low-level driver or device-specific implementation.

The name `DMLite` appears in two places on purpose:

- as a **system**, `droplogic.hardware.DMLite`, which is the top-level DropLogic machine users instantiate
- as a **module version**, `droplogic.hardware.modules.electrode_matrix.versions.DMLite`, which is the Acxel-specific electrode-matrix implementation used inside that system

So the current `DMLite` system is simply a real system made from one main hardware module: the Acxel `DMLite` electrode-matrix adapter.

## How Systems Are Built

In practice, a DropLogic system is a remix of:

1. the shared `DropSystem` base class
2. one or more hardware or simulated modules
3. optional visualizers
4. the `AdvancedDrop` planning layer

This means two systems can share most of their behavior while differing only in the modules they expose and the versions they instantiate.

## Real vs Simulated Systems

DropLogic supports both:

- **simulated systems**, which are useful for planning, debugging, and development without hardware
- **real systems**, which bind those same concepts to physical devices

For real systems, the documentation includes a **Modules** subsection so the hardware composition is explicit.

## Current Systems

### Simulator

`Simulator` is the simplest environment to start with. It is intended for development, algorithm validation, and visual debugging.

### DMLite

`DMLite` is a minimal real system centered on an Acxel electrode matrix. It exposes a smaller hardware surface than larger machines because it currently consists of one main hardware module, but it keeps the same DropLogic architecture.

## Extending the Library

Once you understand systems and modules, creating a new machine in DropLogic becomes mostly an exercise in recombining existing modules and adding new ones where needed.

See **Creating New Systems** at the end of this section for the implementation guide.
