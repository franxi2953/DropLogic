# Plan Executor

`PlanExecutor` ejecuta un `DropletPlan` sobre un sistema.

Se encarga de la ejecucion sincronizada: avanza frame a frame, actualiza posiciones de gotas, envia comandos de matriz al sistema, coordina visualizadores y puede grabar salida sincronizada.

El executor tambien es la autoridad de runtime mas util para apps externas que quieren visualizar o inspeccionar un protocolo activo. Contiene el cursor de ejecucion, el plan cargado, el ultimo frame aplicado, breakpoints, estado de seguimiento del stage y estado de grabacion sincronizada.

## Que Hace

- ejecuta planes de forma asincrona en un thread de trabajo
- envia actualizaciones de frame al sistema con un `frame_delay` controlado
- guarda estado y progreso de ejecucion
- soporta pausa, reanudacion, parada y breakpoints
- actualiza posiciones de gotas durante la ejecucion
- coordina visualizadores de matriz y streamer
- graba video sincronizado con el executor mediante `SegmentedVideoWriter`
- escribe diagnosticos cuando la ejecucion hasta breakpoint agota el tiempo
- expone estado compacto de runtime que dashboards u otras apps pueden renderizar sin leer internals crudos de hardware

## Uso Tipico

```python
system.advanced_drop.move(mode="sipp")

system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
)
```

En hardware, usa un `frame_delay` mas lento que respete la actuacion de voltaje y la respuesta del fluido. En el simulador normalmente se pueden usar delays mas cortos.

## `start()`

```python
system.advanced_drop.executor.start(
    plan=None,
    frame_delay=1.0,
    verify_positions=True,
    enable_visualizers=False,
    save_to_file=None,
    record_matrix=False,
    record_streamer=False,
    matrix_filename=None,
    streamer_filename=None,
)
```

Argumentos:

- `plan`: plan a ejecutar. Si es `None`, usa `system.advanced_drop.plan`.
- `frame_delay`: segundos entre frames.
- `verify_positions`: activa validacion por vision si el sistema lo soporta.
- `enable_visualizers`: inicia/actualiza visualizadores de matriz y streamer.
- `save_to_file`: path, o lista de paths, donde guardar `plan` y `droplets` como pickle.
- `record_matrix`: graba frames del matrix visualizer sincronizados con el executor.
- `record_streamer`: graba frames del streamer visualizer sincronizados con el executor.
- `matrix_filename`: path de salida para video de matriz.
- `streamer_filename`: path de salida para video de streamer.

## Pausa, Reanudacion, Stop

```python
executor = system.advanced_drop.executor

executor.pause()
print(executor.status())

executor.resume()
executor.stop()
```

`status()` devuelve:

- `is_executing`
- `current_frame`
- `total_frames`
- `frames_executed`
- `execution_time`
- `progress`
- `last_update`
- `breakpoints`
- `breakpoint_reached`
- `stage_tracking_mode`
- `fixed_stage_position`
- `verify_positions`
- `last_stage_target_position`
- `last_frame`

`current_frame` es el siguiente frame que el executor intentara ejecutar. Si una app externa quiere mostrar el ultimo frame realmente aplicado, debe preferir `status()["last_frame"]["index"]` cuando exista. Esto importa en breakpoints: despues de aplicar el frame `N`, el executor puede quedar pausado con `current_frame == N + 1`, mientras `last_frame.index == N`.

## Estado Del Plan Para Apps Externas

Las UIs externas deberian tratar el executor y el plan como una fuente estructurada de escena, no como screenshots. Las entradas utiles son:

- `executor.status()` para cursor de ejecucion, progreso, breakpoints, modo de seguimiento del stage y ultimo frame aplicado.
- `executor.current_plan` para el plan que se esta ejecutando. Si el executor aun no ha arrancado, usa `system.advanced_drop.plan`.
- `plan.frames[frame_index]` para la matriz activa de electrodos en un frame concreto.
- `plan.droplet_trajectories` para rutas de gotas en el tiempo.
- `plan.active_droplets_per_frame` para saber que gotas estan activas en cada frame.
- `plan.events` y `plan.event_id_per_frame` para etiquetas de pasos del protocolo.
- `system.advanced_drop.droplets` para forma, target, prioridad y metadata de vital-space de cada gota.

