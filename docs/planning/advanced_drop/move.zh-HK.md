# 移動

`move()` 為目前位置同目標唔同嘅液滴規劃協同移動。

要再次移動已有液滴，先更新佢嘅目標：

```python
system.advanced_drop.droplets.update_droplet_target(1, (60, 20))
system.advanced_drop.move(mode="sipp")
```

返回嘅 `DropletPlan` 亦會保存為 `system.advanced_drop.plan`。

## 公共簽名

```python
system.advanced_drop.move(
    mode="sipp",
    remove_duplicate_frames=False,
    merge_on_failure=True,
    **kwargs,
)
```

`kwargs` 會轉發畀低層 SIPP planner。

## 模式

目前 `mode="sipp"` 係唯一實現嘅移動模式。SIPP 係 Safe Interval Path Planning；喺 DropLogic 入面，佢會喺空間同時間中 route 液滴，並保留液滴身體、`vital_space` halo 同邊緣轉換以減少碰撞。

其他模式會拋出：

```python
ValueError: Unsupported mode
```

## 基本移動

```python
ad = system.advanced_drop
ad.clear()

ad.droplets.create_droplet(1, origin=(30, 18), target=(30, 48), width=2, height=2)

plan = ad.move(
    mode="sipp",
    planning_timeout=60,
    max_path_frames=120,
)
```

## 多液滴移動

只有 `origin_corner != target_corner` 嘅液滴會被規劃。已經喺目標位置嘅液滴喺擴展計劃時仍會作為 active droplets 保留。

啟用 matrix visualizer 後，`PlanExecutor` 可以將保存嘅 `droplet_trajectories` 顯示為 route overlays。

## 常用 Planner 選項

- `planning_timeout`：停止前最大規劃時間，單位秒。
- `max_iterations`：每個液滴嘅搜尋迭代限制。
- `max_frames`：生成 frames 上限。
- `max_path_frames`：SIPP 搜尋內部路徑長度上限。
- `reservation_horizon`：用於保留初始/最終位置嘅未來 frames 數。
- `reserve_final_positions`：路徑完成後繼續保留最終位置。
- `ignore_vital_space_pairs`：允許忽略 vital-space separation 嘅液滴 ID pair 集合。
- `debug_visualization`：喺生成 frames 中標記 reserved 或 vital-space 區域。

## 失敗處理

預設 `merge_on_failure=True`，表示 partial planning output 仍可追加到目前計劃。

```python
candidate = ad.move(mode="sipp", merge_on_failure=False)

if not candidate.planning_success:
    print(candidate.targets_reached)
```

`merge_on_failure=False` 時，規劃失敗嘅液滴會恢復到之前嘅邏輯角，返回嘅 plan 唔會賦畀 `ad.plan`。

## 執行後重新設定目標

```python
ad.droplets.update_droplet_target(1, (60, 20))
ad.move(mode="sipp")
ad.executor.start(frame_delay=0.5, enable_visualizers=True)
```

planner 會讀取上一個 plan state 並由嗰度繼續擴展。
