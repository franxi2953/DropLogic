# 合并

`merge()` 将多个液滴 route 到一个合并后的 footprint。

```python
merged_id = system.advanced_drop.merge(
    droplet_ids=[1, 2],
    target=(40, 40),
)
```

该函数扩展 `system.advanced_drop.plan`，并返回合并液滴的 ID；如果无法创建有效合并液滴，则返回 `None`。

## 公共签名

```python
system.advanced_drop.merge(
    droplet_ids,
    target,
    forced_width=None,
    forced_height=None,
    hold_final_position=False,
    event_id=None,
    remove_duplicate_frames=False,
)
```

## 目标模式

`target` 可以是坐标：

```python
merged_id = ad.merge([1, 2, 3], target=(50, 50))
```

也可以是已有液滴 ID：

```python
merged_id = ad.merge([1, 2], target=3)
```

当 `target` 是液滴 ID 时，其他液滴会合并到该液滴的当前位置。

## 形状控制

默认情况下，DropLogic 根据总电极数量构建紧凑的合并 footprint。需要特定几何时使用 `forced_width` 或 `forced_height`。

```python
merged_id = ad.merge(
    droplet_ids=[1, 2, 3],
    target=(45, 45),
    forced_width=3,
    forced_height=2,
)
```

## 保持最终 Footprint

`hold_final_position=True` 会在合并 frames 中激活合并后的 footprint。这对目标位置需要额外电支撑的情况有用。

```python
merged_id = ad.merge(
    droplet_ids=[1, 2],
    target=(40, 40),
    hold_final_position=True,
)
```

## 事件标签

```python
merged_id = ad.merge(
    droplet_ids=[1, 2],
    target=(40, 40),
    event_id="merge_reagents",
)
```

事件会出现在 plan 和 plan debugger 中。

## 常见模式

```python
ad.droplets.create_droplet(1, origin=(18, 18), target=(18, 18), width=1, height=1)
ad.droplets.create_droplet(2, origin=(18, 32), target=(18, 32), width=1, height=1)

merged_id = ad.merge(
    [1, 2],
    target=(24, 25),
    hold_final_position=True,
)

ad.executor.start(frame_delay=0.7, enable_visualizers=True)
```

合并操作内部使用移动规划，因此如果布局太受限，液滴无法安全 route 到合并点时仍可能失败。
