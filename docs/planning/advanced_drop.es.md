# AdvancedDrop

`AdvancedDrop` es la capa de alto nivel para manipulacion de gotas conectada a un `DropSystem`.

Los sistemas como `Simulator` y `DMLite` la inicializan y la exponen como:

```python
system.advanced_drop
```

## Responsabilidades

- gestionar gotas mediante `system.advanced_drop.droplets`
- crear y actualizar objetos `DropletPlan`
- planificar movimiento basado en SIPP
- crear planes de division, fusion, mezcla y extraccion
- conectar la salida de planificacion con `PlanExecutor`
- conectarse opcionalmente a validacion por vision cuando el sistema tiene los modulos de camara y platina necesarios

## Donde Vive

- `droplogic/utils/advanced_drop/__init__.py`
- `droplogic/utils/advanced_drop/common.py`
- `droplogic/utils/advanced_drop/move.py`
- `droplogic/utils/advanced_drop/splitting.py`
- `droplogic/utils/advanced_drop/merge.py`
- `droplogic/utils/advanced_drop/mixing.py`
- `droplogic/utils/advanced_drop/feedback.py`

## Limite de Diseno

`AdvancedDrop` no deberia conocer el protocolo de bajo nivel de un dispositivo hardware. Crea y manipula planes de frames de matriz; los sistemas y modulos traducen esos planes a comandos de hardware.
