# MCP Server

DropLogic MCP server 令 AI agents 可以透過 Model Context Protocol 操作函式庫，同時將硬件所有權保留喺一個本地 Python process 入面。

當你希望 agent 檢查目前系統、建立同修改液滴 plans、執行 protocols、喺 breakpoints 暫停、讀取 visualizer frames，或者運行 droplet verification / condensate detection 等 vision checks 時，可以使用佢。

## 點解存在

普通 DropLogic 腳本係直接 Python 程式：

```python
from droplogic.hardware.simulator import Simulator

system = Simulator()
system.advanced_drop.droplets.create_droplet(1, (5, 5), (20, 20))
system.advanced_drop.move()
system.advanced_drop.executor.start()
```

MCP server 將同一個函式庫包裝成 agent 可以調用嘅 tools。關鍵邊界係：agent 同 server 溝通，server 擁有唯一 live `DropSystem`。

咁可以避免多個 notebooks、agents 或 scripts 爭用同一套 hardware queues、state lock、visualizers 或 `PlanExecutor`。

## 安裝

MCP 支援係可選嘅，所以 core library 預設唔安裝 agent-server dependencies。

由倉庫根目錄運行：

```bash
pip install -e ".[agent]"
```

呢個 extra 會安裝 `mcp` package，並啟用 `droplogic-mcp` 命令。

## 運行 Server

本地 desktop MCP client 使用 `stdio`：

```bash
droplogic-mcp --transport stdio --load-system simulator
```

遠程 MCP client 或長期運行嘅本地 daemon 使用 HTTP transport：

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --load-system simulator
```

預設情況下 server 只可以載入 simulator。真實硬件必須明確啟用：

```bash
droplogic-mcp --allow-real-hardware --load-system dmlite
```

raw state writes 同 raw module operations 預設亦被停用：

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools --load-system boxmini
```

`--allow-unsafe-tools` 只應該喺有人監督嘅除錯中使用。

## 核心架構

MCP 層刻意保持好薄：

| 層 | 作用 |
| --- | --- |
| `droplogic.mcp.server` | MCP transport、tools、resources 同 CLI entrypoint |
| `droplogic.mcp.runtime` | 擁有一個 `DropSystem`，套用 safety gates，序列化輸出 |
| `DropSystem` | Simulator、DMLite、BOXMini 或其他系統 |
| `AdvancedDrop` | 建立液滴並構建 plans |
| `PlanExecutor` | 執行 plans、處理 breakpoints、保存 protocols、錄製影片 |
| Visualizers | 向 agent 提供 matrix 同 streamer frames |

agent 通常應該透過 `AdvancedDrop` 同 `PlanExecutor` 控制實驗，而唔係寫任意矩陣。

## Tool Groups

### Runtime Tools

用於載入系統同檢查 server：

| Tool | 用途 |
| --- | --- |
| `load_system` | 載入 `simulator`、`dmlite` 或 `boxmini` |
| `close_system` | 關閉目前系統 |
| `runtime_status` | 返回 system、executor、plan 同 droplet status |
| `health_check` | 檢查 queue workers、executor state、module busy state 同 last error |
| `restart_system` | 失敗後關閉並重新載入系統 |
| `capabilities` | 列出目前 agent-facing functions |
| `read_state` | 讀取全部 state 或 dotted path |
| `emergency_stop` | 停止執行、清空 queues，並可選關閉電極 |

`capabilities()` 係 agent 嘅最佳第一步，因為可用模組取決於已載入嘅系統。

### Droplet And Planning Tools

用於定義液滴同調用 planning functions：

| Tool | 用途 |
| --- | --- |
| `create_droplet` | 建立一個液滴 |
| `add_droplets` | 建立多個液滴 |
| `delete_droplet` | 從邏輯液滴列表刪除液滴 |
| `update_droplet_target` | 規劃前更改目標 |
| `update_droplet_position` | 修正邏輯目前位置 |
| `droplets_summary` | 檢查所有液滴 |
| `advanced_drop_call` | 調用白名單 `AdvancedDrop` method |
| `plan_summary` | 檢查 frame count、events、trajectories 同結果 |
| `save_protocol` | 將目前 plan 同 droplets 保存到 pickle |

`advanced_drop_call` 暴露 `move`、`reservoir_extraction`、`isometric_split`、`mix`、`merge`、`verify_droplets`、`detect_condensates`、`correct_droplet_position`、`clear` 同 `push_frame` 等方法。

### Execution Tools

用於控制 `PlanExecutor`：

| Tool | 用途 |
| --- | --- |
| `start_plan` | 開始執行目前 plan |
| `pause_plan` | 暫停執行 |
| `resume_plan` | 恢復執行 |
| `stop_plan` | 停止執行 |
| `executor_status` | 檢查目前 frame、總 frames、進度同 breakpoints |
| `add_breakpoint` | 到達 frame 時暫停 |
| `execute_until_breakpoint` | 阻塞直到下一個 breakpoint 或 plan 完成 |

錄影仍然屬於 `PlanExecutor`，所以影片會同執行 frames 保持同步。

### Visualizer And Frame Tools

當 agent 需要查看目前狀態時使用：

| Tool | 用途 |
| --- | --- |
| `visualizer_status` | 檢查 matrix 同 streamer 是否可用 |
| `visualizer_frame` | 返回目前 frame 嘅 base64 或保存到磁碟 |
| `visualizer_snapshot` | 保存 snapshot 檔案 |
| `visualizer_call` | 調用白名單 visualizer method |
| `start_visualizer` | 支援時啟動 visualizer window |
| `stop_visualizer` | 停止 visualizer window |

MCP server 唔係影片串流伺服器。agents 可以輪詢 `visualizer_frame` 取得目前 frames。

### Vision Tools

Vision tools 既直接暴露，亦可以透過 `advanced_drop_call` 使用：

| Tool | 用途 |
| --- | --- |
| `verify_droplets` | 檢查某個 plan frame 嘅液滴位置 |
| `detect_condensates` | 由目前 imaging setup 運行 condensate detection |

冇 live imaging 時可以使用 debug mode。

## Safety

真實硬件載入、unsafe tools 同 raw state mutation 都需要明確 flags。保持呢個邊界好重要：agent 應盡量透過 high-level planning tools 控制實驗，而唔係直接寫底層硬件狀態。
