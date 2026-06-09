# 调试和诊断

调试工具帮助检查 plans、runtime failures 和本地安装问题。

## 主要组件

- `plan_debugger.py`：用于保存 plans 的可视化 frame explorer
- `doctor.py`：检查必需的原生 runtime 文件
- `logging_config.py`：共享 logger setup 和 log-level helpers
- executor timeout reports：breakpoint 执行卡住时写出的诊断 logs

## 代码位置

- `droplogic/utils/debug/plan_debugger.py`
- `droplogic/utils/doctor.py`
- `droplogic/utils/logging_config.py`
- `droplogic/utils/advanced_drop/plan_executor.py`

最有用的调试 artifacts 通常是保存的 plans、executor diagnostics，以及同步 visualizer 输出的 screenshots 或 recordings。

## 保存 Plan 用于调试

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/debug_plan.pkl",
)
```

pickle 保存 `plan` 和 `droplets`。

## 打开 Plan Debugger

从 Python：

```python
from droplogic.utils.debug.plan_debugger import open_explorer

open_explorer("runs/debug_plan.pkl")
```

从命令行：

```bash
python -m droplogic.utils.debug.plan_debugger runs/debug_plan.pkl
```

debugger 是 PyQt UI，用于检查 frames、液滴位置、active droplets、event labels 和可能的 occupancy conflicts。

## 该看什么

- 液滴第一次偏离预期的 frame。
- 失败附近的 event label。
- 该 frame 的 active droplet list。
- 可疑电极上的 body/vital-space overlap。
- split、merge 或 correction events 后的 trajectory discontinuities。

## Breakpoint 调试

```python
executor = system.advanced_drop.executor

executor.add_breakpoint(40)
executor.start(frame_delay=0.5, enable_visualizers=True, save_to_file="runs/breakpoint_debug.pkl")
executor.execute_until_breakpoint_or_raise(label="before merge")
```

到达 breakpoint 后，检查 `executor.status()` 和 `executor.get_droplet_position(...)`，然后 correct、replan 或 resume。

## Runtime Doctor

使用 runtime doctor 检查原生 runtime 文件：

```bash
python -m droplogic.utils.doctor
```

它通过 runtime resolver 检查 native components。常见位置包括 `DROPLOGIC_RUNTIME_DIR`、DropLogic 包旁的 runtime folder、installer path 和平台默认 runtime 目录。

## Logging

```python
from droplogic.utils.logging_config import enable_debug_logging

enable_debug_logging()
```

规划失败时 debug logs 很有用，因为 planner 和 executor 会向共享 DropLogic loggers 写详细信息。
