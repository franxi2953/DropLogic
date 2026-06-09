# Hardware

This Python library wraps communication and integration code for several open and closed hardware devices used in digital microfluidics:

When this documentation names `DMLite` or `BOXMini`, those names refer to Acxel hardware platforms. This repository only contains Python adapter code around supported hardware; vendor hardware and native runtime assets are not part of the source tree. See [Acxel](https://www.acxel.com/) for the hardware provider.

- **Vision Systems**: Integration with MVS cameras (`mvs_camera`) and AI/YOLO algorithms for droplet detection.
- **XY Platforms**: Stage controllers (`nmc_controller`).
- **Thermal Control**: Peltier systems and thermocouples.
- **Microscopes**: Focus control and image capture.
- **Electrode Matrix**: Driving adapters for platforms like Acxel `DMLite`.
