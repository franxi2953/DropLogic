# Utilities

Utilities are support layers used by systems, planning, hardware integration, and debugging.

They are not the main user-facing workflow, but they make the workflow reliable:

- coordinate conversions and configuration helpers
- droplet and condensate detection
- image capture helpers
- plan debugging
- runtime diagnostics
- logging setup

Most users start with `Systems` and `Planning`, then come here when they need to tune hardware, inspect failures, or integrate new modules.

## What to Use When

- Use **Hardware Utilities** for `config.json`, electrode-stage conversion, pixel-micron conversion, and simple volume estimates.
- Use **Drop Vision** for direct droplet or condensate detection outside the visualizer.
- Use **Debugging and Diagnostics** for saved-plan inspection, runtime doctor checks, logging, and executor timeout reports.
