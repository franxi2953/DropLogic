# 分割同抽取

DropLogic 有兩個公開嘅 split-style 操作：

- `reservoir_extraction()`：由 reservoir 液滴建立一個或多個液滴。
- `isometric_split()`：將一個液滴分成對稱子滴。

兩個函數都會擴展 `system.advanced_drop.plan`，並返回新液滴 ID。

## Reservoir Extraction

```python
new_ids = system.advanced_drop.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to2",
    steps=(0, 10),
    split_size={(2, 2), (2, 3), (3, 2), (3, 3)},
    new_droplet_id=10,
)
```

參數：

- `reservoir_droplet_id`：reservoir 液滴 ID。
- `split_mode`：`"1to2"`、`"1to3"` 或 `"linear"`。
- `steps`：由 reservoir corner 出發嘅位移。
- `split_size`：抽取液滴嘅形狀或尺寸。
- `new_droplet_id`：可選嘅第一個新 ID。
- `halo_size`：`"1to2"` 中抽取液滴周圍嘅 inactive halo。
- `separation_steps`：`"1to3"` 嘅分離距離。
- `remove_duplicate_frames`：擴展後裁剪重複 frames。

`steps` 係 `(row_delta, col_delta)`。負 row 向上，正 col 向右。

## `1to2`

由 reservoir 中抽取一個液滴。

```python
ad.droplets.create_droplet(1, origin=(20, 16), target=(20, 16), width=6, height=6)

new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to2",
    steps=(0, 10),
    split_size={(2, 2), (2, 3), (3, 2), (3, 3)},
    halo_size=1,
)
```

當你希望 reservoir 保留大部分 footprint，同時產生一個較細液滴時使用。

## `1to3`

抽取中央液滴並分離產生嘅 pieces。

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to3",
    steps=(0, 14),
    split_size=(2, 2),
    separation_steps=4,
)
```

對於 `"1to3"`，`split_size` 解釋為 `(height, width)`。適合直接 reservoir dispensing 受幾何限制時使用。

## `linear`

由 reservoir 線性 sweep 生成多個液滴。

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="linear",
    linear_drops_number=21,
    linear_offset=0,
    linear_space_per_col=3,
    linear_space_per_row=1,
    linear_drop_shape=(1, 1),
    linear_direction=(0, 1),
)
```

`linear_direction=(0, 1)` 表示向右水平 sweep，`(1, 0)` 表示向下，負值表示相反方向。

## Isometric Split

`isometric_split()` 遞歸咁將液滴分成相等子滴，並對稱移動佢哋。

```python
new_ids = ad.isometric_split(
    droplet_id=1,
    steps=[(0, 8), (8, 0), (0, 4), (4, 0)],
    simultaneous=True,
    new_droplet_id=2,
)
```

常見失敗原因包括：源液滴不存在、`steps` 會將新液滴放出矩陣、抽取液滴同 reservoir overlap、源液滴電極數不足，或者周圍區域太受限無法分離。
