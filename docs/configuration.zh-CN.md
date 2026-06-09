# 配置

`config.json` 是 DropLogic 系统使用的默认状态文件。

公开默认文件位于仓库根目录：

```text
config.json
```

如果实例化系统时没有传入自定义路径，系统会从当前工作目录加载 `config.json`。如果从克隆仓库的根目录运行示例，这就是仓库默认文件：

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite(config_file="config.json")
```

如果脚本从其他目录运行，请传入显式路径。你也可以保留仓库默认文件，并使用一份机器专属副本：

```python
system = DMLite(config_file="local_config.json")
```

`local_config*.json`、`config.local.json` 和 `calibration_data.json` 已被 Git 忽略，因此私有机器校准可以留在本地。

`DMLite` 和 `BOXMini` 是 [Acxel](https://www.acxel.com/) 的硬件平台。本仓库包含围绕受支持硬件的 Python 适配器和共享控制逻辑；供应商硬件和原生 runtime 文件不属于本库。

## 应该提交到仓库吗？

应该。基础 `config.json` 是公开仓库的一部分，因为它定义默认 schema，并作为库的起点。

不要把 secrets、私有 SDK 路径、原生库、API keys 或个人凭据放进这个文件。供应商 SDK 文件和原生 runtime assets 会被有意排除在仓库之外。

## DMLite 需要什么

`DMLite` 只需要 `electrode_matrix` block。

必需字段：

| 字段 | 含义 | 默认值 |
| --- | --- | --- |
| `electrode_matrix.rows` | 矩阵行数 | `128` |
| `electrode_matrix.columns` | 矩阵列数 | `128` |
| `electrode_matrix.voltage` | 电极驱动电压 | `55` |
| `electrode_matrix.version` | 低层矩阵实现 | `DMLite` |
| `electrode_matrix.matrix` | Runtime 矩阵状态 | 启动时为 `[]` |

对于当前 DMLite setup，仓库默认值是合适的。系统启动时会重置 `electrode_matrix.matrix`，因此用户通常不需要手动编辑该字段。

`electrode_matrix.version: "DMLite"` 会加载当前 OS 和 CPU 架构对应的原生 runtime。支持的 DMLite runtimes 包括 Windows x86_64、macOS Apple Silicon、Linux x86_64、Raspberry Pi OS 64-bit 和 Raspberry Pi OS 32-bit。如果没有安装匹配的 runtime 文件，`DMLite()` 会抛出清晰错误。

## Simulator 需要什么

`Simulator` 使用：

| 字段 | 含义 |
| --- | --- |
| `electrode_matrix.rows` / `columns` | 仿真矩阵尺寸 |
| `electrode_matrix.voltage` | 仿真电压值 |
| `xy_stage.position` | mock stage 初始位置 |

对于只使用模拟器的工作流，其余字段可以保留默认值。

## BOXMini 类型系统需要什么

更大的硬件系统会使用更多 block：

| Block | 用途 | 用户通常编辑 |
| --- | --- | --- |
| `temperature` | 温度串口模块 | `Port`, `version` |
| `xy_stage` | Stage 位置、运动参数和限制 | `safe_limits`, `position`, `motion_params` |
| `camera_settings` | MVS 相机曝光/增益 | `auto_exposure`, `exposure_time`, `gain`, `version` |
| `microscope_settings` | 显微镜曝光/通道/串口 | `Port`, `current_channel`, `total_channels` |
| `light_settings` | ring/coaxial 光控制器 | `VID`, `PID`, `upled_serial`, intensities, `version` |
| `capacitive_feedback` | feedback 模块选择 | `version` |

只有当所选系统确实实例化这些模块时，才需要填写对应 block。

## 校准 Block

`calibration` 包含 runtime 中用于相机像素转换、电极/stage 转换和可选 XY backlash compensation 的测量值。

测量并更新 `chip_origin`、`inter_row` 和 `inter_column`，以匹配每台物理机器和芯片对准状态。

## 实用编辑流程

1. 从仓库的 `config.json` 开始。
2. 复制为 `local_config.json`，用于机器专属修改。
3. 只更新你要实例化的系统实际使用的 block。
4. 运行 Simulator 或 DMLite smoke test。
5. 只提交 schema/default 的变化，不提交私有机器校准。
