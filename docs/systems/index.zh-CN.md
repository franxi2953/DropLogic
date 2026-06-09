# 系统和模块

DropLogic 围绕一个简单想法组织：一个 **系统** 由一组可复用 **模块** 组合而成。

这种结构让库保持灵活。同一套规划和控制层可以在仿真环境和真实硬件之间复用，而每个系统只连接自己真正需要的模块。

## 核心概念

### 系统

**系统** 是暴露给用户的顶层机器定义。

例子：

- `Simulator`：用于开发和测试的纯软件环境。
- `DMLite`：专注于电极矩阵的真实硬件系统。硬件平台来自 [Acxel](https://www.acxel.com/)；本库提供 Python 集成层。

系统通常提供：

- 基于 `DropSystem` 的控制表面
- 状态和命令 routing
- 该机器可用的模块集合
- 相关时的 visualizers
- `AdvancedDrop` 规划和执行

### 模块

**模块** 是系统内部的能力块。

例子：

- 电极矩阵
- 相机
- 显微镜
- XY stage
- 温度控制器
- 光照

模块给系统提供物理或仿真能力。可以把一个系统理解为一组经过选择的模块 bundle。

### 版本

**版本** 是模块背后的具体实现。

例子：

- `CameraV1`
- `DMLite`
- `TemperatureV1`

这让 DropLogic 能保持稳定的高层 API，同时替换低层 driver 或设备专属实现。

`DMLite` 这个名字有意出现在两个地方：

- 作为 **系统**：`droplogic.hardware.DMLite`，也就是用户实例化的顶层 DropLogic 机器
- 作为 **模块版本**：`droplogic.hardware.modules.electrode_matrix.versions.DMLite`，也就是该系统内部使用的 Acxel 专属电极矩阵实现

因此当前 `DMLite` 系统就是一个真实系统，由一个主要硬件模块组成：Acxel `DMLite` 电极矩阵适配器。

## 系统如何构建

实际中，一个 DropLogic 系统通常由这些部分 remix 而成：

1. 共享的 `DropSystem` base class
2. 一个或多个硬件或仿真模块
3. 可选 visualizers
4. `AdvancedDrop` 规划层

这意味着两个系统可以共享大部分行为，只在暴露的模块和实例化的版本上不同。

## 真实系统 vs 仿真系统

DropLogic 同时支持：

- **仿真系统**：适合无硬件时进行规划、调试和开发
- **真实系统**：把同样的概念绑定到物理设备

对于真实系统，文档包含 **模块** 子章节，让硬件组成保持明确。

## 当前系统

### Simulator

`Simulator` 是最适合入门的环境，用于开发、算法验证和可视化调试。

### DMLite

`DMLite` 是围绕 Acxel 电极矩阵构建的最小真实系统。它的硬件表面比大型机器小，因为目前主要由一个硬件模块组成，但仍保持同样的 DropLogic 架构。

## 扩展库

理解 systems 和 modules 后，在 DropLogic 中创建新机器主要就是重组现有模块，并在需要时添加新模块。

实现指南见本节末尾的 **创建新系统**。
