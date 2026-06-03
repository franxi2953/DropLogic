<div class="dl-home">
  <div class="dl-home__mark" aria-hidden="true">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" fill="none">
      <circle cx="34" cy="48" r="24" fill="white" stroke="#111111" stroke-width="4"/>
      <circle cx="62" cy="48" r="24" fill="white" stroke="#111111" stroke-width="4"/>
      <path d="M48 28.5A24 24 0 0 0 48 67.5A24 24 0 0 0 48 28.5Z" fill="#111111"/>
    </svg>
  </div>
  <p class="dl-home__eyebrow">Digital Microfluidics Control Platform</p>
  <h1 class="dl-home__title">DropLogic</h1>
  <p class="dl-home__copy">
    Minimal, deployment-ready control for digital microfluidics: systems, planning, execution, visualization, and utilities in one library.
  </p>
  <div class="dl-home__actions">
    <a class="md-button dl-button" href="getting_started/">Getting Started</a>
    <a class="md-button dl-button" href="systems/">Systems</a>
    <a class="md-button dl-button" href="planning/">Planning</a>
    <a class="md-button dl-button" href="visualization/">Visualization</a>
  </div>
</div>

!!! warning "Platform Compatibility"
    **Currently, DropLogic only supports Windows.** The library relies on proprietary hardware DLLs (Dynamic Link Libraries) provided by manufacturers, which are inherently Windows-exclusive. Usage on macOS or Linux is not supported at this time and will result in import and runtime errors.

Welcome to the official documentation for **DropLogic**! We built this platform to make digital microfluidics (DMF) control as straightforward as possible. Instead of wrestling with different hardware interfaces, DropLogic abstracts hardware modules—like electrode matrices, cameras, and positioning systems—into a single unified library, providing common classes specifically tailored to digital microfluidic applications. Whether you're moving a few droplets or automating an entire lab workflow, this tool gives you the high-level control you need to focus on your experiments.

## What will you find here?
<ul class="dl-home__list">
  <li><strong><a href="getting_started/">Getting Started</a></strong>: Installation, basic usage, and first steps.</li>
  <li><strong><a href="repository_structure/">Architecture Map</a></strong>: A detailed look into the structure of the repository and how modules are organized.</li>
  <li><strong><a href="systems/">Systems</a></strong>: The structure of systems, modules, versions, and how to create new machines.</li>
  <li><strong><a href="planning/">Planning</a></strong>: AdvancedDrop, droplet plans, SIPP movement, and executor-driven runtime.</li>
  <li><strong><a href="visualization/">Visualization</a></strong>: Matrix and streamer visualizers, snapshots, and synchronized recording.</li>
  <li><strong><a href="utilities/">Utilities</a></strong>: Calibration, drop vision, hardware helpers, debugging, and diagnostics.</li>
  <li><strong><a href="api/">API</a></strong>: Generated Python documentation from the source tree.</li>
</ul>
