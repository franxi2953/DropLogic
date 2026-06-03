# Planificacion

La planificacion es la capa que convierte la intencion de movimiento de gotas en frames ejecutables para la matriz.

En DropLogic, esta capa vive principalmente en `AdvancedDrop`: guarda las gotas, construye planes, comprueba restricciones y entrega frames al executor.

## Piezas Principales

- **AdvancedDrop**: API de planificacion expuesta en cada sistema como `system.advanced_drop`
- **Estado de gotas**: gotas, posiciones, objetivos, formas, eventos y metadatos de frames
- **Planificacion de movimiento**: rutas SIPP para movimiento multi-gota con evitacion de colisiones
- **Operaciones**: movimiento, division, fusion, mezcla y extraccion desde reservorios
- **PlanExecutor**: ejecucion en runtime de los frames planificados sobre un sistema

## Flujo Tipico

```python
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2,
    height=2,
)

system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

El planner deberia mantenerse independiente del hardware. El comportamiento especifico de hardware pertenece a sistemas y modulos; la planificacion debe razonar sobre frames, gotas, restricciones y tiempos de ejecucion.
