# AdvancedDrop

`AdvancedDrop` 係連接到 `DropSystem` 嘅高層液滴操作層。

系統（例如 `Simulator` 同 `DMLite`）初始化佢之後，透過下面嘅屬性暴露：

```python
system.advanced_drop
```

## 職責

- 透過 `system.advanced_drop.droplets` 管理液滴
- 建立同更新 `DropletPlan` 物件
- 規劃基於 SIPP 嘅移動
- 為分割、合併、混合同抽取建立操作計劃
- 將規劃輸出連接到 `PlanExecutor`
- 當系統有相機同 stage 模組時，可選連接到 vision-based validation

## 座標約定

DropLogic 使用 0-indexed 矩陣座標，表示為 `(row, col)` tuple。呢個同 NumPy array 順序一致：`matrix[row, col]`。

唔好將 AdvancedDrop 位置理解成笛卡爾 `(x, y)`。如果由圖像或 stage 座標思考，最接近嘅映射係：

- `row` 係垂直矩陣索引，類似 `y`
- `col` 係水平矩陣索引，類似 `x`
- 所以 `(x, y)` 通常對應 `(row, col) = (y, x)`

喺邏輯矩陣約定中，`(0, 0)` 係未旋轉矩陣左上角電極。`row` 增大向下移動，`col` 增大向右移動。

對於液滴，`origin_corner` 同 `target_corner` 係液滴 footprint 嘅左上角。`shape` 儲存為相對該左上角嘅 offsets。

```python
ad.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(30, 40),
    width=2,
    height=2,
)
```

低層硬件 helpers 可能暴露自己嘅 indexing 規則。AdvancedDrop 嘅 plans、droplets、trajectories、breakpoints 同 debugger positions 都使用 0-indexed `(row, col)`。

## Matrix Visualizer 方向

planner 同 plan debugger 使用上面嘅邏輯矩陣約定。互動式 `MatrixVisualizer` 預設會將該邏輯矩陣旋轉顯示：

- 預設顯示旋轉：順時針 `90` 度
- 邏輯 `(0, 0)` 顯示喺 matrix visualizer 右上附近
- `row` 增大會喺預設顯示中向左移動
- `col` 增大會喺預設顯示中向下移動

呢個只係顯示變換，唔會改變你喺 AdvancedDrop 入面寫 plan、建立液滴或尋址電極嘅方式。

```python
system.visualizers.matrix.set_matrix_rotation(0)
```

支持嘅顯示旋轉係 `0`、`90`、`180`、`270` 順時針度數。點擊會被轉返做邏輯 `(row, col)` 再傳畀 callbacks。

## 公共介面

- **液滴管理**：建立、更新、檢查同刪除邏輯液滴。
- **移動**：為目標唔同於目前位置嘅液滴規劃 SIPP movement。
- **分割同抽取**：由 reservoirs 抽取液滴，或者將一滴分成對稱子滴。
- **合併**：將多滴 route 到一個目標 footprint。
- **混合**：運行 split-recombine 或 2D loop mixing patterns。
- **視覺同修正**：驗證、偵測 condensates、修正邏輯位置，並將 stage 移到液滴。
- **Plan objects**：理解 frames、trajectories、events 同 plan extension。

## 最小範例

```python
ad = system.advanced_drop

ad.droplets.create_droplet(1, origin=(8, 8), target=(20, 20), width=2, height=2)
plan = ad.move(mode="sipp")

print(plan.frame_count)
print(plan.planning_success)
```

結果會保存為 `ad.plan`，亦會由規劃函數返回。

## 安全說明

- 唔好喺 protocol scripts 入面直接修改 `droplet.origin_corner`，除非你明確要繞過 planner state。
- 如果硬件移動失敗後物理液滴喺其他地方，請使用 `correct_droplet_position()`。
- `move(mode="sipp")` 係目前唯一公開實現嘅移動模式。其他 `mode` 會拋出 `ValueError`。
- 將 `remove_duplicate_frames=True` 視為開發/除錯選項；佢可能縮短計劃，但亦可能合併對 breakpoints 同診斷有用嘅事件邊界。

## 程式位置

- `droplogic/utils/advanced_drop/__init__.py`
- `droplogic/utils/advanced_drop/common.py`
- `droplogic/utils/advanced_drop/move.py`
- `droplogic/utils/advanced_drop/splitting.py`
- `droplogic/utils/advanced_drop/merge.py`
- `droplogic/utils/advanced_drop/mixing.py`
- `droplogic/utils/advanced_drop/feedback.py`

## 設計邊界

`AdvancedDrop` 唔應該知道硬件設備嘅低層協議。佢建立同操作矩陣 frame plans；systems 同 modules 再將呢啲 plans 翻譯成硬件命令。
