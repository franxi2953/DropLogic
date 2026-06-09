# Plan Objects

`AdvancedDrop` 將 protocol 輸出保存喺 `system.advanced_drop.plan`。

呢個 plan 係一個 `DropletPlan`：按 frame 描述矩陣狀態、液滴軌跡、活動液滴同事件 metadata。

## `DropletPlan` 欄位

- `frames`：2D arrays 列表。每個 frame 係要發送到系統嘅電極矩陣。
- `frame_count`：frame 數量。
- `droplet_trajectories`：由液滴 ID 到隨時間變化嘅 `(row, col)` 位置。
- `active_droplets_per_frame`：每個 frame 嘅活動液滴 ID。
- `events`：按時間排序嘅 `(frame_index, event_type, metadata)`。
- `planning_success`：整體布爾結果。
- `conflicts_resolved`：診斷用衝突 metadata。
- `targets_reached`：由液滴 ID 到 boolean。
- `event_id_per_frame`：每個 frame 嘅事件 ID 標籤。

## 檢查 Plan

```python
plan = system.advanced_drop.plan

print(plan.frame_count)
print(plan.planning_success)
print(plan.targets_reached)
print(plan.events)
```

## 取得液滴位置

`AdvancedDrop.get_droplet_position()` 返回最終規劃位置。

```python
final_pos = system.advanced_drop.get_droplet_position(1)
```

`PlanExecutor.get_droplet_position()` 返回 runtime 中最後執行嘅位置。

```python
runtime_pos = system.advanced_drop.executor.get_droplet_position(1)
```

## 擴展 Plans

大多數公共操作會自動擴展目前 plan：

```python
ad.droplets.create_droplet(1, (10, 10), (20, 20), width=2, height=2)
ad.move(mode="sipp")
ad.mix(1, mode="2d_loop", cycles=3)
ad.merge([1, 2], target=(40, 40))
```

只有組合自訂 `DropletPlan` 時先直接使用 `extend_plan()`。

## 刪除重複 Frames

```python
ad.remove_duplicates(start_idx=0, end_idx=-1)
```

佢會刪除指定範圍內嘅重複 frames，並 remap trajectories/events。請喺規劃後使用，唔好喺 executor 運行時使用。

呢個主要係開發/除錯清理工具，可能合併對 breakpoints、diagnostics 或 protocol inspection 有用嘅事件邊界。

## 合併連續 Events

`merge_sequential_events()` 合併兩個連續 event spans。

```python
new_event_id = ad.merge_sequential_events(
    event_id_1=3,
    event_id_2=4,
    force=False,
)
```

只有當你理解被覆蓋嘅電極衝突時先使用 `force=True`。

## 保存 Plan

保存通常由 executor 處理：

```python
ad.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

保存嘅 pickle 包含 `plan` 同 `droplets`，plan debugger 可以讀取呢個格式。
