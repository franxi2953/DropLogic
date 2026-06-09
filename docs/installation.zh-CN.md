# 安装

## Python 包

从源码 checkout 安装 DropLogic：

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

开发时可以使用 editable mode：

```bash
pip install -e .
```

## DMLite 原生 Runtime

Python 包包含 DropLogic 的适配层代码。真实硬件控制还需要与主机操作系统和 CPU 架构匹配的 DropLogic 原生 runtime assets。这些原生文件不会放在公开的 Python 源码树里，而是单独分发。

安装了对应 runtime 后，`DMLite` 支持以下主机：

| 主机 | Runtime 文件 |
| --- | --- |
| Windows x86_64 | `electrode_matrix/dmlite/sdk.dll` |
| macOS Apple Silicon | `electrode_matrix/dmlite/sdk.dylib` |
| Linux x86_64 | `electrode_matrix/dmlite/linux-x86_64/sdk.so` |
| Raspberry Pi OS 64-bit | `electrode_matrix/dmlite/linux-aarch64/sdk.so` |
| Raspberry Pi OS 32-bit | `electrode_matrix/dmlite/linux-armv7l/sdk.so` |

DropLogic 会从已安装的 runtime 目录、`DROPLOGIC_RUNTIME_DIR`，或本地源码 checkout 中的 `vendor_bin/electrode_matrix/dmlite/` 解析这些文件。

如果当前操作系统或架构对应的文件不存在，`DMLite()` 会抛出 runtime error，而不是静默加载错误的 backend。

## Linux 和 Raspberry Pi 依赖

在 Debian、Ubuntu 和 Raspberry Pi OS 上，先安装 `libusb` runtime 包：

```bash
sudo apt update
sudo apt install -y libusb-1.0-0
```

如果要在 Linux 或 Raspberry Pi 上从源码编译 DMLite runtime，也需要开发包：

```bash
sudo apt install -y build-essential pkg-config libusb-1.0-0-dev python3
```

如果希望 Linux 或 Raspberry Pi 不用 `sudo` 访问 USB，请安装 runtime 源码包里提供的 DMLite udev rule。在该 runtime 源码包目录下运行：

```bash
sudo cp udev/99-dmlite.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

然后拔下并重新连接 DMLite 控制器。

## macOS 依赖

当前 macOS runtime 面向 Apple Silicon 构建。除非 runtime 包已经捆绑 `libusb`，否则请用 Homebrew 安装：

```bash
brew install libusb
```

## 快速测试

从仓库根目录运行：

```bash
PYTHONPATH=. python3 examples/DMLite_example.py
```

如果 DropLogic 已经通过 `pip install .` 安装，通常不需要 `PYTHONPATH=.`：

```bash
python3 examples/DMLite_example.py
```

如果只想测试规划和可视化，而不连接硬件，请运行模拟器示例：

```bash
python3 examples/simulator_example.py
```
