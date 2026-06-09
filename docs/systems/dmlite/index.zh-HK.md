# DMLite

`DMLite` 係本函式庫入面一個最小真實系統，圍繞 [Acxel](https://www.acxel.com/) 嘅物理電極矩陣構建。硬件由 Acxel 提供；本倉庫包含用嚟控制佢嘅 Python 系統同模組適配器。

`DMLite` 呢個名喺兩個層級使用：頂層 DropLogic 系統，以及該系統入面嘅電極矩陣模組版本。喺本節入面，**系統** 指 `droplogic.hardware.DMLite`；**模組版本** 指 `droplogic.hardware.modules.electrode_matrix.versions.DMLite`。

同更大嘅機器相比，佢刻意保持較細嘅硬件表面。呢點令佢成為理解真實機器點樣由本函式庫模組組裝而成嘅有用參考系統。

## 包含咩

目前 `DMLite` 系統包括：

- `ElectrodeMatrixModule`
- `MatrixVisualizer`
- `AdvancedDrop` 規劃層

佢目前**唔**捆綁相機、顯微鏡、溫度或光照模組。

## 點解重要

`DMLite` 展示咗真實系統嘅核心模式：

- 繼承 `DropSystem`
- 由設定載入機器狀態
- 實例化必需嘅硬件模組
- 將高層狀態更新 route 去模組命令
- 令規劃層獨立於硬件 driver 細節

換句話講，佢係 DropLogic 系統架構一個細但真實嘅例子。

## 硬件重點

呢個系統專注於電極驅動：

- 設定矩陣狀態
- 更新工作電壓
- 將矩陣變化傳遞畀低層實現

具體硬件實現位於模組層之後，所以系統本身保持可讀、可替換。

## 典型入口

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

## 模組

因為 `DMLite` 係真實硬件支援嘅系統，佢嘅模組組成會喺本節下面嘅嵌套頁面明確記錄。目前呢個組成刻意保持簡單：系統由 Acxel `DMLite` 電極矩陣模組，以及 DropLogic 共享嘅規劃同視覺化層組成。
