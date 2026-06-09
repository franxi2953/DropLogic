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
