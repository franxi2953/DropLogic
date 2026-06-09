# 规划

规划层把液滴意图转换成可执行的矩阵 frames。

在 DropLogic 中，这主要由 `AdvancedDrop` 处理：它保存液滴、构建计划、检查约束，并把 frames 交给 executor。

## 主要组成

- **AdvancedDrop**：面向用户的规划 API，在每个系统中通过 `system.advanced_drop` 暴露
- **液滴状态**：液滴、位置、目标、形状、事件和 frame metadata
- **移动规划**：基于 SIPP 的 routing，用于避免碰撞的多液滴移动
- **操作**：移动、分裂、合并、混合和 reservoir extraction
- **PlanExecutor**：把计划好的 frames 在系统上运行的 runtime 执行层

## 公共工作流

大多数脚本都遵循类似结构：

```python
from droplogic.hardware.simulator import Simulator

system = Simulator(log_level="INFO")
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(10, 10), target=(30, 40), width=2, height=2)
ad.move(mode="sipp")

ad.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    save_to_file="runs/simple_plan.pkl",
)
```

`AdvancedDrop` 构建计划。`PlanExecutor` 执行并记录计划。可视化工具显示或捕获 executor 正在做的事情。

## 典型流程

```python
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2,
    height=2,
)

system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

规划器应保持与硬件无关。硬件相关行为属于 systems 和 modules；规划层只应处理 frames、液滴、约束和执行 timing。
