# DMLite

`DMLite` 是本库中的一个最小真实系统，围绕 [Acxel](https://www.acxel.com/) 的物理电极矩阵构建。硬件由 Acxel 提供；本仓库包含用于控制它的 Python 系统和模块适配器。

`DMLite` 这个名字在两个层级上使用：顶层 DropLogic 系统，以及该系统内部的电极矩阵模块版本。在本节中，**系统** 指 `droplogic.hardware.DMLite`；**模块版本** 指 `droplogic.hardware.modules.electrode_matrix.versions.DMLite`。

与更大的机器相比，它刻意保持较小的硬件表面。这让它成为理解真实机器如何由本库模块组装而成的有用参考系统。

## 包含什么

当前 `DMLite` 系统包括：

- `ElectrodeMatrixModule`
- `MatrixVisualizer`
- `AdvancedDrop` 规划层

它目前**不**捆绑相机、显微镜、温度或光照模块。

## 为什么重要

`DMLite` 展示了真实系统的核心模式：

- 继承 `DropSystem`
- 从配置加载机器状态
- 实例化必需的硬件模块
- 将高层状态更新路由到模块命令
- 让规划层独立于硬件 driver 细节

换句话说，它是 DropLogic 系统架构的一个小而真实的例子。

## 硬件重点

这个系统专注于电极驱动：

- 设置矩阵状态
- 更新工作电压
- 把矩阵变化传递给低层实现

具体硬件实现位于模块层之后，因此系统本身保持可读、可替换。

## 典型入口

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

## 模块

因为 `DMLite` 是真实硬件支持的系统，它的模块组成会在本节下的嵌套页面中明确记录。目前这个组成刻意保持简单：系统由 Acxel `DMLite` 电极矩阵模块，以及 DropLogic 共享的规划和可视化层组成。
