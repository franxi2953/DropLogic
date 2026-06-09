# AdvancedDrop

`AdvancedDrop` 是连接到 `DropSystem` 的高层液滴操作层。

系统（例如 `Simulator` 和 `DMLite`）初始化它之后，通过下面的属性暴露：

```python
system.advanced_drop
```

## 职责

- 通过 `system.advanced_drop.droplets` 管理液滴
- 构建和更新 `DropletPlan` 对象
- 规划基于 SIPP 的移动
- 为分裂、合并、混合和提取创建操作计划
- 将规划输出连接到 `PlanExecutor`
- 当系统具备相机和 stage 模块时，可选连接到 vision-based validation

## 坐标约定

DropLogic 使用 0-indexed 矩阵坐标，表示为 `(row, col)` tuple。这与 NumPy 数组的顺序一致：`matrix[row, col]`。

不要把 AdvancedDrop 位置理解为笛卡尔 `(x, y)`。如果从图像或 stage 坐标思考，最接近的映射是：

- `row` 是垂直矩阵索引，类似 `y`
- `col` 是水平矩阵索引，类似 `x`
- 因此 `(x, y)` 通常对应 `(row, col) = (y, x)`

在逻辑矩阵约定中，`(0, 0)` 是未旋转矩阵左上角电极。`row` 增大向下移动，`col` 增大向右移动。

对于液滴，`origin_corner` 和 `target_corner` 是液滴 footprint 的左上角。`shape` 存储为相对该左上角的 offsets。

```python
ad.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(30, 40),
    width=2,
    height=2,
)
```

这会创建一个 2x2 液滴，身体从 row `10`、column `10` 开始，目标左上角为 row `30`、column `40`。

低层硬件 helpers 可能暴露自己的 indexing 规则。AdvancedDrop 的 plans、droplets、trajectories、breakpoints 和 debugger positions 都使用 0-indexed `(row, col)`。

## Matrix Visualizer 方向

planner 和 plan debugger 使用上面的逻辑矩阵约定。交互式 `MatrixVisualizer` 默认会把该逻辑矩阵旋转显示：

- 默认显示旋转：顺时针 `90` 度
- 逻辑 `(0, 0)` 显示在 matrix visualizer 的右上附近
- `row` 增大会在默认显示中向左移动
- `col` 增大会在默认显示中向下移动

这只是显示变换，不会改变你在 AdvancedDrop 中写 plan、创建液滴或寻址电极的方式。

要使用未旋转显示：

```python
system.visualizers.matrix.set_matrix_rotation(0)
```

支持的显示旋转为 `0`、`90`、`180`、`270` 顺时针度数。点击会被转换回逻辑 `(row, col)` 后再传给 callbacks。

## 公共接口

- **液滴管理**：创建、更新、检查和删除逻辑液滴。
- **移动**：为目标不同于当前位置的液滴规划 SIPP movement。
- **分裂和提取**：从 reservoirs 提取液滴，或把一滴分成对称子滴。
- **合并**：把多滴 route 到一个目标 footprint。
- **混合**：运行 split-recombine 或 2D loop mixing patterns。
- **视觉和校正**：验证、检测 condensates、校正逻辑位置，并把 stage 移到液滴。
- **Plan objects**：理解 frames、trajectories、events 和 plan extension。

## 最小示例

```python
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(8, 8), target=(20, 20), width=2, height=2)
plan = ad.move(mode="sipp")

print(plan.frame_count)
print(plan.planning_success)
```

结果会保存为 `ad.plan`，也会从规划函数返回。

## 安全说明

- 不要在 protocol scripts 中直接修改 `droplet.origin_corner`，除非你明确要绕过 planner state。
- 如果硬件移动失败后物理液滴在别处，请使用 `correct_droplet_position()`。
- `move(mode="sipp")` 是当前唯一公开实现的移动模式。其他 `mode` 会抛出 `ValueError`。
- 把 `remove_duplicate_frames=True` 视为开发/调试选项；它可能缩短计划，但也可能合并对 breakpoints 和诊断有用的事件边界。

## 代码位置

- `droplogic/utils/advanced_drop/__init__.py`
- `droplogic/utils/advanced_drop/common.py`
- `droplogic/utils/advanced_drop/move.py`
- `droplogic/utils/advanced_drop/splitting.py`
- `droplogic/utils/advanced_drop/merge.py`
- `droplogic/utils/advanced_drop/mixing.py`
- `droplogic/utils/advanced_drop/feedback.py`

## 设计边界

`AdvancedDrop` 不应该知道硬件设备的低层协议。它创建和操作矩阵 frame plans；systems 和 modules 再把这些 plans 翻译成硬件命令。
