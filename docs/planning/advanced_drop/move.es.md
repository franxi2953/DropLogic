# Movimiento

`move()` planifica movimiento coordinado para gotas cuya posicion actual difiere de su objetivo.

Para mover de nuevo una gota existente, actualiza primero su objetivo:

```python
system.advanced_drop.droplets.update_droplet_target(1, (60, 20))
system.advanced_drop.move(mode="sipp")
```

```python
plan = system.advanced_drop.move(mode="sipp")
```

El `DropletPlan` devuelto tambien se guarda como `system.advanced_drop.plan`.

## Firma Publica

```python
system.advanced_drop.move(
    mode="sipp",
    remove_duplicate_frames=False,
    merge_on_failure=True,
    **kwargs,
)
```

`kwargs` se reenvian al planner SIPP de bajo nivel.

## Modos

Actualmente, `mode="sipp"` es el unico modo de movimiento implementado.

SIPP significa Safe Interval Path Planning. En DropLogic enruta gotas en espacio y tiempo, reservando cuerpos, halos `vital_space` y transiciones de borde para reducir colisiones.

Si se pasa otro modo, el planner lanza:

```python
ValueError: Unsupported mode
```

## Movimiento Basico

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando move(mode=\"sipp\") moviendo una gota 2x2 con ruta superpuesta](../../assets/advanced-drop/move-basic.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>move(mode="sipp")</code>: una gota 2x2 enrutada a un nuevo objetivo</figcaption>
</figure>

```python
ad = system.advanced_drop
ad.clear()

ad.droplets.create_droplet(1, origin=(30, 18), target=(30, 48), width=2, height=2)

plan = ad.move(
    mode="sipp",
    planning_timeout=60,
    max_path_frames=120,
)
```

## Movimiento Multi-Gota

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando movimiento SIPP coordinado para veinte gotas](../../assets/advanced-drop/move-coordinated.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de movimiento coordinado <code>move(mode="sipp")</code>: veinte gotas 1x1 enrutadas por la matriz</figcaption>
</figure>

Solo se planifican gotas cuyo `origin_corner != target_corner`. Las gotas que ya estan en objetivo se mantienen como gotas activas al extender planes.

Cuando el matrix visualizer esta activo, `PlanExecutor` puede mostrar `droplet_trajectories` como rutas superpuestas.

## Opciones Utiles Del Planner

- `planning_timeout`: tiempo maximo de planificacion en segundos.
- `max_iterations`: limite de iteraciones por gota.
- `max_frames`: limite de frames generados.
- `max_path_frames`: limite de longitud dentro de la busqueda SIPP.
- `reservation_horizon`: frames futuros usados para reservar posiciones iniciales y finales.
- `reserve_final_positions`: mantiene reservadas las posiciones finales al terminar una ruta.
- `ignore_vital_space_pairs`: pares de IDs autorizados a ignorar separacion `vital_space`.
- `debug_visualization`: marca areas reservadas o vital-space en frames generados.

```python
plan = ad.move(
    mode="sipp",
    planning_timeout=60,
    max_path_frames=200,
    reservation_horizon=250,
    ignore_vital_space_pairs={(1, 2)},
)
```

## Manejo De Fallos

Por defecto, `merge_on_failure=True` permite anadir salida parcial al plan actual.

Si quieres inspeccionar un intento fallido sin mutar `ad.plan`, usa:

```python
candidate = ad.move(mode="sipp", merge_on_failure=False)

if not candidate.planning_success:
    print(candidate.targets_reached)
```

Con `merge_on_failure=False`, las gotas que fallaron vuelven a sus esquinas logicas anteriores y el plan devuelto no se asigna a `ad.plan`.

## Re-Target Tras Ejecucion

```python
ad.droplets.update_droplet_target(1, (60, 20))
ad.move(mode="sipp")
ad.executor.start(frame_delay=0.5, enable_visualizers=True)
```

El planner lee el ultimo estado del plan y extiende desde ahi.

## Frames Duplicados

```python
ad.move(mode="sipp", remove_duplicate_frames=True)
```

Tratalo como una opcion de desarrollo y potencialmente inestable. Puede acortar planes, pero tambien unir limites de evento utiles para depuracion, breakpoints e inspeccion.
