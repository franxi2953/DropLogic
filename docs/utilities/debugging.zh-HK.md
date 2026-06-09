# 除錯同診斷

除錯工具幫助檢查 plans、runtime failures 同本地安裝問題。

## 主要組件

- `plan_debugger.py`：用於保存 plans 嘅可視化 frame explorer
- `doctor.py`：檢查必需嘅原生 runtime 檔案
- `logging_config.py`：共享 logger setup 同 log-level helpers
- executor timeout reports：breakpoint 執行卡住時寫出嘅診斷 logs

## 程式位置

- `droplogic/utils/debug/plan_debugger.py`
- `droplogic/utils/doctor.py`
- `droplogic/utils/logging_config.py`
- `droplogic/utils/advanced_drop/plan_executor.py`

最有用嘅除錯 artifacts 通常係保存嘅 plans、executor diagnostics，以及同步 visualizer 輸出嘅 screenshots 或 recordings。

## 保存 Plan 用於除錯

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/debug_plan.pkl",
)
```

pickle 保存 `plan` 同 `droplets`。

## 打開 Plan Debugger

```python
from droplogic.utils.debug.plan_debugger import open_explorer

open_explorer("runs/debug_plan.pkl")
```

命令行：

```bash
python -m droplogic.utils.debug.plan_debugger runs/debug_plan.pkl
```

debugger 係 PyQt UI，用於檢查 frames、液滴位置、active droplets、event labels 同可能嘅 occupancy conflicts。

## 應該睇咩

- 液滴第一次偏離預期嘅 frame。
- 失敗附近嘅 event label。
- 該 frame 嘅 active droplet list。
- 可疑電極上嘅 body/vital-space overlap。
- split、merge 或 correction events 後嘅 trajectory discontinuities。

## Breakpoint 除錯

```python
executor = system.advanced_drop.executor

executor.add_breakpoint(40)
executor.start(frame_delay=0.5, enable_visualizers=True, save_to_file="runs/breakpoint_debug.pkl")
executor.execute_until_breakpoint_or_raise(label="before merge")
```

到達 breakpoint 後，檢查 `executor.status()` 同 `executor.get_droplet_position(...)`，然後 correct、replan 或 resume。

## Runtime Doctor

用 runtime doctor 檢查原生 runtime 檔案：

```bash
python -m droplogic.utils.doctor
```

佢會透過 runtime resolver 檢查 native components。常見位置包括 `DROPLOGIC_RUNTIME_DIR`、DropLogic 包旁邊嘅 runtime folder、installer path 同平台預設 runtime 目錄。

## Logging

```python
from droplogic.utils.logging_config import enable_debug_logging

enable_debug_logging()
```

規劃失敗時 debug logs 好有用，因為 planner 同 executor 會向共享 DropLogic loggers 寫詳細資訊。
