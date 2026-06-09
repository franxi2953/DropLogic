# Simulator

`Simulator` 是 DropLogic 中默认的纯软件系统。当你想验证协议、测试规划逻辑，或在不连接物理硬件的情况下检查矩阵行为时，它是最好的起点。

![Executor 录制的 simulator GIF，显示多个液滴的协同 SIPP routing](../assets/systems/simulator-executor-demo.gif)

这个 demo 来自一个真实 `Simulator` plan，由启用矩阵录制的 `PlanExecutor` 执行。点表示液滴，细灰色路径表示计划路线。

## 它提供什么

模拟器目前包含：

- 仿真电极矩阵
- 仿真 XY stage 接口
- `MatrixVisualizer`
- `AdvancedDrop` 规划层

这使它适合大多数早期开发，尤其是迭代液滴 routing 或调试状态转换时。

## 为什么重要

模拟器保留了真实机器使用的同一套系统级结构：

- 它继承自 `DropSystem`
- 它通过相同的 queue-based 机制 route 命令
- 它通过熟悉的 attributes 暴露系统组件

这意味着针对模拟器写的协议通常只需要很少修改就能迁移到真实系统。

## 主要用例

- 不连接硬件时开发
- 调试规划和执行
- 可视化验证液滴移动
- 测试状态转换和命令 routing

## 当前范围

模拟器刻意保持轻量。它专注于算法开发最有用的部分：

- 电极激活状态
- XY 位置状态
- 矩阵可视化

它不会尝试模拟真实机器的所有物理效应。

## 典型入口

```python
from droplogic.hardware.simulator import Simulator

system = Simulator(log_level="INFO")
```

之后，你可以像在真实系统脚本中一样使用标准 `advanced_drop` 工作流和矩阵 visualizer。
