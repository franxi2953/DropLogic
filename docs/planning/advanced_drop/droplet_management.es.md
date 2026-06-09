# Gestion de Gotas

Las gotas se gestionan mediante `system.advanced_drop.droplets`.

Este objeto se comporta como una lista, pero añade helpers para crear, actualizar e inspeccionar objetos `Droplet`.

## `create_droplet()`

Crea una gota logica y añade un frame mostrandola en su origen.

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador grabado por executor mostrando create_droplet anadiendo gotas rectangulares y de forma personalizada](../../assets/advanced-drop/droplet-create.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>create_droplet()</code>: una gota rectangular y una huella personalizada se anaden al plan en sus origenes</figcaption>
</figure>

```python
droplet = system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(40, 40),
    width=2,
    height=2,
    priority=0,
    vital_space=1,
)
```

Usa `width` y `height` para una gota rectangular, o `shape` para una huella personalizada:

```python
shape = {(0, 0), (0, 1), (1, 0)}

system.advanced_drop.droplets.create_droplet(
    droplet_id=2,
    origin=(20, 20),
    target=(30, 25),
    shape=shape,
)
```

Argumentos principales:

- `droplet_id`: identificador entero unico.
- `origin`: posicion actual `(row, col)` de la esquina superior izquierda.
- `target`: posicion objetivo `(row, col)` de la esquina superior izquierda.
- `shape`: conjunto opcional de offsets relativos `(row, col)`.
- `width`, `height`: dimensiones rectangulares si no se pasa `shape`.
- `priority`: orden de ruteo. El planner SIPP actual ordena de menor a mayor; `priority=0` se planifica antes que `priority=1`.
- `vital_space`: halo minimo usado para evitar colisiones.

## Creacion En Lote

Usa `add_droplets()` cuando un protocolo empieza desde una lista de definiciones.

```python
droplet_specs = []
droplet_id = 1

for row in (18, 30, 42):
    for col in (18, 30, 42):
        droplet_specs.append({
            "id": droplet_id,
            "origin": (row, col),
            "target": (row + 24, col + 34),
            "width": 2,
            "height": 2,
            "priority": droplet_id,
            "vital_space": 1,
        })
        droplet_id += 1

system.advanced_drop.droplets.add_droplets(droplet_specs)
```

## Actualizar Objetivos

`update_droplet_target()` es la forma normal de pedir un nuevo movimiento despues de ejecutar un plan anterior.

```python
system.advanced_drop.droplets.update_droplet_target(1, (70, 20))
system.advanced_drop.move(mode="sipp")
```

`move()` solo planifica gotas cuya posicion actual difiere de su objetivo. Si una gota ya esta en destino, actualiza primero su objetivo.

`update_droplet_position()` cambia la posicion logica actual. Para corregir tras un desajuste fisico, prefiere `system.advanced_drop.correct_droplet_position()`, porque tambien anade un frame de correccion al plan.

## Inspeccionar Gotas

```python
droplet = system.advanced_drop.droplets.get_droplet(1)
info = system.advanced_drop.droplets.get_droplet_info(1)
summary = system.advanced_drop.droplets.get_droplets_summary()
```

`get_droplet_info()` devuelve posicion actual, objetivo, forma, prioridad y `vital_space`.

`get_droplets_summary()` devuelve todas las gotas y si `AdvancedDrop` tiene un plan activo.

## Borrar Y Reiniciar

```python
system.advanced_drop.droplets.delete_droplet(1)
system.advanced_drop.clear()
```

`delete_droplet()` elimina el objeto gota. No reescribe automaticamente frames antiguos.

`clear()` reinicia la lista de gotas y el plan actual. Usalo al empezar un nuevo protocolo en la misma sesion Python.

## Enviar Un Frame Manual

`push_frame()` pinta las gotas activas actuales en un nuevo frame del plan y lo etiqueta como evento.

```python
system.advanced_drop.push_frame(
    event_type="manual_hold",
    event_data={"reason": "stabilize before imaging"},
)
```

Es util cuando un protocolo necesita un hold explicito o un punto de sincronizacion entre operaciones.
