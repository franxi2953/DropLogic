# 建立新系統

本指南提供實現新 DropLogic 系統嘅起點。佢總結咗 `Simulator` 同 Acxel-backed `DMLite` adapter 等實現中嘅主要模式，並展示點樣圍繞共享 `DropSystem` base 重組 modules 去建立新機器。

`DMLite` 同 `BOXMini` 係 Acxel 硬件平台。本倉庫包含圍繞受支援設備嘅 Python adapters 同 orchestration code；唔包含供應商硬件或原生 runtime assets。硬件供應商資料請睇 [Acxel](https://www.acxel.com/)。

## 快速開始

1. **複製模板**：
   ```bash
   cp droplogic/hardware/template/hardware_template.py droplogic/hardware/my_hardware.py
   ```

2. **重命名 class**：
   ```python
   class MyHardware(HardwareTemplate):  # Inherit from DropSystem Base
   ```

3. **按硬件自訂**。

4. **測試實現**：
   ```python
   hardware = MyHardware()
   hardware.visualizers.matrix.start()
   ```

## 模板結構

- **DropSystem Base Class**：queue-based command processing、state management 同 logging。
- **Hardware Modules**：camera、microscope、XY stage、electrode matrix、temperature 等。
- **Visualizers**：自動設定 `MatrixVisualizer` 同 `StreamerVisualizer`。
- **AdvancedDrop**：內置 SIPP planning 同 execution capabilities。

## 基礎 Setup

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

## 初始化硬件模組

根據系統需要注入模組，並同設定入面嘅 version 匹配：

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

## 命令處理

為硬件專屬 commands 加入 routing：

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

## Cleanup 同資源管理

喺 `close()` 入面確保乾淨關閉硬件：

```python
def close(self):
    if getattr(self, "_closed", False):
        return

    self._closed = True
    self.logger.info("Closing MyHardware")
    super().close()
```

## 最佳實踐

1. 遵循現有實現嘅命名約定。
2. 使用合適嘅 logging levels。
3. 優雅處理硬件異常，避免主線程崩潰。
4. 先用 simulator 測試，再切換到真實硬件。
5. 喺 `config.json` 中記錄硬件專屬參數。
6. 為硬件通信失敗實現合適嘅錯誤恢復。

## 參考實現

- **BOXMini** (`box_mini1.py`)：包含 camera、microscope 同 XY stage 嘅 Acxel 硬件系統 adapter。
- **Simulator** (`simulator.py`)：只用於模擬嘅環境，模擬電極矩陣行為。
