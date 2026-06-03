# Plan Executor

`PlanExecutor` ejecuta un `DropletPlan` sobre un sistema.

Se encarga de la ejecucion sincronizada: avanza frame a frame, actualiza posiciones de gotas, envia comandos de matriz al sistema, coordina visualizadores y puede grabar salida sincronizada.

## Que Hace

- ejecuta planes de forma asincrona en un thread de trabajo
- envia actualizaciones de frame al sistema con un `frame_delay` controlado
- guarda estado y progreso de ejecucion
- soporta pausa, reanudacion, parada y breakpoints
- actualiza posiciones de gotas durante la ejecucion
- coordina visualizadores de matriz y streamer
- graba video sincronizado con el executor mediante `SegmentedVideoWriter`
- escribe diagnosticos cuando la ejecucion hasta breakpoint agota el tiempo

## Uso Tipico

```python
system.advanced_drop.move(mode="sipp")

system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

En hardware, usa un `frame_delay` mas lento que respete la actuacion de voltaje y la respuesta del fluido. En el simulador normalmente se pueden usar delays mas cortos.

## Donde Vive

- `droplogic/utils/advanced_drop/plan_executor.py`
- `droplogic/utils/recording.py`

## Limite de Diseno

El executor debe ser la unica capa que guarda y graba planes de forma sincronizada. Los visualizadores pueden exponer frames y snapshots, pero la grabacion a nivel de executor mantiene la matriz y el streamer alineados con la linea temporal del plan.
