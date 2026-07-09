# MCP Server

DropLogic MCP server 让 AI agents 通过 Model Context Protocol 操作库，同时把硬件所有权保留在一个本地 Python process 中。

当你希望 agent 检查当前系统、创建和修改液滴 plans、执行 protocols、在 breakpoints 暂停、读取 visualizer frames，或运行 droplet verification / condensate detection 等 vision checks 时，可以使用它。

## 为什么存在

普通 DropLogic 脚本是直接 Python 程序：

```python
from droplogic.hardware.simulator import Simulator

system = Simulator()
system.advanced_drop.droplets.create_droplet(1, (5, 5), (20, 20))
system.advanced_drop.move()
system.advanced_drop.executor.start()
```

MCP server 将同一个库包装成 agent 可调用的 tools。关键边界是：agent 与 server 通信，server 拥有唯一 live `DropSystem`。

这避免多个 notebooks、agents 或 scripts 争用同一套 hardware queues、state lock、visualizers 或 `PlanExecutor`。

## 安装

MCP 支持是可选的，因此 core library 默认不安装 agent-server dependencies。

从仓库根目录运行：

```bash
pip install -e ".[agent]"
```

该 extra 会安装 `mcp` package，并启用 `droplogic-mcp` 命令。

## 运行 Server

本地 desktop MCP client 使用 `stdio`：

```bash
droplogic-mcp --transport stdio
```

远程 MCP client 或长期运行的本地 daemon 使用 HTTP transport：

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765
```

默认情况下 server 只能加载 simulator。真实硬件必须显式启用：

```bash
droplogic-mcp --allow-real-hardware
```

raw state writes 和 raw module operations 默认也被禁用：

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools
```

`--allow-unsafe-tools` 只应在有人监督的调试中使用。

## 核心架构

MCP 层刻意保持很薄：

| 层 | 作用 |
| --- | --- |
| `droplogic.mcp.server` | MCP transport、tools、resources 和 CLI entrypoint |
| `droplogic.mcp.runtime` | 拥有一个 `DropSystem`，应用 safety gates，序列化输出 |
| `DropSystem` | Simulator、DMLite、BOXMini 或其他系统 |
| `AdvancedDrop` | 创建液滴并构建 plans |
| `PlanExecutor` | 执行 plans、处理 breakpoints、保存 protocols、录制视频 |
| Visualizers | 向 agent 提供 matrix 和 streamer frames |

agent 通常应通过 `AdvancedDrop` 和 `PlanExecutor` 控制实验，而不是写任意矩阵。

## Tool Groups

### Runtime Tools

用于加载系统和检查 server：

| Tool | 用途 |
| --- | --- |
| `load_system` | 加载 `simulator`、`dmlite` 或 `boxmini` |
| `close_system` | 关闭当前系统 |
| `runtime_status` | 返回 system、executor、plan 和 droplet status |
| `health_check` | 检查 queue workers、executor state、module busy state 和 last error |
| `restart_system` | 失败后关闭并重新加载系统 |
| `capabilities` | 列出当前 agent-facing functions |
| `read_state` | 读取全部 state 或 dotted path |
| `emergency_stop` | 停止执行、清空 queues，并可选关闭电极 |

`capabilities()` 是 agent 的最佳第一步，因为可用模块取决于加载的系统。

### Droplet Definition Tools

用于定义和编辑逻辑液滴集合：

| Tool | 用途 |
| --- | --- |
| `clear_droplet_state` | 清空逻辑液滴和 plan frames，并可选择重置 executor cursor |
| `create_droplet` | 创建一个液滴 |
| `add_droplets` | 创建多个液滴 |
| `delete_droplet` | 从逻辑液滴列表删除液滴 |
| `update_droplet_target` | 规划前更改目标 |
| `update_droplet_targets` | 规划前批量更改目标 |
| `update_droplet_position` | 校正逻辑当前位置 |
| `droplets_summary` | 检查所有液滴 |

`update_droplet_target` 和 `update_droplet_targets` 会在修改目标前验证最终 active-droplet layout。如果结果包含 `target_validation.ok=false`，目标不会被修改；调用 `plan_move` 前先检查 `blocking_issues`、`warnings` 和 `suggested_targets`。在已加载 runtime 中开始干净的逻辑协议时使用 `clear_droplet_state(reset_executor=true)`；它只重置 AdvancedDrop 状态，不关闭物理电极，所以需要关电极时先调用 `emergency_stop(deactivate_electrodes=true)`。

### Planning Primitive Tools

这些 tools 会把一个逻辑 planning primitive 添加到当前 plan，但不会执行硬件。agent 应先 plan，再检查 `plan_summary`，然后通过 `PlanExecutor` 明确执行。

