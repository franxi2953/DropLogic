# 液滴管理

液滴透過 `system.advanced_drop.droplets` 管理。呢個物件似 list 咁工作，同時提供建立、更新同檢查 `Droplet` 物件嘅 helper methods。

## `create_droplet()`

建立一個邏輯液滴，並追加一個顯示佢喺起點位置嘅 frame。

```python
droplet = system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(40, 40),
    width=2,
    height=2,
    priority=0,
    vital_space=1,
)
```

用 `width` 同 `height` 建立矩形液滴，或者用 `shape` 指定自訂 footprint。

主要參數：

- `droplet_id`：唯一整數 ID。
- `origin`：目前左上角 `(row, col)`。
- `target`：目標左上角 `(row, col)`。
- `shape`：可選嘅相對 `(row, col)` offsets。
- `width`, `height`：未提供 `shape` 時嘅矩形尺寸。
- `priority`：routing 順序。當前 SIPP planner 由低數值到高數值規劃。
- `vital_space`：用於避免碰撞嘅最小 halo。

## 批量建立

當 protocol 由一組液滴定義開始時，使用 `add_droplets()`。

```python
system.advanced_drop.droplets.add_droplets(droplet_specs)
```

## 更新目標

`update_droplet_target()` 係執行舊計劃後請求新移動嘅常規方式。

```python
system.advanced_drop.droplets.update_droplet_target(1, (70, 20))
system.advanced_drop.move(mode="sipp")
```

`move()` 只規劃目前位置同目標唔同嘅液滴。如果液滴已經喺目標位置，請先更新目標。

硬件位置唔匹配後嘅修正應優先用 `system.advanced_drop.correct_droplet_position()`，因為佢仲會向計劃追加 correction frame。

## 檢查液滴

```python
droplet = system.advanced_drop.droplets.get_droplet(1)
info = system.advanced_drop.droplets.get_droplet_info(1)
summary = system.advanced_drop.droplets.get_droplets_summary()
```

`get_droplet_info()` 返回目前位置、目標、形狀、priority 同 vital-space 設定。

## 刪除同重置

```python
system.advanced_drop.droplets.delete_droplet(1)
system.advanced_drop.clear()
```

`delete_droplet()` 刪除液滴物件，但唔會自動重寫舊 plan frames。`clear()` 重置液滴列表同目前計劃。

## 推送手動 Frame

```python
system.advanced_drop.push_frame(
    event_type="manual_hold",
    event_data={"reason": "stabilize before imaging"},
)
```

適合喺操作之間加入明確 hold 或同步點。
