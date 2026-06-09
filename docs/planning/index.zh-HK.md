# 規劃

規劃層將液滴意圖轉換成可執行嘅矩陣 frames。

喺 DropLogic 入面，呢件事主要由 `AdvancedDrop` 處理：佢保存液滴、建立計劃、檢查約束，並將 frames 交畀 executor。

## 主要組成

- **AdvancedDrop**：面向用戶嘅規劃 API，喺每個系統入面透過 `system.advanced_drop` 暴露
- **液滴狀態**：液滴、位置、目標、形狀、事件同 frame metadata
- **移動規劃**：基於 SIPP 嘅 routing，用於避免碰撞嘅多液滴移動
- **操作**：移動、分割、合併、混合同 reservoir extraction
- **PlanExecutor**：將已規劃 frames 喺系統上運行嘅 runtime 執行層

## 公共工作流

大多數腳本都係類似結構：

```python
from droplogic.hardware.simulator import Simulator

system = Simulator(log_level="INFO")
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(10, 10), target=(30, 40), width=2, height=2)
ad.move(mode="sipp")

ad.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    save_to_file="runs/simple_plan.pkl",
)
```

`AdvancedDrop` 建立計劃。`PlanExecutor` 執行並記錄計劃。視覺化工具會顯示或捕捉 executor 正在做嘅事。

## 典型流程

```python
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2,
    height=2,
)

system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

規劃器應該保持同硬件無關。硬件相關行為屬於 systems 同 modules；規劃層只應處理 frames、液滴、約束同執行 timing。
