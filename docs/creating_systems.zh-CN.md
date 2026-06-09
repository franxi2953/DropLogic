# 创建新系统

本指南提供实现新 DropLogic 系统的起点。它总结了 `Simulator` 和 Acxel-backed `DMLite` adapter 等实现中的主要模式，并展示如何围绕共享 `DropSystem` base 重新组合 modules 来构建新机器。

`DMLite` 和 `BOXMini` 是 Acxel 硬件平台。本仓库包含围绕受支持设备的 Python adapters 和 orchestration code；不包含供应商硬件或原生 runtime assets。硬件提供商信息请看 [Acxel](https://www.acxel.com/)。

## 快速开始

1. **复制模板**：
   ```bash
   cp droplogic/hardware/template/hardware_template.py droplogic/hardware/my_hardware.py
   ```

2. **重命名 class**：
   ```python
   class MyHardware(HardwareTemplate):  # Inherit from DropSystem Base
   ```

3. **按硬件定制**。

4. **测试实现**：
   ```python
   hardware = MyHardware()
   hardware.visualizers.matrix.start()
   ```

## 模板结构

- **DropSystem Base Class**：queue-based command processing、state management 和 logging。
- **Hardware Modules**：camera、microscope、XY stage、electrode matrix、temperature 等。
- **Visualizers**：自动设置 `MatrixVisualizer` 和 `StreamerVisualizer`。
- **AdvancedDrop**：内置 SIPP planning 和 execution capabilities。

## 基础 Setup

```python
from ..base import DropSystem

class MyHardware(DropSystem):
    def __init__(self, config_file="config.json", log_level="INFO"):
        super().__init__(config_file=config_file)
        
        # Add your custom initialization here
        # self.my_custom_module = MyCustomModule(self)
        
        from ..utils.advanced_drop import AdvancedDrop
        self.advanced_drop = AdvancedDrop(self)
```

## 初始化硬件模块

根据系统需要注入模块，并与配置中的 version 匹配：

```python
from .modules.camera import CameraModule
from .modules.xy_stage import XYStageModule
from .modules.electrode_matrix import ElectrodeMatrixModule

self.camera = CameraModule(self, self.state.get("camera_settings", {}).get("version", "CameraV1"))
self.xy_stage = XYStageModule(self, self.state.get("xy_stage", {}).get("version", "XYStageV1"))
self.electrode_matrix = ElectrodeMatrixModule(
    self, None, 128, 128, version="DMLite"
)
```

## 命令处理

为硬件专属 commands 添加 routing：

```python
def _process_hardware_command(self, path: str, value: Any, priority: Priority):
    try:
        if path.startswith("electrode_matrix."):
            return self._process_electrode_command(path, value)
        elif path.startswith("my_device."):
            return self._process_my_device_command(path, value)
        else:
            self.logger.warning(f"Unknown command path: {path}")
            return False
    except Exception as e:
        self.logger.error(f"Hardware command failed: {e}")
        return False
```

## Cleanup 和资源管理

在 `close()` 中确保干净关闭硬件：

```python
def close(self):
    if getattr(self, "_closed", False):
        return

    self._closed = True
    self.logger.info("Closing MyHardware")
    super().close()
```

## 最佳实践

1. 遵循现有实现的命名约定。
2. 使用合适的 logging levels。
3. 优雅处理硬件异常，避免主线程崩溃。
4. 先用 simulator 测试，再切换到真实硬件。
5. 在 `config.json` 中记录硬件专属参数。
6. 为硬件通信失败实现恰当的错误恢复。

## 参考实现

- **BOXMini** (`box_mini1.py`)：包含 camera、microscope 和 XY stage 的 Acxel 硬件系统 adapter。
- **Simulator** (`simulator.py`)：只用于仿真的环境，模拟电极矩阵行为。
