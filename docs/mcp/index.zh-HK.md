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
droplogic-mcp --transport stdio
```

遠程 MCP client 或長期運行嘅本地 daemon 使用 HTTP transport：

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765
```

預設情況下 server 只可以載入 simulator。真實硬件必須明確啟用：

```bash
droplogic-mcp --allow-real-hardware
```

raw state writes 同 raw module operations 預設亦被停用：

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools
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
| `runtime_status` | 返回適合輪詢嘅 system、queue、executor、plan 同 droplet status |
| `health_check` | 檢查 queue workers、executor state、module busy state 同 last error |
| `restart_system` | 失敗後關閉並重新載入系統 |
| `capabilities` | 列出目前 agent-facing functions |
| `read_state` | 讀取全部 state 或 dotted path |
| `emergency_stop` | 停止執行、清空 queues，並可選關閉電極 |

`capabilities()` 係 agent 嘅最佳第一步，因為可用模組取決於已載入嘅系統。載入 BOXMini 時，包括 XY stage 在內嘅所有核心模組都必須成功初始化；載入失敗會關閉部分初始化資源，亦唔會留下可供 caller 使用或自動重啟嘅已載入 system。

`runtime_status()` 預設使用 `detail="compact"`，適合 dashboard 頻密輪詢，即使 planner 正忙亦可以使用。佢唔會啟動 MJPEG stream server。對支援 queue 嘅 system，`system.queue_summary.pending_commands` 係未完成命令總數（包括處理中嘅命令），而 `system.queue_summary.queues` 包含 `CRITICAL`、`HIGH`、`MEDIUM` 同 `LOW` entries，每項提供 `pending_commands`、`worker_alive` 同 `interval_ms`。使用 `detail="full"` 可以查看原始 queue size、last-command error 同 state-save diagnostics。

### Droplet Definition Tools

用於定義同編輯邏輯液滴集合：

| Tool | 用途 |
| --- | --- |
| `clear_droplet_state` | 清空邏輯液滴同 plan frames，並可選擇重置 executor cursor |
| `create_droplet` | 建立一個液滴 |
| `add_droplets` | 建立多個液滴 |
| `delete_droplet` | 從邏輯液滴列表刪除液滴 |
| `update_droplet_target` | 規劃前更改目標 |
| `update_droplet_targets` | 規劃前批量更改目標 |
| `update_droplet_position` | 修正邏輯目前位置 |
| `droplets_summary` | 檢查所有液滴 |

`update_droplet_target` 同 `update_droplet_targets` 會喺修改目標前驗證最終 active-droplet layout。如果結果包含 `target_validation.ok=false`，目標唔會被修改；調用 `plan_move` 前先檢查 `blocking_issues`、`warnings` 同 `suggested_targets`。喺已載入 runtime 中開始乾淨邏輯 protocol 時使用 `clear_droplet_state(reset_executor=true)`；佢只重置 AdvancedDrop 狀態，唔關閉物理電極，所以需要關電極時先調用 `emergency_stop(deactivate_electrodes=true)`。

### Planning Primitive Tools

呢啲 tools 會將一個邏輯 planning primitive 加到目前 plan，但唔會執行硬件。agent 應該先 plan，再檢查 `plan_summary`，然後透過 `PlanExecutor` 明確執行。

| Tool | 用途 |
| --- | --- |
| `plan_activation_frame` | 為目前液滴加入一個 activation frame |
| `plan_move` | 為 target 同目前位置唔同嘅液滴規劃移動 |
| `plan_reservoir_extraction` | 由 reservoir 規劃液滴抽取 |
| `plan_isometric_split` | 規劃 isometric split |
| `plan_mix` | 規劃 mixing sequence |
| `plan_merge` | 規劃 droplet merge |
| `planning_job_status` | 檢查 background planning job 同建議等待時間 |
| `cancel_planning_job` | 要求取消 background planning job |
| `plan_summary` | 檢查 frame count、events、trajectories 同結果 |
| `save_protocol` | 將目前 plan 同 droplets 保存到 pickle |

