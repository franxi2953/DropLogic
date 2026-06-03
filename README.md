<p align="center">
  <img src="docs/assets/droplets-mark.svg" alt="DropLogic logo" width="120" />
</p>

<h1 align="center">DropLogic</h1>

<p align="center">
  <strong>Minimal, deployment-ready control for digital microfluidics.</strong>
</p>

<p align="center">
  <a href="https://franxi2953.github.io/DropLogic/"><img alt="Docs" src="https://img.shields.io/badge/docs-online-111111?style=flat-square"></a>
  <img alt="Version" src="https://img.shields.io/badge/version-v1.0.0-111111?style=flat-square">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-111111?style=flat-square"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.8%2B-111111?style=flat-square">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows-111111?style=flat-square">
</p>

<p align="center">
  <a href="https://franxi2953.github.io/DropLogic/">Documentation</a>
  ·
  <a href="https://franxi2953.github.io/DropLogic/getting_started/">Getting Started</a>
  ·
  <a href="https://franxi2953.github.io/DropLogic/systems/">Systems</a>
  ·
  <a href="https://franxi2953.github.io/DropLogic/planning/">Planning</a>
  ·
  <a href="https://franxi2953.github.io/DropLogic/visualization/">Visualization</a>
</p>

<p align="center">
  <img src="docs/assets/readme-affiliations.svg" alt="PhD project at the University of Cambridge, Occhipinti Group, and Di Michele Lab" width="760" />
</p>

DropLogic is a Python library for digital microfluidics (DMF): systems, modules, SIPP-based droplet planning, synchronized execution, visualization, and hardware-facing utilities in one library.

The project began as **Fran Quero's PhD project at the University of Cambridge**, developed across the **Occhipinti Group** and the **Di Michele Lab**. It is designed to make DMF control scripts readable while keeping the hardware-specific details isolated inside systems and modules.

> DMLite and BOXMini are hardware platforms from [Acxel](https://www.acxel.com/). DropLogic provides Python integration layers around supported hardware; it does not manufacture those devices.

## Quick Start

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

## What DropLogic Provides

- **Systems**: high-level machines such as `Simulator` and `DMLite`.
- **Modules**: reusable hardware components and version-specific implementations.
- **AdvancedDrop**: public planning API for droplets, movement, splitting, merging, mixing, and correction.
- **PlanExecutor**: synchronized frame execution, breakpoints, pause/resume, protocol saving, and video recording.
- **Visualizers**: matrix and live-stream views for execution, snapshots, and diagnostics.
- **Utilities**: calibration, coordinate conversion, drop vision, runtime checks, and plan debugging.

## Documentation

Full documentation is available at:

**[franxi2953.github.io/DropLogic](https://franxi2953.github.io/DropLogic/)**

Start with the [Getting Started Guide](https://franxi2953.github.io/DropLogic/getting_started/), then move to [Systems](https://franxi2953.github.io/DropLogic/systems/) and [Planning](https://franxi2953.github.io/DropLogic/planning/).

## Runtime Note

For native control of physical hardware devices, an additional DropLogic Runtime Installer may be required. The runtime installer is distributed separately from the Python library so that vendor SDKs and native DLLs do not live in the public source repository.

## License

DropLogic is released under the [MIT License](LICENSE).
