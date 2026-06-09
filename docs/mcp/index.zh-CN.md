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
droplogic-mcp --transport stdio --load-system simulator
```

远程 MCP client 或长期运行的本地 daemon 使用 HTTP transport：

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --load-system simulator
```

默认情况下 server 只能加载 simulator。真实硬件必须显式启用：

```bash
droplogic-mcp --allow-real-hardware --load-system dmlite
```

raw state writes 和 raw module operations 默认也被禁用：

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools --load-system boxmini
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

### Droplet And Planning Tools

用于定义液滴和调用 planning functions：

| Tool | 用途 |
| --- | --- |
| `create_droplet` | 创建一个液滴 |
| `add_droplets` | 创建多个液滴 |
| `delete_droplet` | 从逻辑液滴列表删除液滴 |
| `update_droplet_target` | 规划前更改目标 |
| `update_droplet_position` | 校正逻辑当前位置 |
| `droplets_summary` | 检查所有液滴 |
| `advanced_drop_call` | 调用白名单 `AdvancedDrop` method |
| `plan_summary` | 检查 frame count、events、trajectories 和结果 |
| `save_protocol` | 将当前 plan 和 droplets 保存到 pickle |

`advanced_drop_call` 暴露 `move`、`reservoir_extraction`、`isometric_split`、`mix`、`merge`、`verify_droplets`、`detect_condensates`、`correct_droplet_position`、`clear` 和 `push_frame` 等方法。

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
| `execute_until_breakpoint` | 阻塞直到下一个 breakpoint 或 plan 完成 |

录制仍属于 `PlanExecutor`，因此视频会与执行 frames 保持同步。

### Visualizer And Frame Tools

当 agent 需要查看当前状态时使用：

| Tool | 用途 |
| --- | --- |
| `visualizer_status` | 检查 matrix 和 streamer 是否可用 |
| `visualizer_frame` | 返回当前 frame 的 base64 或保存到磁盘 |
| `visualizer_snapshot` | 保存 snapshot 文件 |
| `visualizer_call` | 调用白名单 visualizer method |
| `start_visualizer` | 在支持时启动 visualizer window |
| `stop_visualizer` | 停止 visualizer window |

MCP server 不是视频流服务器。agents 可以轮询 `visualizer_frame` 获取当前 frames。

### Vision Tools

Vision tools 既直接暴露，也可通过 `advanced_drop_call` 使用：

| Tool | 用途 |
| --- | --- |
| `verify_droplets` | 检查某个 plan frame 的液滴位置 |
| `detect_condensates` | 从当前 imaging setup 运行 condensate detection |

无 live imaging 时可以使用 debug mode。

## Safety

真实硬件加载、unsafe tools 和 raw state mutation 都需要显式 flags。保持这个边界很重要：agent 应尽量通过 high-level planning tools 控制实验，而不是直接写底层硬件状态。
