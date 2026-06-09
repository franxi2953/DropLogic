# Objetos De Plan

`AdvancedDrop` guarda la salida del protocolo en `system.advanced_drop.plan`.

El plan es un `DropletPlan`: una descripcion frame por frame de estados de matriz, trayectorias de gotas, gotas activas y metadata de eventos.

## Campos De `DropletPlan`

- `frames`: lista de arrays 2D. Cada frame es la matriz de electrodos enviada al sistema.
- `frame_count`: numero de frames.
- `droplet_trajectories`: diccionario de ID de gota a posiciones `(row, col)` en el tiempo.
- `active_droplets_per_frame`: IDs de gotas activas por frame.
- `events`: lista cronologica `(frame_index, event_type, metadata)`.
- `planning_success`: booleano global.
- `conflicts_resolved`: metadata diagnostica de conflictos.
- `targets_reached`: diccionario de ID a booleano.
- `event_id_per_frame`: etiqueta de evento para cada frame.

## Inspeccionar Un Plan

```python
plan = system.advanced_drop.plan

print(plan.frame_count)
print(plan.planning_success)
print(plan.targets_reached)
print(plan.events)
```

Para inspeccionar un frame:

```python
frame_10 = plan.frames[10]
active_ids = plan.active_droplets_per_frame[10]
```

## Obtener Posicion De Una Gota

`AdvancedDrop.get_droplet_position()` devuelve la posicion final planificada.

```python
final_pos = system.advanced_drop.get_droplet_position(1)
```

`PlanExecutor.get_droplet_position()` devuelve la ultima posicion ejecutada durante runtime.

```python
runtime_pos = system.advanced_drop.executor.get_droplet_position(1)
```

## Extender Planes

La mayoria de operaciones publicas extienden automaticamente el plan actual:

```python
ad.droplets.create_droplet(1, (10, 10), (20, 20), width=2, height=2)
ad.move(mode="sipp")
ad.mix(1, mode="2d_loop", cycles=3)
ad.merge([1, 2], target=(40, 40))
```

Usa `extend_plan()` directamente solo al componer un `DropletPlan` personalizado.

```python
ad.plan = ad.extend_plan(
    existing_plan=ad.plan,
    new_plan=custom_plan,
    event_type="custom_step",
    event_data={"source": "external planner"},
)
```

## Eliminar Frames Duplicados

```python
ad.remove_duplicates(start_idx=0, end_idx=-1)
```

Elimina frames duplicados en un rango y remapea trayectorias/eventos. Usalo despues de planificar, no mientras el executor corre.

Puede unir limites de evento utiles para breakpoints y diagnostico, asi que evita usarlo rutinariamente en produccion salvo que hayas revisado el resultado.

## Fusionar Eventos Secuenciales

`merge_sequential_events()` combina dos rangos de evento consecutivos.

```python
new_event_id = ad.merge_sequential_events(
    event_id_1=3,
    event_id_2=4,
    force=False,
)
```

Usa `force=True` solo si entiendes los conflictos de electrodos que se estan sobrescribiendo.

## Guardar Un Plan

Normalmente el guardado lo maneja el executor:

```python
ad.executor.start(
    frame_delay=0.5,
    save_to_file="runs/protocol.pkl",
)
```

El pickle contiene `plan` y `droplets`, formato entendido por el plan debugger.
