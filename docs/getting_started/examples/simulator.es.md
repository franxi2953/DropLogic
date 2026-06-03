# Simulator Example

Archivo fuente:
[examples/simulator_example.py](https://github.com/franxi2953/DropLogic/blob/main/examples/simulator_example.py)

Este script demuestra un flujo continuo multi-gota usando el sistema `Simulator`.

Hace lo siguiente:

- crea 20 gotas
- asigna orígenes y destinos aleatorios
- ejecuta planificación SIPP
- lanza el plan con visualizadores activados
- reasigna nuevos objetivos aleatorios cuando termina cada ejecución

Ejecuta el script desde la raíz del repositorio con:

```bash
python3 examples/simulator_example.py
```

## Código Fuente

```python
import random
import time
from droplogic.hardware.simulator import Simulator

def main():
    # Initialize the simulator
    simulator = Simulator(log_level="INFO")
    
    # We have a 128x128 matrix by default in the simulator
    matrix_size = 128
    
    # Create 20 droplets of 2x2
    print("Creating 20 droplets of 2x2 size...")
    for i in range(1, 21):
        start_r = random.randint(0, matrix_size - 3)
        start_c = random.randint(0, matrix_size - 3)
        target_r = random.randint(0, matrix_size - 3)
        target_c = random.randint(0, matrix_size - 3)
        
        simulator.advanced_drop.droplets.create_droplet(
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
            simulator.advanced_drop.move(mode="sipp")
            
            print("Executing plan (delay 0.5s)...")
            simulator.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
            
            # Wait until the plan has finished executing
            while True:
                status = simulator.advanced_drop.executor.status()
                if not status.get("is_executing", False):
                    break
                time.sleep(0.5)

            print("Movement completed. Assigning new random targets...\\n")
            # Assign new random targets to all droplets
            for i in range(1, 21):
                target_r = random.randint(0, matrix_size - 3)
                target_c = random.randint(0, matrix_size - 3)
                simulator.advanced_drop.droplets.update_droplet_target(i, (target_r, target_c))
                
    except KeyboardInterrupt:
        print("\\nStopping simulator...")
        simulator.advanced_drop.executor.stop()
        
if __name__ == "__main__":
    main()
```
