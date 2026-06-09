# 硬件註記

本文檔入面提到嘅 `DMLite` 或 `BOXMini` 指 Acxel 硬件平台。本倉庫只包含圍繞受支援硬件嘅 Python 適配程式碼；供應商硬件同原生 runtime assets 唔喺源碼樹入面。硬件供應商資料請睇 [Acxel](https://www.acxel.com/)。

DropLogic 嘅硬件層由系統同模組組成：

- **系統**：完整機器或者模擬環境，例如 `Simulator`、`DMLite` 或 `BOXMini`。
- **模組**：機器入面嘅能力區塊，例如電極矩陣、相機、XY stage、光照或溫度控制。
- **版本**：某個模組面向具體硬件嘅實現。

呢個結構令高層 droplet API 保持穩定，同時將供應商協議、SDK 同原生 runtime 細節限制喺較細嘅實現層入面。
