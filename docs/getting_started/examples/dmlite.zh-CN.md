# DMLite 示例

源码文件：
[examples/DMLite_example.py](https://github.com/franxi2953/DropLogic/blob/main/examples/DMLite_example.py)

这个脚本演示与模拟器示例相同的连续多液滴循环，但运行在真实 `DMLite` 系统上。

`DMLite` 是 Acxel 的硬件平台。本仓库通过 Python 系统和电极矩阵模块对它进行适配；硬件本身不是这个库的一部分。硬件提供商信息请看 [Acxel](https://www.acxel.com/)。

这个示例可以在任何受支持的原生 host 上控制真实 DMLite 硬件：Windows x86_64、macOS Apple Silicon、Linux x86_64、Raspberry Pi OS 64-bit 或 Raspberry Pi OS 32-bit。请先安装匹配的 DropLogic runtime；在 Linux 和 Raspberry Pi OS 上，还要安装 `libusb`。

它会：

- 初始化真实 `DMLite` 系统
- 创建 20 个带随机起点和目标的液滴
- 运行 SIPP 规划
- 用适合硬件的较慢 delay 执行计划
- 每次循环完成后分配新的随机目标

从仓库根目录运行：

```bash
PYTHONPATH=. python3 examples/DMLite_example.py
```

如果 DropLogic 已经通过 `pip install .` 安装，运行：

```bash
python3 examples/DMLite_example.py
```

## 源码

```python
import random
import time
from droplogic.hardware.DMLite import DMLite

def main():
    # Initialize the real hardware system
    system = DMLite(log_level="INFO")
    
    # We have a 128x128 matrix by default
    matrix_size = 128
    
    # Create 20 droplets of 2x2
    print("Creating 20 droplets of 2x2 size for DMLite hardware...")
    for i in range(1, 21):
        start_r = random.randint(0, matrix_size - 3)
        start_c = random.randint(0, matrix_size - 3)
        target_r = random.randint(0, matrix_size - 3)
        target_c = random.randint(0, matrix_size - 3)
        
        system.advanced_drop.droplets.create_droplet(
            droplet_id=i,
            origin=(start_r, start_c),
            target=(target_r, target_c),
            width=2,
            height=2
        )
        print(f"Droplet {i} created: from ({start_r},{start_c}) to ({target_r},{target_c})")
        
    try:
        while True:
            print("\\nPlanning SIPP multi-droplet routing to targets...")
            system.advanced_drop.move(mode="sipp")
            
            print("Executing plan (delay 1.0s)...")
            system.advanced_drop.executor.start(frame_delay=1.0, enable_visualizers=True)
            
            # Wait until the plan has finished executing
            while True:
                status = system.advanced_drop.executor.status()
                if not status.get("is_executing", False):
                    break
                time.sleep(1.0)

            print("Movement completed. Assigning new random targets...\\n")
            # Assign new random targets to all droplets
            for i in range(1, 21):
                target_r = random.randint(0, matrix_size - 3)
                target_c = random.randint(0, matrix_size - 3)
                system.advanced_drop.droplets.update_droplet_target(i, (target_r, target_c))
                
    except KeyboardInterrupt:
        print("\\nStopping system...")
        system.advanced_drop.executor.stop()
        
if __name__ == "__main__":
    main()
```
