# 入門

## 安裝

**DropLogic** 係標準 Python 函式庫，可以直接用 `pip` 安裝：

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

做開發時用 editable mode：
```bash
pip install -e .
```

關於各平台原生硬件 setup，包括 DMLite runtime 檔案同 Linux/Raspberry Pi 嘅 `libusb` 依賴，請睇 [安裝](installation.md)。

!!! warning "硬件驅動要求"
    要控制實體設備（例如電極矩陣、XY stage 或相機），請為目標平台安裝 **DropLogic Runtime Installer** 或相應嘅原生 runtime assets。呢啲 runtime 套件由硬件供應商或平台維護者另外分發，唔包含喺 Python 函式庫入面。
    
    另外，要啟用相機支援（MVS 模組），需要由 Hikrobot 官網下載並安裝官方 Machine Vision Software：
    [https://www.hikrobotics.com/en/machinevision/service/download/](https://www.hikrobotics.com/en/machinevision/service/download/)

## 基本用法：系統同模組

開始用 **DropLogic** 之前，先理解兩個核心概念：**系統（Systems）** 同 **模組（Modules）**。

- **系統（System）：** 一個系統代表成部硬件機器或者模擬環境。函式庫包括純軟件嘅 `simulator.py` 系統，亦包括面向 Acxel 硬件嘅平台適配系統，例如 `box_mini1` / `BOXMini` 同 `DMLite`。`BOXMini` 同 `DMLite` 係 Acxel 平台；本倉庫只包含 Python 集成層。硬件供應商資料請睇 [Acxel](https://www.acxel.com/)。
- **模組（Module）：** 一個系統本質上由多個模組組成。模組控制特定硬件組件，例如電極矩陣、相機或者溫度控制器。模組可以有唔同 **版本或實現**（例如 `CameraV1` 或 `MicroscopeV2`），咁就可以更換實體組件，同時保持同一套 DropLogic 語法。

（想更有結構咁理解系統、模組同新機器點樣組裝，請睇導航入面嘅 **系統** 部分，最後有 [建立新系統](creating_systems.md) 指南。）

關於預設狀態檔案、每個系統需要嘅設定，以及點樣將機器專屬校準留喺本地，請睇 [設定](configuration.md)。

下面係使用 **Simulator** 系統嘅快速範例：

```python
from droplogic.hardware.simulator import Simulator

# 1. Initialize the system
system = Simulator(log_level="INFO")

# 2. Command your modules (e.g. create a 2x2 droplet and move it)
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2, height=2
)

# 3. Ask the system to plan and execute the movement
system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

## 內置範例

如果想睇更複雜嘅連續工作流，可以查看倉庫入面嘅 `examples/` 目錄，或者喺導航打開 **入門 > 範例腳本**，入面有完整程式碼同 GitHub 連結：

- `examples/simulator_example.py`：純軟件示範，喺 128x128 虛擬矩陣入面生成 20 個大液滴，並令佢哋喺無限連續 routing loop 入面運行。
- `examples/DMLite_example.py`：運行同一個無限 routing loop，但直接綁定到 Acxel `DMLite` AM-EWOD 硬件嘅 DropLogic 適配層。佢用較長嘅 `frame_delay`，以適應真實硬件嘅電壓驅動延遲同流體物理。
