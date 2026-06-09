# 实用工具

Utilities 是 systems、planning、hardware integration 和 debugging 使用的支持层。

它们不是主要面向用户的工作流，但会让工作流更可靠：

- 坐标转换和配置 helpers
- 液滴和 condensate 检测
- 图像捕获 helpers
- plan debugging
- runtime diagnostics
- logging setup

大多数用户先从 `Systems` 和 `Planning` 开始，然后在需要调硬件、检查失败或集成新模块时来到这里。

## 什么时候用什么

- 使用 **Hardware Utilities** 处理 `config.json`、电极-stage 转换、pixel-micron 转换和简单体积估算。
- 使用 **Drop Vision** 在 visualizer 外直接做液滴或 condensate 检测。
- 使用 **Debugging and Diagnostics** 检查保存的计划、runtime doctor、logging 和 executor timeout reports。
