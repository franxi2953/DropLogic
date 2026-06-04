# MCP Server

The DropLogic MCP server lets AI agents operate the library through the Model Context Protocol while keeping ownership of the hardware inside one local Python process.

Use it when you want an agent to inspect the current system, create and modify droplet plans, execute protocols, pause at breakpoints, read visualizer frames, or run vision checks such as droplet verification and condensate detection.

## Why It Exists

Normal DropLogic scripts are direct Python programs:

```python
from droplogic.hardware.simulator import Simulator

system = Simulator()
system.advanced_drop.droplets.create_droplet(1, (5, 5), (20, 20))
system.advanced_drop.move()
system.advanced_drop.executor.start()
```

The MCP server wraps the same library in tools that an agent can call. The important boundary is that the agent talks to the server, and the server owns the single live `DropSystem`.

This avoids multiple notebooks, agents, or scripts competing for the same hardware queues, state lock, visualizers, or `PlanExecutor`.

## Installation

MCP support is optional so the core library does not install agent-server dependencies by default.

From the repository root:

```bash
pip install -e ".[agent]"
```

The extra installs the `mcp` package and enables the `droplogic-mcp` command.

## Running The Server

For a local desktop MCP client, use `stdio`:

```bash
droplogic-mcp --transport stdio --load-system simulator
```

For a remote MCP client or a long-running local daemon, use the HTTP transport:

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --load-system simulator
```

By default, the server can load the simulator only. Real hardware must be enabled explicitly:

```bash
droplogic-mcp --allow-real-hardware --load-system dmlite
```

Raw state writes and raw module operations are also disabled by default:

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools --load-system boxmini
```

Use `--allow-unsafe-tools` only for supervised debugging.

## Core Architecture

The MCP layer is deliberately thin:

| Layer | Role |
| --- | --- |
| `droplogic.mcp.server` | MCP transport, tools, resources, and CLI entrypoint |
| `droplogic.mcp.runtime` | Owns one `DropSystem`, applies safety gates, serializes outputs |
| `DropSystem` | Simulator, DMLite, BOXMini, or another system |
| `AdvancedDrop` | Creates droplets and builds plans |
| `PlanExecutor` | Executes plans, handles breakpoints, saves protocols, records video |
| Visualizers | Provide matrix and streamer frames to the agent |

The agent should normally control experiments through `AdvancedDrop` and `PlanExecutor`, not by writing arbitrary matrices.

## Tool Groups

The server exposes several groups of tools.

### Runtime Tools

Use these to load systems and inspect the server:

| Tool | Purpose |
| --- | --- |
| `load_system` | Load `simulator`, `dmlite`, or `boxmini` |
| `close_system` | Close the current system |
| `runtime_status` | Return system, executor, plan, and droplet status |
| `capabilities` | List the currently available agent-facing functions |
| `read_state` | Read all state or a dotted path such as `electrode_matrix.voltage` |
| `emergency_stop` | Stop execution, clear queues, and optionally deactivate electrodes |

`capabilities()` is the best first call for an agent because available modules depend on the loaded system.

### Droplet And Planning Tools

Use these to define droplets and call planning functions:

| Tool | Purpose |
| --- | --- |
| `create_droplet` | Create one droplet |
| `add_droplets` | Create many droplets |
| `delete_droplet` | Remove a droplet from the logical droplet list |
| `update_droplet_target` | Change a droplet target before planning |
| `update_droplet_position` | Correct the logical current position |
| `droplets_summary` | Inspect all droplets |
| `list_advanced_drop_methods` | Show whitelisted `AdvancedDrop` methods |
| `advanced_drop_call` | Call a whitelisted `AdvancedDrop` method |
| `plan_summary` | Inspect frame count, events, trajectories, and planning result |
| `save_protocol` | Save the current plan and droplets to a pickle file |

`advanced_drop_call` currently exposes public planning and correction methods such as `move`, `reservoir_extraction`, `isometric_split`, `mix`, `merge`, `verify_droplets`, `detect_condensates`, `correct_droplet_position`, `clear`, and `push_frame`.

Example agent call:

```json
{
  "method": "move",
  "arguments": {
    "mode": "sipp",
    "remove_duplicate_frames": false
  }
}
```

### Execution Tools

Use these to control `PlanExecutor`:

