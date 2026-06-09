# 混合

`mix()` 為一個液滴建立混合運動。

```python
new_ids = system.advanced_drop.mix(
    droplet_id=1,
    mode="split_recombine",
    cycles=5,
)
```

函數會擴展 `system.advanced_drop.plan`，並返回操作期間建立嘅新液滴 ID。

兩個內置模式對應經典 DMF mixing 策略：令完整液滴沿 2D loop 移動，或者喺幾何容許時 split 後 recombine。

## 選擇模式

| 模式 | 適用情況 | 注意情況 | 主要參數 |
| --- | --- | --- | --- |
| `split_recombine` | 液滴可以乾淨分裂，並希望透過反覆 split/merge 獲得強內部重排。 | footprint 細、不對稱、接近障礙，或者物理系統分裂唔可靠。 | `cycles`, `split_area` |
| `2d_loop` | 液滴應保持完整，並沿 2D loop 移動。 | 可用 loop 區域好細、被阻擋或太接近其他液滴。 | `cycles`, `mixing_area_size` |

## `split_recombine`

當液滴形狀容許時，呢個模式會反覆分裂並重組液滴。

```python
ad.droplets.create_droplet(1, origin=(28, 28), target=(28, 28), width=2, height=2)
new_ids = ad.mix(droplet_id=1, mode="split_recombine", cycles=1)
```

如果操作需要特定區域進行對稱延展，可以傳入 `split_area`。如果液滴無法安全分裂，實現可能會對剩餘 cycles 回退到 loop-style movement。

## `2d_loop`

呢個模式令液滴沿矩形 loop 移動。

```python
ad.droplets.create_droplet(1, origin=(24, 24), target=(24, 24), width=2, height=2)
ad.mix(droplet_id=1, mode="2d_loop", mixing_area_size=8, cycles=1)
```

當你希望透過重複平移而唔係分裂嚟混合時，使用呢個模式。

## 事件標籤

```python
ad.mix(
    droplet_id=1,
    mode="2d_loop",
    cycles=4,
    event_id="mix_sample",
)
```

事件標籤令長 protocol 更容易喺 plan debugger 中檢查。
