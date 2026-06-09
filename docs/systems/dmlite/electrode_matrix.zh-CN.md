# DMLite 模块：电极矩阵

`DMLite` 系统目前围绕一个真实硬件模块构建：电极矩阵。

`DMLite` 是 Acxel 的硬件平台。本页记录围绕该硬件的 Python 适配器；硬件本身不属于本仓库。硬件提供商信息请看 [Acxel](https://www.acxel.com/)。

## 在系统中的作用

这个模块负责把系统级电极命令转换成 Acxel DMLite 硬件使用的具体低层实现。

在系统层，`DMLite` 使用该模块来：

- 应用矩阵更新
- 设置工作电压
- 关闭电极
- 发送与液滴相关的驱动 pattern

## 分层

电极 stack 被有意拆成几层：

1. **系统层**：`droplogic.hardware.DMLite`
2. **模块 wrapper**：`droplogic.hardware.modules.electrode_matrix.ElectrodeMatrixModule`
3. **版本实现**：`droplogic.hardware.modules.electrode_matrix.versions.DMLite`

这种分离很重要，因为它让系统定义保持清晰，同时允许底层硬件实现随 host 平台变化。

## Backends

`DMLite` 系统使用一个 Python backend，并为当前 host 选择匹配的原生 runtime：

| Host | Runtime 文件 | 用途 |
| --- | --- | --- |
| Windows x86_64 | `sdk.dll` | 原生硬件控制。 |
| macOS Apple Silicon | `sdk.dylib` | 原生硬件控制。 |
| Linux x86_64 | `linux-x86_64/sdk.so` | 使用 `libusb` 的原生硬件控制。 |
| Raspberry Pi OS 64-bit | `linux-aarch64/sdk.so` | 使用 `libusb` 的原生硬件控制。 |
| Raspberry Pi OS 32-bit | `linux-armv7l/sdk.so` | 使用 `libusb` 的原生硬件控制。 |

所有受支持平台都使用同一套 Python API：

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

原生 runtime 会从已安装的 DropLogic runtime 目录、`DROPLOGIC_RUNTIME_DIR`，或开发 checkout 中的本地 `vendor_bin/electrode_matrix/dmlite/` 目录解析。不受支持的 host 或缺失的 runtime 文件会抛出清晰的 runtime error。

在 Linux 和 Raspberry Pi OS 上，运行硬件控制前请安装 `libusb-1.0-0`。macOS Apple Silicon 使用 Homebrew `libusb`，除非你的 runtime 包已经捆绑它。

## 为什么需要模块 Wrapper

Wrapper 不只是额外结构。它让我们可以：

- 标准化系统看到的公共 API
- 之后替换实现，而不用重写系统
- 把版本相关细节从高层机器定义中隔离出来

## 当前行为

在当前 DMLite setup 中，该模块暴露以下操作：

- `set_chip(...)`
- `set_voltage(...)`
- `deactivate_all()`
- `set_droplet(...)`
- `set_droplets(...)`
- `send_ascii_command(...)`

这些操作足以让系统驱动电极表面，同时让 `AdvancedDrop` 专注于规划，而不是硬件协议细节。

## 设计要点

这一页展示了 DropLogic 的核心模式：

- **系统** 定义机器是什么
- **模块** 定义机器具备什么能力块
- **版本** 定义该能力在具体设备上如何实现