| Tool | Purpose |
| --- | --- |
| `start_plan` | Start executing the current plan |
| `pause_plan` | Pause execution |
| `resume_plan` | Resume execution |
| `stop_plan` | Stop execution |
| `executor_status` | Inspect current frame, total frames, progress, and breakpoints |
| `add_breakpoint` | Pause when a frame is reached |
| `remove_breakpoint` | Remove one breakpoint |
| `clear_breakpoints` | Remove all breakpoints |
| `execute_until_breakpoint` | Block until the next breakpoint or plan completion |

Typical execution call:

```json
{
  "frame_delay": 0.5,
  "verify_positions": false,
  "enable_visualizers": false,
  "record_matrix": true,
  "matrix_filename": "runs/matrix.mp4"
}
```

Recording still belongs to `PlanExecutor`, so recorded videos stay synchronized to executed frames.

### Visualizer And Frame Tools

Use these when an agent needs to see the current state:

| Tool | Purpose |
| --- | --- |
| `visualizer_status` | Inspect matrix and streamer availability |
| `visualizer_frame` | Return a current frame as base64 and/or save it to disk |
| `visualizer_snapshot` | Save a snapshot file |
| `visualizer_call` | Call a whitelisted visualizer method |
| `start_visualizer` | Start a visualizer window when supported |
| `stop_visualizer` | Stop a visualizer window |

For matrix state:

```json
{
  "visualizer": "matrix",
  "frame_source": "snapshot",
  "max_width": 640,
  "include_base64": true
}
```

For live camera or microscope state:

```json
{
  "visualizer": "streamer",
  "frame_source": "processed",
  "max_width": 640,
  "include_base64": true
}
```

`StreamerVisualizer` frame sources can include `raw`, `processed`, and `snapshot` depending on whether live frames are available. The simulator only has the matrix visualizer.

The MCP server is not a video streaming server. Agents can poll `visualizer_frame` for current frames. If continuous high-frame-rate streaming is needed later, it should be added as an auxiliary endpoint while keeping commands inside MCP.

### Vision Tools

Vision tools are exposed both directly and through `advanced_drop_call`.

| Tool | Purpose |
| --- | --- |
| `verify_droplets` | Check droplet positions for a plan frame |
| `detect_condensates` | Run condensate detection from the current imaging setup |

Debug mode can be used without live imaging:

```json
{
  "frame_idx": 10,
  "droplet_ids": [1, 2],
  "debug": true
}
```

For real vision workflows, the loaded system must provide the relevant camera, microscope, stage, and detector support.

### Module Tools

Use module tools for system-specific hardware modules:

| Tool | Purpose |
| --- | --- |
| `list_system_modules` | Show loaded modules and whitelisted methods |
| `module_call` | Call a whitelisted module method |
| `system_call` | Call a whitelisted loaded-system method |

Examples of exposed module surfaces include light intensity, camera exposure, microscope channel, temperature setpoints, XY stage positions, and capacitive feedback.

Raw electrode matrix methods such as `set_chip` are considered unsafe and require `--allow-unsafe-tools`. The private vendor command path, including `send_ascii_command`, is not exposed.

## Example Agent Workflow

A simple simulator workflow looks like this:

```text
1. load_system(system="simulator")
2. capabilities()
3. create_droplet(droplet_id=1, origin=[5, 5], target=[20, 20])
4. advanced_drop_call(method="move", arguments={"mode": "sipp"})
5. visualizer_frame(visualizer="matrix", frame_source="snapshot")
6. start_plan(frame_delay=0.5, verify_positions=false)
7. executor_status()
8. save_protocol(output_path="runs/example.pkl")
```

For real hardware, keep the same shape but start the server with `--allow-real-hardware` and use the appropriate system name.

## Safety Model

The server has three intentional restrictions:

| Restriction | Reason |
| --- | --- |
| Real hardware is disabled by default | Prevent accidental actuation by an agent |
| Raw state writes are disabled by default | Keep normal workflows routed through public library APIs |
| Private vendor commands are not exposed | Keep the public library at the documented API boundary |

`emergency_stop()` is always available after a system is loaded. It stops the executor, clears queued hardware commands, and can deactivate the electrode matrix.

## CLI Reference

```bash
droplogic-mcp --help
```

Important flags:

| Flag | Meaning |
| --- | --- |
| `--transport stdio` | Local MCP client over standard input/output |
| `--transport streamable-http` | HTTP MCP server |
| `--host` / `--port` | HTTP bind address |
| `--config` | Path to `config.json` |
| `--load-system` | Optional startup system |
| `--allow-real-hardware` | Permit DMLite or BOXMini loading |
| `--allow-unsafe-tools` | Permit raw state writes and raw module tools |
| `--snapshots-dir` | Where visualizer snapshots are saved |
