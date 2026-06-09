# 系統同模組

DropLogic 圍繞一個簡單想法組織：一個 **系統** 由一組可重用 **模組** 組合而成。

呢個結構令函式庫保持靈活。同一套規劃同控制層可以喺模擬環境同真實硬件之間重用，而每個系統只連接自己真正需要嘅模組。

## 核心概念

### 系統

**系統** 係暴露畀用戶嘅頂層機器定義。

例子：

- `Simulator`：用於開發同測試嘅純軟件環境。
- `DMLite`：專注於電極矩陣嘅真實硬件系統。硬件平台來自 [Acxel](https://www.acxel.com/)；本函式庫提供 Python 集成層。

系統通常提供：

- 基於 `DropSystem` 嘅控制表面
- 狀態同命令 routing
- 該機器可用嘅模組集合
- 相關時嘅 visualizers
- `AdvancedDrop` 規劃同執行

### 模組

**模組** 係系統內部嘅能力區塊。

例子：

- 電極矩陣
- 相機
- 顯微鏡
- XY stage
- 溫度控制器
- 光照

模組畀系統提供物理或模擬能力。可以將一個系統理解成一組經過選擇嘅模組 bundle。

### 版本

**版本** 係模組背後嘅具體實現。

例子：

- `CameraV1`
- `DMLite`
- `TemperatureV1`

呢點令 DropLogic 可以保持穩定嘅高層 API，同時替換低層 driver 或設備專屬實現。

`DMLite` 呢個名有意出現喺兩個地方：

- 作為 **系統**：`droplogic.hardware.DMLite`，即係用戶實例化嘅頂層 DropLogic 機器
- 作為 **模組版本**：`droplogic.hardware.modules.electrode_matrix.versions.DMLite`，即係該系統內部使用嘅 Acxel 專屬電極矩陣實現

所以目前 `DMLite` 系統就係一個真實系統，由一個主要硬件模組組成：Acxel `DMLite` 電極矩陣適配器。

## 系統點樣構建

實際上，一個 DropLogic 系統通常由呢啲部分 remix 而成：

1. 共享嘅 `DropSystem` base class
2. 一個或多個硬件或模擬模組
3. 可選 visualizers
4. `AdvancedDrop` 規劃層

即係兩個系統可以共享大部分行為，只係暴露嘅模組同實例化嘅版本唔同。

## 真實系統 vs 模擬系統

DropLogic 同時支援：

- **模擬系統**：適合冇硬件時做規劃、除錯同開發
- **真實系統**：將同樣概念綁定到物理設備

對於真實系統，文檔包含 **模組** 子章節，令硬件組成保持清楚。

## 目前系統

### Simulator

`Simulator` 係最適合入門嘅環境，用於開發、算法驗證同視覺化除錯。

### DMLite

`DMLite` 係圍繞 Acxel 電極矩陣構建嘅最小真實系統。佢嘅硬件表面比大型機器細，因為目前主要由一個硬件模組組成，但仍然保持同樣嘅 DropLogic 架構。

## 擴展函式庫

理解 systems 同 modules 之後，喺 DropLogic 入面建立新機器主要就係重組現有模組，並喺需要時加入新模組。

實現指南見本節末尾嘅 **建立新系統**。
