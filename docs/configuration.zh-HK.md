# 設定

`config.json` 係 DropLogic 系統使用嘅預設狀態檔案。

公開預設檔案位於倉庫根目錄：

```text
config.json
```

如果實例化系統時冇傳入自訂路徑，系統會由目前工作目錄載入 `config.json`。如果由 clone 落嚟嘅倉庫根目錄運行範例，呢個就係倉庫預設檔案：

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite(config_file="config.json")
```

如果腳本由其他目錄運行，請傳入明確路徑。你亦可以保留倉庫預設檔案，並使用一份機器專屬副本：

```python
system = DMLite(config_file="local_config.json")
```

`local_config*.json`、`config.local.json` 同 `calibration_data.json` 已經被 Git 忽略，所以私有機器校準可以留喺本地。

`DMLite` 同 `BOXMini` 係 [Acxel](https://www.acxel.com/) 嘅硬件平台。本倉庫包含圍繞受支援硬件嘅 Python 適配器同共享控制邏輯；供應商硬件同原生 runtime 檔案唔屬於本函式庫。

## 應唔應該提交到倉庫？

應該。基礎 `config.json` 係公開倉庫嘅一部分，因為佢定義預設 schema，亦係函式庫嘅起點。

唔好將 secrets、私有 SDK 路徑、原生函式庫、API keys 或個人憑據放入呢個檔案。供應商 SDK 檔案同原生 runtime assets 會有意排除喺倉庫之外。

## DMLite 需要咩

`DMLite` 只需要 `electrode_matrix` block。

必要欄位：

| 欄位 | 意思 | 預設值 |
| --- | --- | --- |
| `electrode_matrix.rows` | 矩陣行數 | `128` |
| `electrode_matrix.columns` | 矩陣列數 | `128` |
| `electrode_matrix.voltage` | 電極驅動電壓 | `55` |
| `electrode_matrix.version` | 低層矩陣實現 | `DMLite` |
| `electrode_matrix.matrix` | Runtime 矩陣狀態 | 啟動時為 `[]` |

對於目前 DMLite setup，倉庫預設值係合適嘅。系統啟動時會重置 `electrode_matrix.matrix`，所以用戶通常唔需要手動編輯呢個欄位。

`electrode_matrix.version: "DMLite"` 會載入目前 OS 同 CPU 架構相應嘅原生 runtime。支援嘅 DMLite runtimes 包括 Windows x86_64、macOS Apple Silicon、Linux x86_64、Raspberry Pi OS 64-bit 同 Raspberry Pi OS 32-bit。如果未安裝相配嘅 runtime 檔案，`DMLite()` 會拋出清楚錯誤。

## Simulator 需要咩

`Simulator` 使用：

| 欄位 | 意思 |
| --- | --- |
| `electrode_matrix.rows` / `columns` | 模擬矩陣尺寸 |
| `electrode_matrix.voltage` | 模擬電壓值 |
| `xy_stage.position` | mock stage 初始位置 |

只用模擬器嘅工作流，其餘欄位可以保留預設值。

## BOXMini 類型系統需要咩

較大嘅硬件系統會使用更多 block：

| Block | 用途 | 用戶通常編輯 |
| --- | --- | --- |
| `temperature` | 溫度 serial 模組 | `Port`, `version` |
| `xy_stage` | Stage 位置、運動參數同限制 | `safe_limits`, `position`, `motion_params` |
| `camera_settings` | MVS 相機曝光/增益 | `auto_exposure`, `exposure_time`, `gain`, `version` |
| `microscope_settings` | 顯微鏡曝光/通道/serial | `Port`, `current_channel`, `total_channels` |
| `light_settings` | ring/coaxial 光控制器 | `VID`, `PID`, `upled_serial`, intensities, `version` |
| `capacitive_feedback` | feedback 模組選擇 | `version` |

只有當所選系統確實實例化呢啲模組時，先需要填對應 block。

## 校準 Block

`calibration` 包含 runtime 入面用於相機像素轉換、電極/stage 轉換同可選 XY backlash compensation 嘅測量值。

請為每台物理機器同晶片對準狀態量度並更新 `chip_origin`、`inter_row` 同 `inter_column`。

## 實用編輯流程

1. 由倉庫嘅 `config.json` 開始。
2. 複製成 `local_config.json`，用於機器專屬修改。
3. 只更新你要實例化嘅系統實際使用嘅 block。
4. 運行 Simulator 或 DMLite smoke test。
5. 只提交 schema/default 嘅變化，唔提交私有機器校準。
