# 分裂和提取

DropLogic 有两个公开的 split-style 操作：

- `reservoir_extraction()`：从 reservoir 液滴创建一个或多个液滴。
- `isometric_split()`：把一个液滴分成对称子滴。

两个函数都会扩展 `system.advanced_drop.plan`，并返回新液滴 ID。

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

参数：

- `reservoir_droplet_id`：reservoir 液滴 ID。
- `split_mode`：`"1to2"`、`"1to3"` 或 `"linear"`。
- `steps`：从 reservoir corner 出发的位移。
- `split_size`：提取液滴的形状或尺寸。
- `new_droplet_id`：可选的第一个新 ID。
- `halo_size`：`"1to2"` 中提取液滴周围的 inactive halo。
- `separation_steps`：`"1to3"` 的分离距离。
- `remove_duplicate_frames`：扩展后裁剪重复 frames。

`steps` 是 `(row_delta, col_delta)`。负 row 向上，正 col 向右。

## `1to2`

从 reservoir 中提取一个液滴。

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

当你希望 reservoir 保留大部分 footprint，同时产生一个较小液滴时使用。

## `1to3`

提取中央液滴并分离产生的 pieces。

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to3",
    steps=(0, 14),
    split_size=(2, 2),
    separation_steps=4,
)
```

对于 `"1to3"`，`split_size` 解释为 `(height, width)`。适合直接 reservoir dispensing 受几何限制时使用。

## `linear`

从 reservoir 线性 sweep 生成多个液滴。

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

`linear_direction=(0, 1)` 表示向右水平 sweep，`(1, 0)` 表示向下，负值表示相反方向。

## Isometric Split

`isometric_split()` 递归地将液滴分成相等子滴，并对称移动它们。

```python
new_ids = ad.isometric_split(
    droplet_id=1,
    steps=[(0, 8), (8, 0), (0, 4), (4, 0)],
    simultaneous=True,
    new_droplet_id=2,
)
```

常见失败原因包括：源液滴不存在、`steps` 会把新液滴放出矩阵、提取液滴与 reservoir overlap、源液滴电极数不足，或周围区域太受限无法分离。
