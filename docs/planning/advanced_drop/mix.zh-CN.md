# 混合

`mix()` 为一个液滴创建混合运动。

```python
new_ids = system.advanced_drop.mix(
    droplet_id=1,
    mode="split_recombine",
    cycles=5,
)
```

函数扩展 `system.advanced_drop.plan`，并返回操作期间创建的新液滴 ID。

两个内置模式对应经典 DMF mixing 策略：让完整液滴沿 2D loop 移动，或在几何允许时 split 后 recombine。

## 选择模式

| 模式 | 适用情况 | 注意情况 | 主要参数 |
| --- | --- | --- | --- |
| `split_recombine` | 液滴能干净分裂，并希望通过反复 split/merge 获得强内部重排。 | footprint 小、不对称、接近障碍，或物理系统分裂不可靠。 | `cycles`, `split_area` |
| `2d_loop` | 液滴应保持完整，并沿 2D loop 移动。 | 可用 loop 区域很小、被阻挡或太接近其他液滴。 | `cycles`, `mixing_area_size` |

## 公共签名

```python
system.advanced_drop.mix(
    droplet_id,
    mode="split_recombine",
    split_area=None,
    mixing_area_size=None,
    cycles=5,
    event_id=None,
    remove_duplicate_frames=False,
)
```

## `split_recombine`

当液滴形状允许时，该模式反复分裂并重组液滴。

```python
ad.droplets.create_droplet(1, origin=(28, 28), target=(28, 28), width=2, height=2)
new_ids = ad.mix(droplet_id=1, mode="split_recombine", cycles=1)
```

如果操作需要特定区域进行对称延展，可以传入 `split_area`。如果液滴无法安全分裂，实现可能会对剩余 cycles 回退到 loop-style movement。

## `2d_loop`

该模式让液滴沿矩形 loop 移动。

```python
ad.droplets.create_droplet(1, origin=(24, 24), target=(24, 24), width=2, height=2)
ad.mix(droplet_id=1, mode="2d_loop", mixing_area_size=8, cycles=1)
```

当你希望通过重复平移而不是分裂来混合时，使用这个模式。

## 事件标签

```python
ad.mix(
    droplet_id=1,
    mode="2d_loop",
    cycles=4,
    event_id="mix_sample",
)
```

事件标签让长协议更容易在 plan debugger 中检查。
