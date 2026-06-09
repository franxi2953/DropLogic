# DMLite 模組：電極矩陣

`DMLite` 系統目前圍繞一個真實硬件模組構建：電極矩陣。

`DMLite` 係 Acxel 嘅硬件平台。本頁記錄圍繞該硬件嘅 Python 適配器；硬件本身唔屬於本倉庫。硬件供應商資料請睇 [Acxel](https://www.acxel.com/)。

## 喺系統入面嘅作用

呢個模組負責將系統級電極命令轉換成 Acxel DMLite 硬件使用嘅具體低層實現。

喺系統層，`DMLite` 使用呢個模組去：

- 套用矩陣更新
- 設定工作電壓
- 關閉電極
- 發送同液滴相關嘅驅動 pattern

## 分層

電極 stack 被刻意拆成幾層：

1. **系統層**：`droplogic.hardware.DMLite`
2. **模組 wrapper**：`droplogic.hardware.modules.electrode_matrix.ElectrodeMatrixModule`
3. **版本實現**：`droplogic.hardware.modules.electrode_matrix.versions.DMLite`

呢種分離好重要，因為佢令系統定義保持清晰，同時容許底層硬件實現按 host 平台變化。

## Backends

`DMLite` 系統使用一個 Python backend，並為目前 host 選擇相配嘅原生 runtime：

| Host | Runtime 檔案 | 用途 |
| --- | --- | --- |
| Windows x86_64 | `sdk.dll` | 原生硬件控制。 |
| macOS Apple Silicon | `sdk.dylib` | 原生硬件控制。 |
| Linux x86_64 | `linux-x86_64/sdk.so` | 使用 `libusb` 嘅原生硬件控制。 |
| Raspberry Pi OS 64-bit | `linux-aarch64/sdk.so` | 使用 `libusb` 嘅原生硬件控制。 |
| Raspberry Pi OS 32-bit | `linux-armv7l/sdk.so` | 使用 `libusb` 嘅原生硬件控制。 |

所有受支援平台都使用同一套 Python API：

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

原生 runtime 會由已安裝嘅 DropLogic runtime 資料夾、`DROPLOGIC_RUNTIME_DIR`，或者開發 checkout 入面嘅本地 `vendor_bin/electrode_matrix/dmlite/` 資料夾解析。不受支援嘅 host 或缺失嘅 runtime 檔案會拋出清楚嘅 runtime error。

喺 Linux 同 Raspberry Pi OS 上，運行硬件控制之前請安裝 `libusb-1.0-0`。macOS Apple Silicon 使用 Homebrew `libusb`，除非你嘅 runtime 套件已經包埋佢。

## 點解需要模組 Wrapper

Wrapper 唔只係額外結構。佢令我哋可以：

- 標準化系統見到嘅 public API
- 之後替換實現，而唔需要重寫系統
- 將版本相關細節同高層機器定義隔離

## 目前行為

喺目前 DMLite setup 入面，呢個模組暴露以下操作：

- `set_chip(...)`
- `set_voltage(...)`
- `deactivate_all()`
- `set_droplet(...)`
- `set_droplets(...)`
- `send_ascii_command(...)`

呢啲操作足夠令系統驅動電極表面，同時令 `AdvancedDrop` 專注於規劃，而唔係硬件協議細節。

## 設計要點

呢頁展示咗 DropLogic 嘅核心模式：

- **系統** 定義機器係乜
- **模組** 定義機器具備咩能力區塊
- **版本** 定義該能力喺具體設備上點樣實現
