<div class="dl-home">
  <div class="dl-home__mark" aria-hidden="true">
    <img src="assets/droplets-mark.svg" alt="">
  </div>
  <p class="dl-home__eyebrow">Python Library for Digital Microfluidics</p>
  <h1 class="dl-home__title">DropLogic</h1>
  <p class="dl-home__copy">
    Minimal, deployment-ready control for digital microfluidics: systems, planning, execution, visualization, and utilities in one library.
  </p>
  <div class="dl-home__actions">
    <a class="md-button dl-button" href="getting_started/">Getting Started</a>
    <a class="md-button dl-button" href="systems/">Systems</a>
    <a class="md-button dl-button" href="planning/">Planning</a>
    <a class="md-button dl-button" href="visualization/">Visualization</a>
    <a class="md-button dl-button" href="mcp/">Agent Control</a>
  </div>
</div>

!!! warning "Platform Compatibility"
    **Native DMLite hardware control is currently Windows-only.** The library relies on proprietary hardware DLLs provided by hardware vendors. On macOS, `DMLite()` intentionally raises a clear runtime error for now; use the `Simulator` there until a supported macOS backend exists.

Welcome to the documentation for **DropLogic**, a Python library for digital microfluidics (DMF) control. It keeps scripts readable by wrapping systems, modules, planning, execution, and visualization behind a shared Python interface. Instead of wrestling with different hardware interfaces, you work with common classes for electrode matrices, cameras, positioning systems, and droplet plans.

## What will you find here?
<ul class="dl-home__list">
  <li><strong><a href="getting_started/">Getting Started</a></strong>: Installation, basic usage, and first steps.</li>
  <li><strong><a href="configuration/">Configuration</a></strong>: The repository `config.json`, required fields, and local machine-specific calibration.</li>
  <li><strong><a href="repository_structure/">Architecture Map</a></strong>: A detailed look into the structure of the repository and how modules are organized.</li>
  <li><strong><a href="systems/">Systems</a></strong>: The structure of systems, modules, versions, and how to create new machines.</li>
  <li><strong><a href="planning/">Planning</a></strong>: AdvancedDrop, droplet plans, SIPP movement, and executor-driven runtime.</li>
  <li><strong><a href="visualization/">Visualization</a></strong>: Matrix and streamer visualizers, snapshots, and synchronized recording.</li>
  <li><strong><a href="mcp/">Agent Control</a></strong>: MCP server tools for agents to plan, execute, inspect frames, and run vision checks.</li>
  <li><strong><a href="utilities/">Utilities</a></strong>: Hardware helpers, drop vision, debugging, and diagnostics.</li>
</ul>
