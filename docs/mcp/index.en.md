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
droplogic-mcp --transport stdio
```

For a remote MCP client or a long-running local daemon, use the HTTP transport:

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765
```

The server starts idle. It does not instantiate a simulator, DMLite, or BOXMini until an agent calls `load_system(...)`.

By default, the server can load the simulator only. Real hardware must be enabled explicitly, but this still does not open hardware at startup:

```bash
droplogic-mcp --allow-real-hardware
```

Raw state writes and raw module operations are also disabled by default:

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools
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
| `health_check` | Check queue workers, executor state, module busy state, and last error |
| `restart_system` | Close and reload the current or requested system after a failure |
| `capabilities` | List the currently available agent-facing functions |
| `read_state` | Read all state or a dotted path such as `electrode_matrix.voltage` |
| `emergency_stop` | Stop execution, clear queues, and optionally deactivate electrodes |

When the server starts, no system is loaded. Use `load_system(...)` to create one, `close_system()` to release it, and `restart_system(...)` only after an observed failure. `capabilities()` is useful after loading because available modules depend on the active system.

### Droplet Definition Tools

Use these to define and edit the logical droplet set:

| Tool | Purpose |
| --- | --- |
| `clear_droplet_state` | Clear logical droplets and plan frames, optionally resetting the executor cursor |
| `create_droplet` | Create one droplet |
| `add_droplets` | Create many droplets |
| `delete_droplet` | Remove a droplet from the logical droplet list |
| `update_droplet_target` | Change a droplet target before planning |
| `update_droplet_targets` | Change many targets before planning |
| `update_droplet_position` | Correct the logical current position |
| `droplets_summary` | Inspect all droplets |

`update_droplet_target` and `update_droplet_targets` validate the proposed final active-droplet layout before mutating targets. If the result contains `target_validation.ok=false`, the targets were not changed; inspect `blocking_issues`, `warnings`, and `suggested_targets` before calling `plan_move`. Use `clear_droplet_state(reset_executor=true)` when starting a clean logical protocol in an already-loaded runtime; it resets AdvancedDrop state, not physical electrodes, so call `emergency_stop(deactivate_electrodes=true)` first when hardware must be turned off.

### Planning Primitive Tools

Use these to add one logical planning primitive to the current plan. They do not execute hardware. The agent should plan, inspect `plan_summary`, then execute deliberately through `PlanExecutor`.

| Tool | Purpose |
| --- | --- |
| `plan_activation_frame` | Append one activation frame for the current droplets |
| `plan_move` | Plan movement for droplets whose targets differ from their current positions |
| `plan_reservoir_extraction` | Plan extraction of droplets from a reservoir |
| `plan_isometric_split` | Plan an isometric split |
| `plan_mix` | Plan a mixing sequence |
| `plan_merge` | Plan droplet merge |
| `planning_job_status` | Poll a background planning job |
| `cancel_planning_job` | Request cancellation of a background planning job |
| `plan_summary` | Inspect frame count, events, trajectories, and planning result |
| `save_protocol` | Save the current plan and droplets to a pickle file |

For large moves or difficult plans, use `background=true` and poll `planning_job_status()` rather than holding one MCP request open.

On real hardware systems such as DMLite and BOXMini, `plan_move` refuses more than 10 active moving droplets in one call. Split movement into executed batches of 5-10 droplets, preferring 5 for dense layouts, crossings, long routes, or 2 x 2 droplets.

`plan_merge` preflights the merge hub through the core AdvancedDrop validation API. Unsafe hubs return `ok=false` with `primitive_validation.merge_target_validation`, and may include `blocker_parking_suggestions`, `suggested_target`, or `recommended_action` for staging blockers or retrying at a nearby hub.

Example move planning call:

```json
{
  "mode": "sipp",
  "remove_duplicate_frames": false,
  "planning_timeout": 1200,
  "background": true
}
```

The generic `advanced_drop_call` and `list_advanced_drop_methods` tools are debug-only surfaces exposed only when the server starts with `--allow-unsafe-tools`.

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
| `start_execute_until_breakpoint` | Start a background wait for breakpoint/plan completion |
| `execution_wait_status` | Poll the active or last execution wait |
| `cancel_execution_wait` | Cancel only the wait job, not physical execution |

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

### State And Scene Tools

Use these when an agent or external app needs structured state rather than an image:

| Tool | Purpose |
| --- | --- |
| `state_summary` | Read summarized system state without expanding large arrays |
| `read_state` | Read one exact small state path |
| `matrix_summary` | Return exact compact active matrix ranges; zeros are implicit |
| `execution_scene` | Return compact plan/executor/matrix/droplet scene state |

