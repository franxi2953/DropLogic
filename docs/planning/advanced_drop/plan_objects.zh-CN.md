# Plan Objects

`AdvancedDrop` 将协议输出保存在 `system.advanced_drop.plan`。

该 plan 是一个 `DropletPlan`：按 frame 描述矩阵状态、液滴轨迹、活动液滴和事件 metadata。

## `DropletPlan` 字段

- `frames`：2D arrays 列表。每个 frame 是要发送到系统的电极矩阵。
- `frame_count`：frame 数量。
- `droplet_trajectories`：从液滴 ID 到随时间变化的 `(row, col)` 位置。
- `active_droplets_per_frame`：每个 frame 的活动液滴 ID。
- `events`：按时间排序的 `(frame_index, event_type, metadata)`。
- `planning_success`：整体布尔结果。
- `conflicts_resolved`：诊断用冲突 metadata。
- `targets_reached`：从液滴 ID 到 boolean。
- `event_id_per_frame`：每个 frame 的事件 ID 标签。

## 检查 Plan

```python
plan = system.advanced_drop.plan

print(plan.frame_count)
print(plan.planning_success)
print(plan.targets_reached)
print(plan.events)
```

检查某个 frame：

```python
frame_10 = plan.frames[10]
active_ids = plan.active_droplets_per_frame[10]
```

## 获取液滴位置

`AdvancedDrop.get_droplet_position()` 返回最终规划位置。

```python
final_pos = system.advanced_drop.get_droplet_position(1)
```

`PlanExecutor.get_droplet_position()` 返回 runtime 中最后执行的位置。

```python
runtime_pos = system.advanced_drop.executor.get_droplet_position(1)
```

## 扩展 Plans

大多数公共操作会自动扩展当前 plan：

```python
ad.droplets.create_droplet(1, (10, 10), (20, 20), width=2, height=2)
ad.move(mode="sipp")
ad.mix(1, mode="2d_loop", cycles=3)
ad.merge([1, 2], target=(40, 40))
```

只有在组合自定义 `DropletPlan` 时才直接使用 `extend_plan()`。

## 删除重复 Frames

```python
ad.remove_duplicates(start_idx=0, end_idx=-1)
```

它会删除指定范围内的重复 frames，并 remap trajectories/events。请在规划后使用，不要在 executor 运行时使用。

这主要是开发/调试清理工具，可能合并对 breakpoints、diagnostics 或 protocol inspection 有用的事件边界。

## 合并连续 Events

`merge_sequential_events()` 合并两个连续 event spans。

```python
new_event_id = ad.merge_sequential_events(
    event_id_1=3,
    event_id_2=4,
    force=False,
)
```

只有当你理解被覆盖的电极冲突时才使用 `force=True`。

## 保存 Plan

保存通常由 executor 处理：

```python
ad.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

保存的 pickle 包含 `plan` 和 `droplets`，plan debugger 可以读取该格式。
