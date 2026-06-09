# 移动

`move()` 为当前位置与目标不同的液滴规划协同移动。

要再次移动已有液滴，先更新它的目标：

```python
system.advanced_drop.droplets.update_droplet_target(1, (60, 20))
system.advanced_drop.move(mode="sipp")
```

```python
plan = system.advanced_drop.move(mode="sipp")
```

返回的 `DropletPlan` 也会保存为 `system.advanced_drop.plan`。

## 公共签名

```python
system.advanced_drop.move(
    mode="sipp",
    remove_duplicate_frames=False,
    merge_on_failure=True,
    **kwargs,
)
```

`kwargs` 会转发给低层 SIPP planner。

## 模式

目前 `mode="sipp"` 是唯一实现的移动模式。SIPP 是 Safe Interval Path Planning；在 DropLogic 中，它在空间和时间中 route 液滴，并保留液滴身体、`vital_space` halo 和边缘转换以减少碰撞。

传入其他模式会抛出：

```python
ValueError: Unsupported mode
```

## 基本移动

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

## 多液滴移动

只有 `origin_corner != target_corner` 的液滴会被规划。已经在目标位置的液滴在扩展计划时仍会作为 active droplets 保留。

启用 matrix visualizer 后，`PlanExecutor` 可以把保存的 `droplet_trajectories` 显示为 route overlays。

## 常用 Planner 选项

- `planning_timeout`：停止前的最大规划时间，单位秒。
- `max_iterations`：每个液滴的搜索迭代限制。
- `max_frames`：生成 frames 的上限。
- `max_path_frames`：SIPP 搜索内部的路径长度上限。
- `reservation_horizon`：用于保留初始/最终位置的未来 frames 数。
- `reserve_final_positions`：路径完成后继续保留最终位置。
- `ignore_vital_space_pairs`：允许忽略 vital-space separation 的液滴 ID pair 集合。
- `debug_visualization`：在生成 frames 中标记 reserved 或 vital-space 区域。

```python
plan = ad.move(
    mode="sipp",
    planning_timeout=60,
    max_path_frames=200,
    reservation_horizon=250,
    ignore_vital_space_pairs={(1, 2)},
)
```

## 失败处理

默认 `merge_on_failure=True`，表示 partial planning output 仍可追加到当前计划。

如果想检查失败尝试而不改变 `ad.plan`：

```python
candidate = ad.move(mode="sipp", merge_on_failure=False)

if not candidate.planning_success:
    print(candidate.targets_reached)
```

`merge_on_failure=False` 时，规划失败的液滴会恢复到之前的逻辑角，返回的 plan 不会赋给 `ad.plan`。

## 执行后重新设定目标

```python
ad.droplets.update_droplet_target(1, (60, 20))
ad.move(mode="sipp")
ad.executor.start(frame_delay=0.5, enable_visualizers=True)
```

planner 会读取上一个 plan state 并从那里继续扩展。
