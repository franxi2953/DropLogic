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

如果目标液滴 ID 也出现在 `droplet_ids` 中，它会被视为 merge destination 并从输入列表移除；仍然需要至少一个其他输入液滴。

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

## Target Validation

使用 `validate_merge_target_layout()` 在追加 plan frames 前诊断 merge hub：

```python
validation = ad.validate_merge_target_layout(
    droplet_ids=[1, 2],
    target=(40, 40),
)

if not validation["ok"]:
    print(validation["blocking_issues"])
    print(validation.get("suggested_target"))
    print(validation.get("blocker_parking_suggestions"))
```

这个 helper 是 pure 的：不会修改 droplets 或 `ad.plan`。它检查缺失输入、合并 footprint 越界、active non-merge droplets 与目标 footprint/vital space 冲突，以及 merge inputs 起始位置落在另一个 active droplet 当前保留空间中的情况。可行时会返回附近 `suggested_target` 和每个 blocker 的 `blocker_parking_suggestions`。

merge into existing droplet 时，合并产物保留目标液滴的 `vital_space`，包括 `0`。坐标目标创建新合并液滴时，产物默认使用 `vital_space=1`。

MCP `plan_merge` 会在规划前调用这个 validation。不安全 hub 返回 `ok=false` 和 `primitive_validation.merge_target_validation`，并可能包含 `primitive_validation.recommended_action`。如果 existing-target merge 的 suggested target 含有 `retry_arguments`，使用这些参数，而不是只替换坐标。

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
