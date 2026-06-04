# Getting Started

## Installation

As **DropLogic** is a standard library, users can easily install it directly using `pip`:

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

For development (editable mode):
```bash
pip install -e .
```

### DMLite on macOS

`DMLite` native hardware control is currently Windows-only because the Acxel SDK is distributed as Windows DLLs. On macOS, `DMLite()` raises a clear runtime error. Use `Simulator` on macOS while DMLite support remains a placeholder.

!!! warning "Hardware Drivers Requirement"
    To control physical devices (like the Electrode Matrix, XY Stage, or Camera), you must install the **DropLogic Runtime Installer** for your target hardware. This runtime package is distributed separately from the Python library by the hardware provider or platform maintainer.
    
    Additionally, for camera support (MVS modules), you must download and install the official Hikrobot Machine Vision Software from their website:
    [https://www.hikrobotics.com/en/machinevision/service/download/](https://www.hikrobotics.com/en/machinevision/service/download/)

## Basic Usage: Systems and Modules

To start using **DropLogic**, you first need to understand two key concepts: **Systems** and **Modules**.

- **System:** A system represents the entire hardware machine or simulation environment. The library includes a pure software `simulator.py` system and adapter systems for Acxel hardware such as `box_mini1` / `BOXMini` and `DMLite`. `BOXMini` and `DMLite` are Acxel platforms; this repository only contains the Python integration layer. See [Acxel](https://www.acxel.com/) for the hardware provider.
- **Module:** A system is essentially a collection of Modules. A module controls a specific hardware component, like the electrode matrix, the camera, or the temperature controllers. Modules can have different **versions/implementations** (e.g. `CameraV1` or `MicroscopeV2`), allowing you to swap physical hardware components while maintaining the same DropLogic syntax.

*(For a more structured explanation of systems, modules, and how new machines are assembled, see the **Systems** section in the navigation menu, ending with our [Creating New Systems](creating_systems.md) guide).*

For details on the default state file, what each system needs, and how to keep machine-specific calibration local, see [Configuration](configuration.md).

Here is a quick example of how to start using **DropLogic** with the **Simulator** system within your scripts:

```python
from droplogic.hardware.simulator import Simulator

# 1. Initialize the system
system = Simulator(log_level="INFO")

# 2. Command your modules (e.g. create a 2x2 droplet and move it)
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2, height=2
)

# 3. Ask the system to plan and execute the movement
system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

## Included Examples

For more complex real-world continuous use cases, check out the scripts inside the `examples/` directory included in the repository, or open the new **Getting Started > Example Scripts** subsection in the navigation menu for the full code and direct GitHub links:

- `examples/simulator_example.py`: A pure software demonstration of a 128x128 virtual matrix that spawns 20 droplets and sets them into an infinite continuous-routing loop.
- `examples/DMLite_example.py`: Runs the exact same infinite routing loop but binding directly to Acxel `DMLite` AM-EWOD hardware through DropLogic's adapter layer. It sets a higher `frame_delay` to accommodate hardware voltage actuation delays and fluid physics.