Para dashboards de navegador u otras apps, usa un DTO compacto. No envies la matriz completa 128 x 128 como JSON anidado en cada update si solo necesitas renderizar; codifica electrodos activos como rangos por fila o spans de celdas activas.

Ejemplo de forma:

```json
{
  "available": true,
  "scene_mode": "advanced_drop",
  "revision": "compact-state-hash",
  "matrix": {
    "shape": [128, 128],
    "encoding": "active_ranges_by_row",
    "rows": {
      "40": [[1, 6]],
      "41": [[1, 6]]
    }
  },
  "executor": {
    "is_executing": true,
    "current_frame": 42,
    "last_frame": {"index": 41},
    "total_frames": 180,
    "stage_tracking_mode": "follow_droplets"
  },
  "plan": {
    "planning_success": true,
    "current_event": [41, "move", {"event_id": 3}]
  },
  "droplets": [
    {
      "id": 204,
      "position": [40, 1],
      "target": [70, 20],
      "bbox": {"row_min": 40, "row_max": 43, "col_min": 1, "col_max": 4},
      "path": [[40, 1], [41, 1], [42, 2]]
    }
  ]
}
```

Este es el patron para integraciones tipo dashboard: la app renderiza su propio canvas de matriz desde estado de plan/executor, mientras que los frames del visualizer OpenCV quedan como fallback para debug o snapshots directos. En MCP, `execution_scene` expone la misma idea como una tool compacta y acotada de estado. Aun asi, los agentes deberian preferir resumenes mas pequenos como `plan_summary`, `executor_status`, `droplets_summary` y `matrix_summary` cuando no necesitan la escena combinada.

## Guardar El Protocolo

Usa `save_to_file` cuando quieras un snapshot que se pueda abrir luego en el plan debugger.

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

El pickle contiene:

- `plan`
- `droplets`

## Grabar Video Sincronizado

La grabacion debe hacerse desde el executor, no directamente desde el loop del visualizer.

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    matrix_filename="runs/matrix.mp4",
)
```

Si el sistema tiene streamer visualizer:

```python
system.advanced_drop.executor.start(
    frame_delay=0.5,
    enable_visualizers=True,
    record_matrix=True,
    record_streamer=True,
    matrix_filename="runs/matrix.mp4",
    streamer_filename="runs/streamer.mp4",
)
```

El FPS se deriva de `frame_delay`, asi que cada frame de video corresponde a un frame ejecutado del plan.

## Breakpoints

Los breakpoints pausan la ejecucion despues de ejecutar un frame.

```python
executor = system.advanced_drop.executor

executor.add_breakpoint(25)
executor.start(frame_delay=0.5, enable_visualizers=True)

executor.execute_until_breakpoint()
print(executor.status()["current_frame"])
```

Los breakpoints son de un solo uso: el executor los elimina despues de alcanzarlos.

Para continuar:

```python
executor.resume()
```

## Extension Dinamica Del Plan

Puedes pausar en un breakpoint, anadir operaciones y reanudar.

```python
executor.add_breakpoint(20)
executor.start(frame_delay=0.5, save_to_file="runs/protocol.pkl")
executor.execute_until_breakpoint_or_raise(label="first move")

system.advanced_drop.droplets.update_droplet_target(1, (60, 60))
system.advanced_drop.move(mode="sipp")

executor.resume()
```

Cuando `resume()` detecta un `system.advanced_drop.plan` mas nuevo, recarga el plan y refresca los archivos configurados con `save_to_file`.

## Posicion De Gota En Runtime

```python
pos = system.advanced_drop.executor.get_droplet_position(1)
```

Esto devuelve la ultima posicion ejecutada, no necesariamente la posicion final planificada.

Usa `system.advanced_drop.get_droplet_position(1)` para la posicion final planificada.

## Donde Vive

- `droplogic/utils/advanced_drop/plan_executor.py`
- `droplogic/utils/recording.py`

## Limite de Diseno

El executor debe ser la unica capa que guarda y graba planes de forma sincronizada. Los visualizadores pueden exponer frames y snapshots, pero la grabacion a nivel de executor mantiene la matriz y el streamer alineados con la linea temporal del plan.