| Tool | 用途 |
| --- | --- |
| `plan_activation_frame` | 为当前液滴添加一个 activation frame |
| `plan_move` | 为 target 与当前位置不同的液滴规划移动 |
| `plan_reservoir_extraction` | 从 reservoir 规划液滴抽取 |
| `plan_isometric_split` | 规划 isometric split |
| `plan_mix` | 规划 mixing sequence |
| `plan_merge` | 规划 droplet merge |
| `planning_job_status` | 检查 background planning job 及推荐等待时间 |
| `cancel_planning_job` | 请求取消 background planning job |
| `plan_summary` | 检查 frame count、events、trajectories 和结果 |
| `save_protocol` | 将当前 plan 和 droplets 保存到 pickle |

大规模或困难规划应使用 `background=true`，然后调用 `planning_job_status()`，不要让一个 MCP request 长时间阻塞。job 仍在运行时，status response 会包含 `recommended_wait_seconds`、`next_check_after_seconds` 和 `recommended_status_call`；按该间隔等待后再检查，不要反复立即轮询。通用 `advanced_drop_call` / `list_advanced_drop_methods` 只在 `--allow-unsafe-tools` 下作为 debug surface 注册。

在 DMLite 和 BOXMini 等真实硬件上，`plan_move` 会拒绝单次调用中超过 10 个 active moving droplets。把移动拆成已执行的 5-10 个液滴批次；密集布局、交叉、长路径或 2 x 2 液滴优先使用 5 个一批。

`plan_merge` 会通过 core AdvancedDrop validation API 预检查 merge hub。不安全的 hub 返回 `ok=false` 和 `primitive_validation.merge_target_validation`，并可能包含 `blocker_parking_suggestions`、`suggested_target` 或 `recommended_action`，用于先移动阻挡液滴或在附近 hub 重试。

### Execution Tools

用于控制 `PlanExecutor`：

| Tool | 用途 |
| --- | --- |
| `start_plan` | 开始执行当前 plan |
| `pause_plan` | 暂停执行 |
| `resume_plan` | 恢复执行 |
| `stop_plan` | 停止执行 |
| `executor_status` | 检查当前 frame、总 frames、进度和 breakpoints |
| `add_breakpoint` | 到达 frame 时暂停 |
| `start_execute_until_breakpoint` | 启动 background wait，直到 breakpoint 或 plan 完成 |
| `execution_wait_status` | 轮询执行等待状态 |
| `cancel_execution_wait` | 只取消等待 job，不停止物理执行 |

录制仍属于 `PlanExecutor`，因此视频会与执行 frames 保持同步。

### State And Scene Tools

当 agent 或外部 app 需要结构化状态而不是图像时使用：

| Tool | 用途 |
| --- | --- |
| `state_summary` | 读取摘要状态，避免展开大型数组 |
| `read_state` | 读取一个小型精确 state path |
| `matrix_summary` | 返回紧凑的 active matrix ranges；zeros 隐式表示 |
| `execution_scene` | 返回紧凑的 plan/executor/matrix/droplet scene state |

`read_large_state` 只在 server 使用 `--allow-large-state-tools` 启动时注册，仅用于有人监督的调试。

### Visualizer And Frame Tools

当 agent 需要查看当前状态时使用：

| Tool | 用途 |
| --- | --- |
| `visualizer_status` | 检查 matrix 和 streamer 是否可用 |
| `visualizer_frame` | 返回当前 frame 的 base64 或保存到磁盘 |
| `start_visualizer` | 在支持时启动 visualizer window |
| `stop_visualizer` | 停止 visualizer window |
| `bring_visualizer_to_front` | 在支持时将 visualizer window 带到前台 |

MCP server 不是视频流服务器。agents 可以轮询 `visualizer_frame` 获取当前 frames。

### Vision Tools

| Tool | 用途 |
| --- | --- |
| `verify_droplets` | 检查某个 plan frame 的液滴位置 |
| `detect_condensates` | 从当前 imaging setup 运行 condensate detection |

无 live imaging 时可以使用 debug mode。

### Temperature Tools

| Tool | 用途 |
| --- | --- |
| `temperature_hold` | 设置单个目标温度，等待/保持，并返回紧凑 samples |
| `start_temperature_routine` | 后台运行一组 temperature hold steps |
| `temperature_routine_status` | 检查当前或上一次 temperature routine |
| `cancel_temperature_routine` | 取消当前 temperature routine |
| `start_melting_curve_capture` | 每个温度 step hold 后捕获图像 |
| `melting_curve_capture_status` | 检查当前或上一次 melting-curve capture |
| `cancel_melting_curve_capture` | 取消当前 melting-curve capture |

Temperature holds 和 routines 默认使用 `tolerance_c=0.2`。runtime 会等待硬件命令队列稳定，确认目标没有回退，并在等待或 hold 期间被其他目标替换时让该 step 失败。

## Safety

真实硬件加载、unsafe tools 和 raw state mutation 都需要显式 flags。保持这个边界很重要：agent 应尽量通过 high-level planning tools 控制实验，而不是直接写底层硬件状态。