`execution_scene` combines the pieces most dashboards need: executor cursor, last applied frame, current plan frame summary, active matrix ranges, current event, droplet positions, targets, bounding boxes, and bounded paths. It uses the same compact matrix encoding as `matrix_summary`, so it is safe for normal MCP use. By default it does not return every droplet cell; request `include_droplet_cells=true` only when a client needs those cells and can handle the extra context.

Use `matrix_summary` when the question is only about the electrode matrix. Use `execution_scene` when the question is about how the matrix relates to the plan, executor frame, events, and droplets. Use `visualizer_frame` only when the agent needs pixels.

Raw 128 x 128 matrix reads are guarded because MCP transports can duplicate data in both text and structured payloads. `read_large_state` is only registered when the server starts with `--allow-large-state-tools`; use that only for supervised debugging.

### Visualizer And Frame Tools

Use these when an agent needs to see the current state:

| Tool | Purpose |
| --- | --- |
| `visualizer_status` | Inspect matrix and streamer availability |
| `visualizer_frame` | Return a current frame as base64 and/or save it to disk |
| `start_visualizer` | Start a visualizer window when supported |
| `stop_visualizer` | Stop a visualizer window |
| `bring_visualizer_to_front` | Bring a visualizer window forward when supported |

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

### Temperature Tools

| Tool | Purpose |
| --- | --- |
| `temperature_hold` | Set one target temperature, wait/hold, and return compact samples |
| `start_temperature_routine` | Run a background sequence of temperature hold steps |
| `temperature_routine_status` | Inspect the active or last temperature routine |
| `cancel_temperature_routine` | Cancel the active temperature routine |
| `start_melting_curve_capture` | Hold each temperature step and capture images after every step |
| `melting_curve_capture_status` | Inspect the active or last melting-curve capture |
| `cancel_melting_curve_capture` | Cancel the active melting-curve capture |

Temperature holds and routines default to `tolerance_c=0.2`. The runtime waits for the hardware command queue to settle, confirms the target did not revert, and fails the step if another target replaces it during the wait or hold.

### Module Tools

Use module tools for system-specific hardware modules:

| Tool | Purpose |
| --- | --- |
| `list_system_modules` | Show loaded modules and whitelisted methods |
| `module_busy_status` | Check whether one module, or all modules, appear busy |
| `module_call` | Debug/fallback call to a whitelisted module method |

Normal workflows should prefer the dedicated stage, light, imaging, temperature, planning, execution, and state tools. `module_call` remains available for supervised low-level reads or operations that do not yet have a dedicated high-level tool.

Raw electrode matrix methods such as `set_chip` are considered unsafe and require `--allow-unsafe-tools`. `system_call`, `set_system_state`, and the generic AdvancedDrop call tools are also debug-only and only registered with `--allow-unsafe-tools`. The private vendor command path, including `send_ascii_command`, is not exposed.

## Busy Modules And Recovery

Hardware modules can be temporarily busy even when the MCP server is healthy. For example, the electrode matrix is busy while `PlanExecutor` is actively executing frames, and the XY stage is busy while stage motion is not complete.

Agents should prefer this pattern before direct module calls:

```text
1. module_busy_status(module="electrode_matrix")
2. If a fallback module call is necessary, call module_call(..., wait_if_busy=true, timeout_seconds=30)
```

`module_call` accepts `wait_if_busy`, `timeout_seconds`, and `poll_interval`:

```json
{
  "module": "xy_stage",
  "method": "get_position",
  "arguments": {"axis": "X"},
  "wait_if_busy": true,
  "timeout_seconds": 10
}
```

If a module is busy and the agent did not ask to wait, the tool returns a structured busy response instead of trying to run over the executor:

```json
{
  "ok": false,
  "busy": true,
  "module": "electrode_matrix",
  "status": {
    "busy": true,
    "reasons": ["PlanExecutor is actively executing frames"]
  }
}
```

Tool errors are not meant to kill the MCP server. Runtime call errors are recorded in `last_error`, and `health_check()` reports whether hardware queue workers are still alive. If the system becomes unhealthy, call `restart_system()` rather than relying on automatic recovery. Automatic restart is intentionally not performed because reinitializing real hardware without supervision can have physical consequences.

## Example Agent Workflow

A simple simulator workflow looks like this:

```text
1. load_system(system="simulator")
2. capabilities()
3. create_droplet(droplet_id=1, origin=[5, 5], target=[20, 20])
4. plan_move(mode="sipp")
5. visualizer_frame(visualizer="matrix", frame_source="snapshot")
6. start_plan(frame_delay=0.5, verify_positions=false)
7. executor_status()
8. save_protocol(output_path="runs/example.pkl")
9. close_system()
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
| `--allow-real-hardware` | Permit DMLite or BOXMini loading |
| `--allow-unsafe-tools` | Permit raw state writes and raw module tools |
| `--snapshots-dir` | Where visualizer snapshots are saved |
