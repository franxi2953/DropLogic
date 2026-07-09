# 合併

`merge()` 將多個液滴 route 到一個合併後嘅 footprint。

```python
merged_id = system.advanced_drop.merge(
    droplet_ids=[1, 2],
    target=(40, 40),
)
```

函數會擴展 `system.advanced_drop.plan`，並返回合併液滴嘅 ID；如果無法建立有效合併液滴，則返回 `None`。

## 公共簽名

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

## 目標模式

`target` 可以係座標：

```python
merged_id = ad.merge([1, 2, 3], target=(50, 50))
```

亦可以係已有液滴 ID：

```python
merged_id = ad.merge([1, 2], target=3)
```

當 `target` 係液滴 ID 時，其他液滴會合併到該液滴嘅目前位置。

如果目標液滴 ID 亦出現在 `droplet_ids` 中，佢會被視為 merge destination 並由輸入列表移除；仍然需要至少一個其他輸入液滴。

## 形狀控制

預設情況下，DropLogic 根據總電極數量建立緊湊嘅合併 footprint。需要特定幾何時用 `forced_width` 或 `forced_height`。

## 保持最終 Footprint

`hold_final_position=True` 會喺合併 frames 中激活合併後嘅 footprint。對目標位置需要額外電支撐嘅情況有用。

```python
merged_id = ad.merge(
    droplet_ids=[1, 2],
    target=(40, 40),
    hold_final_position=True,
)
```

## Target Validation

使用 `validate_merge_target_layout()` 喺追加 plan frames 前診斷 merge hub：

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

呢個 helper 係 pure：唔會修改 droplets 或 `ad.plan`。佢檢查缺失輸入、合併 footprint 越界、active non-merge droplets 同目標 footprint/vital space 衝突，以及 merge inputs 起始位置落在另一個 active droplet 目前保留空間中嘅情況。可行時會返回附近 `suggested_target` 同每個 blocker 嘅 `blocker_parking_suggestions`。

merge into existing droplet 時，合併產物保留目標液滴嘅 `vital_space`，包括 `0`。座標目標建立新合併液滴時，產物預設使用 `vital_space=1`。

MCP `plan_merge` 會喺規劃前調用呢個 validation。不安全 hub 返回 `ok=false` 同 `primitive_validation.merge_target_validation`，並可能包含 `primitive_validation.recommended_action`。如果 existing-target merge 嘅 suggested target 含有 `retry_arguments`，使用呢啲參數，而唔係只替換座標。

## 事件標籤

```python
merged_id = ad.merge(
    droplet_ids=[1, 2],
    target=(40, 40),
    event_id="merge_reagents",
)
```

事件會出現喺 plan 同 plan debugger 入面。

## 常見模式

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

合併操作內部使用移動規劃，所以如果 layout 太受限，液滴無法安全 route 到合併點時仍可能失敗。
