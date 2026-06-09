# 架构图

此页面是 DropLogic 仓库结构的本地化入口。英文页面包含一个自动生成的交互式 graph，展示源码目录、模块边界、文件路径和公共 symbols。

代码标识符、文件名、Python symbol、路径和函数名不翻译，因为它们必须与仓库中的真实对象完全一致。

## 如何阅读

- `droplogic/hardware/` 包含系统定义，例如 `Simulator`、`DMLite` 和硬件 adapters。
- `droplogic/hardware/modules/` 包含可复用硬件模块，例如 electrode matrix、camera、light、XY stage 和 feedback。
- `droplogic/utils/advanced_drop/` 包含高层液滴规划 API、SIPP movement、split/merge/mix 操作和 `PlanExecutor`。
- `droplogic/utils/visualizer/` 和 `droplogic/utils/recording.py` 包含可视化与同步录制支持。
- `droplogic/utils/drop_vision/` 包含液滴和 condensate detection helpers。
- `docs/` 包含多语言文档；每个页面通过 `.en.md`、`.es.md`、`.zh-CN.md` 和 `.zh-HK.md` 后缀本地化。

## 交互式 Graph

完整交互式 graph 由 `docs/scripts/generate_architecture_graph.py` 生成。它主要显示代码结构而不是自然语言，因此技术 labels 会保持英文/源码形式。

如果需要重新生成 graph，请从仓库根目录运行相应 docs 脚本，并确认生成的 `.en.md` / `.es.md` / `.zh-CN.md` / `.zh-HK.md` 页面仍能通过 `mkdocs build --strict`。
