# 液滴管理

液滴通过 `system.advanced_drop.droplets` 管理。这个对象像 list 一样工作，同时提供创建、更新和检查 `Droplet` 对象的 helper methods。

## `create_droplet()`

创建一个逻辑液滴，并追加一个显示它在起点位置的 frame。

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

使用 `width` 和 `height` 创建矩形液滴，或用 `shape` 指定自定义 footprint：

```python
shape = {(0, 0), (0, 1), (1, 0)}

system.advanced_drop.droplets.create_droplet(
    droplet_id=2,
    origin=(20, 20),
    target=(30, 25),
    shape=shape,
)
```

主要参数：

- `droplet_id`：唯一整数 ID。
- `origin`：当前左上角 `(row, col)`。
- `target`：目标左上角 `(row, col)`。
- `shape`：可选的相对 `(row, col)` offsets。
- `width`, `height`：未提供 `shape` 时的矩形尺寸。
- `priority`：routing 顺序。当前 SIPP planner 从低数值到高数值规划。
- `vital_space`：用于避免碰撞的最小 halo。

## 批量创建

当协议从一组液滴定义开始时，使用 `add_droplets()`。

```python
system.advanced_drop.droplets.add_droplets(droplet_specs)
```

## 更新目标

`update_droplet_target()` 是执行旧计划后请求新移动的常规方式。

```python
system.advanced_drop.droplets.update_droplet_target(1, (70, 20))
system.advanced_drop.move(mode="sipp")
```

`move()` 只规划当前位置与目标不同的液滴。如果液滴已经在目标位置，请先更新目标。

`update_droplet_position()` 会改变逻辑当前位置。硬件位置不匹配后的修正应优先使用 `system.advanced_drop.correct_droplet_position()`，因为它还会向计划追加 correction frame。

## 检查液滴

```python
droplet = system.advanced_drop.droplets.get_droplet(1)
info = system.advanced_drop.droplets.get_droplet_info(1)
summary = system.advanced_drop.droplets.get_droplets_summary()
```

`get_droplet_info()` 返回当前位置、目标、形状、priority 和 vital-space 设置。

## 删除和重置

```python
system.advanced_drop.droplets.delete_droplet(1)
system.advanced_drop.clear()
```

`delete_droplet()` 删除液滴对象，但不会自动重写旧 plan frames。`clear()` 重置液滴列表和当前计划。

## 推送手动 Frame

```python
system.advanced_drop.push_frame(
    event_type="manual_hold",
    event_data={"reason": "stabilize before imaging"},
)
```

这适合在操作之间加入明确 hold 或同步点。
