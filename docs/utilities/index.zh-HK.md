# 工具

Utilities 係 systems、planning、hardware integration 同 debugging 使用嘅支援層。

佢哋唔係主要面向用戶嘅工作流，但會令工作流更可靠：

- 座標轉換同設定 helpers
- 液滴同 condensate 偵測
- 圖像擷取 helpers
- plan debugging
- runtime diagnostics
- logging setup

大多數用戶會先由 `Systems` 同 `Planning` 開始，之後需要調硬件、檢查失敗或集成新模組時先嚟呢度。

## 幾時用咩

- 用 **Hardware Utilities** 處理 `config.json`、電極-stage 轉換、pixel-micron 轉換同簡單體積估算。
- 用 **Drop Vision** 喺 visualizer 之外直接做液滴或 condensate 偵測。
- 用 **Debugging and Diagnostics** 檢查保存嘅計劃、runtime doctor、logging 同 executor timeout reports。
