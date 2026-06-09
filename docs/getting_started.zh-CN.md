# 入门

## 安装

**DropLogic** 是标准 Python 库，可以直接用 `pip` 安装：

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

开发时使用 editable mode：
```bash
pip install -e .
```

关于各平台原生硬件 setup，包括 DMLite runtime 文件和 Linux/Raspberry Pi 的 `libusb` 依赖，请看 [安装](installation.md)。

!!! warning "硬件驱动要求"
    要控制物理设备（例如电极矩阵、XY stage 或相机），请为目标平台安装 **DropLogic Runtime Installer** 或对应的原生 runtime assets。这些 runtime 包由硬件提供商或平台维护者单独分发，不包含在 Python 库中。
    
    另外，要启用相机支持（MVS 模块），需要从 Hikrobot 官网下载并安装官方 Machine Vision Software：
    [https://www.hikrobotics.com/en/machinevision/service/download/](https://www.hikrobotics.com/en/machinevision/service/download/)

## 基本用法：系统和模块

开始使用 **DropLogic** 前，先理解两个核心概念：**系统（Systems）** 和 **模块（Modules）**。

- **系统（System）：** 一个系统表示整台硬件机器或仿真环境。库中包含纯软件的 `simulator.py` 系统，也包含面向 Acxel 硬件的平台适配系统，例如 `box_mini1` / `BOXMini` 和 `DMLite`。`BOXMini` 和 `DMLite` 是 Acxel 平台；本仓库只包含 Python 集成层。硬件提供商信息请看 [Acxel](https://www.acxel.com/)。
- **模块（Module）：** 一个系统本质上由多个模块组成。模块控制特定硬件组件，例如电极矩阵、相机或温度控制器。模块可以有不同的 **版本或实现**（例如 `CameraV1` 或 `MicroscopeV2`），这样可以更换物理组件，同时保持同一套 DropLogic 语法。

（想更系统地理解系统、模块以及新机器如何组装，请看导航里的 **系统** 部分，最后有 [创建新系统](creating_systems.md) 指南。）

关于默认状态文件、每个系统需要的配置，以及如何把机器专属校准留在本地，请看 [配置](configuration.md)。

下面是使用 **Simulator** 系统的快速示例：

```python
from droplogic.hardware.simulator import Simulator

# 1. Initialize the system
system = Simulator(log_level="INFO")

# 2. Command your modules (e.g. create a 2x2 droplet and move it)
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2, height=2
)

# 3. Ask the system to plan and execute the movement
system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

## 内置示例

如果想看更复杂的连续工作流，可以查看仓库中的 `examples/` 目录，或在导航中打开 **入门 > 示例脚本**，那里有完整代码和 GitHub 链接：

- `examples/simulator_example.py`：纯软件演示，在 128x128 虚拟矩阵中生成 20 个大液滴，并让它们在无限连续 routing loop 中运行。
- `examples/DMLite_example.py`：运行同样的无限 routing loop，但直接绑定到 Acxel `DMLite` AM-EWOD 硬件的 DropLogic 适配层。它使用更长的 `frame_delay`，以适应真实硬件的电压驱动延迟和流体物理。
