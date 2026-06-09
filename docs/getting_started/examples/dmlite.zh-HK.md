# DMLite 範例

源碼檔案：
[examples/DMLite_example.py](https://github.com/franxi2953/DropLogic/blob/main/examples/DMLite_example.py)

呢個腳本示範同模擬器範例相同嘅連續多液滴循環，但係喺真實 `DMLite` 系統上運行。

`DMLite` 係 Acxel 嘅硬件平台。本倉庫透過 Python 系統同電極矩陣模組去適配佢；硬件本身唔係呢個函式庫嘅一部分。硬件供應商資料請睇 [Acxel](https://www.acxel.com/)。

呢個範例可以喺任何受支援嘅原生 host 上控制真實 DMLite 硬件：Windows x86_64、macOS Apple Silicon、Linux x86_64、Raspberry Pi OS 64-bit 或 Raspberry Pi OS 32-bit。請先安裝相配嘅 DropLogic runtime；喺 Linux 同 Raspberry Pi OS 上，仲要安裝 `libusb`。

佢會：

- 初始化真實 `DMLite` 系統
- 建立 20 個有隨機起點同目標嘅液滴
- 運行 SIPP 規劃
- 用適合硬件嘅較慢 delay 執行計劃
- 每次循環完成後分配新嘅隨機目標

由倉庫根目錄執行：

```bash
PYTHONPATH=. python3 examples/DMLite_example.py
```

如果 DropLogic 已經用 `pip install .` 安裝，執行：

```bash
python3 examples/DMLite_example.py
```

## 源碼

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