大型或困難規劃應使用 `background=true`，然後調用 `planning_job_status()`，唔好令一個 MCP request 長時間阻塞。job 仍在運行時，status response 會包含 `recommended_wait_seconds`、`next_check_after_seconds` 同 `recommended_status_call`；按該間隔等候後再檢查，唔好反覆即時輪詢。通用 `advanced_drop_call` / `list_advanced_drop_methods` 只會喺 `--allow-unsafe-tools` 下作為 debug surface 註冊。

喺 DMLite 同 BOXMini 等真實硬件上，`plan_move` 會拒絕單次調用中超過 10 個 active moving droplets。將移動拆成已執行嘅 5-10 個液滴批次；密集 layout、交叉、長路徑或 2 x 2 液滴優先用 5 個一批。

`plan_merge` 會透過 core AdvancedDrop validation API 預檢 merge hub。不安全嘅 hub 返回 `ok=false` 同 `primitive_validation.merge_target_validation`，並可能包含 `blocker_parking_suggestions`、`suggested_target` 或 `recommended_action`，用於先移動阻擋液滴或喺附近 hub 重試。

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
| `start_execute_until_breakpoint` | 啟動 background wait，直到 breakpoint 或 plan 完成 |
| `execution_wait_status` | 輪詢執行等待狀態 |
| `cancel_execution_wait` | 只取消等待 job，唔停止物理執行 |

錄影仍然屬於 `PlanExecutor`，所以影片會同執行 frames 保持同步。

### State And Scene Tools

當 agent 或外部 app 需要結構化狀態而唔係圖像時使用：

| Tool | 用途 |
| --- | --- |
| `state_summary` | 讀取摘要狀態，避免展開大型 arrays |
| `read_state` | 讀取一個細型精確 state path |
| `matrix_summary` | 返回緊湊 active matrix ranges；zeros 隱式表示 |
| `execution_scene` | 返回緊湊 plan/executor/matrix/droplet scene state |

`read_large_state` 只會喺 server 用 `--allow-large-state-tools` 啟動時註冊，只用於有人監督嘅除錯。

### Visualizer And Frame Tools

當 agent 需要查看目前狀態時使用：

| Tool | 用途 |
| --- | --- |
| `visualizer_status` | 檢查 visualizers 並啟動輔助 MJPEG endpoint |
| `visualizer_frame` | 返回目前 frame 嘅 base64 或保存到磁碟 |
| `start_visualizer` | 支援時啟動 visualizer window |
| `stop_visualizer` | 停止 visualizer window |
| `bring_visualizer_to_front` | 支援時將 visualizer window 帶到前台 |

agents 可以輪詢 `visualizer_frame` 取得目前 frames。瀏覽器 client 可以呼叫 `visualizer_status()`，確保輔助 direct-MJPEG endpoint 已運行並取得 matrix 同 streamer URLs；普通 `runtime_status()` 輪詢唔會啟動該 endpoint。硬件命令仍然經 MCP 執行。

### Vision Tools

| Tool | 用途 |
| --- | --- |
| `verify_droplets` | 檢查某個 plan frame 嘅液滴位置 |
| `detect_condensates` | 由目前 imaging setup 運行 condensate detection |

冇 live imaging 時可以使用 debug mode。

### Temperature Tools

| Tool | 用途 |
| --- | --- |
| `temperature_hold` | 設定單個目標溫度，等待/保持，並返回緊湊 samples |
| `start_temperature_routine` | 背景運行一組 temperature hold steps |
| `temperature_routine_status` | 檢查目前或上一次 temperature routine |
| `cancel_temperature_routine` | 取消目前 temperature routine |
| `start_melting_curve_capture` | 每個溫度 step hold 後捕獲圖像 |
| `melting_curve_capture_status` | 檢查目前或上一次 melting-curve capture |
| `cancel_melting_curve_capture` | 取消目前 melting-curve capture |

Temperature holds 同 routines 預設使用 `tolerance_c=0.2`。runtime 會等待硬件命令隊列穩定，確認目標冇回退，並喺等待或 hold 期間被其他目標取代時令該 step 失敗。

## Safety

真實硬件載入、unsafe tools 同 raw state mutation 都需要明確 flags。保持呢個邊界好重要：agent 應盡量透過 high-level planning tools 控制實驗，而唔係直接寫底層硬件狀態。
