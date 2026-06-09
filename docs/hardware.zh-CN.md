# 硬件说明

本文档中提到的 `DMLite` 或 `BOXMini` 指 Acxel 硬件平台。本仓库只包含围绕受支持硬件的 Python 适配代码；供应商硬件和原生 runtime assets 不在源码树中。硬件提供商信息请看 [Acxel](https://www.acxel.com/)。

DropLogic 的硬件层由系统和模块组成：

- **系统**：完整机器或仿真环境，例如 `Simulator`、`DMLite` 或 `BOXMini`。
- **模块**：机器中的能力块，例如电极矩阵、相机、XY stage、光照或温度控制。
- **版本**：某个模块面向具体硬件的实现。

这种结构让高层 droplet API 保持稳定，同时把供应商协议、SDK 和原生 runtime 细节限制在较小的实现层中。
