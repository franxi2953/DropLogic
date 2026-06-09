# 架構圖

呢頁係 DropLogic 倉庫結構嘅本地化入口。英文頁面包含一個自動生成嘅互動式 graph，展示源碼目錄、模組邊界、檔案路徑同 public symbols。

程式標識符、檔案名、Python symbol、路徑同函數名唔翻譯，因為佢哋必須同倉庫入面嘅真實物件完全一致。

## 點樣閱讀

- `droplogic/hardware/` 包含系統定義，例如 `Simulator`、`DMLite` 同硬件 adapters。
- `droplogic/hardware/modules/` 包含可重用硬件模組，例如 electrode matrix、camera、light、XY stage 同 feedback。
- `droplogic/utils/advanced_drop/` 包含高層液滴規劃 API、SIPP movement、split/merge/mix 操作同 `PlanExecutor`。
- `droplogic/utils/visualizer/` 同 `droplogic/utils/recording.py` 包含視覺化同同步錄影支援。
- `droplogic/utils/drop_vision/` 包含液滴同 condensate detection helpers。
- `docs/` 包含多語言文檔；每個頁面透過 `.en.md`、`.es.md`、`.zh-CN.md` 同 `.zh-HK.md` 後綴本地化。

## 互動式 Graph

完整互動式 graph 由 `docs/scripts/generate_architecture_graph.py` 生成。佢主要顯示程式碼結構，而唔係自然語言，所以技術 labels 會保持英文/源碼形式。

如果需要重新生成 graph，請由倉庫根目錄運行相應 docs 腳本，並確認生成嘅 `.en.md` / `.es.md` / `.zh-CN.md` / `.zh-HK.md` 頁面仍然可以通過 `mkdocs build --strict`。
