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

## Convencion de Coordenadas

AdvancedDrop usa coordenadas de matriz 0-indexed en tuplas `(row, col)`.
Es el mismo orden que NumPy: `matrix[row, col]`.

No leas estas posiciones como Cartesianas `(x, y)`. Si estas pensando en imagen
o coordenadas de stage, la equivalencia mental mas segura es:

- `row` es el indice vertical de matriz, parecido a `y`.
- `col` es el indice horizontal de matriz, parecido a `x`.
- por tanto, un punto `(x, y)` suele escribirse como `(row, col) = (y, x)`.

En la matriz logica sin rotar, `(0, 0)` es el electrodo superior izquierdo.
Aumentar `row` baja por la matriz. Aumentar `col` mueve hacia la derecha.

Para gotas, `origin_corner` y `target_corner` son la esquina superior izquierda
de la huella de la gota. `shape` se guarda como offsets relativos a esa esquina.

```python
ad.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(30, 40),
    width=2,
    height=2,
)
```

Esto crea una gota `2x2` cuya huella empieza en fila `10`, columna `10`, y cuyo
target es la esquina superior izquierda en fila `30`, columna `40`.

Los helpers de bajo nivel pueden tener reglas propias de indexado. AdvancedDrop,
sus planes, trayectorias, breakpoints y el debugger usan `(row, col)` 0-indexed.

## Orientacion del MatrixVisualizer

El planner usa siempre la convencion logica anterior. El `MatrixVisualizer`
muestra esa matriz rotada por defecto:

- rotacion por defecto: `90` grados clockwise.
- el `(0, 0)` logico aparece cerca de la parte superior derecha del visualizer.
- aumentar `row` se ve como movimiento hacia la izquierda.
- aumentar `col` se ve como movimiento hacia abajo.

Este default coincide con la orientacion usada por la configuracion de matriz
tipo Acxel DMLite/BOXMini que inspiro el visualizer. Es solo una transformacion
visual: no cambia como escribes planes ni como direccionas electrodos en
AdvancedDrop.

Para usar una visualizacion sin rotar, donde `(0, 0)` aparece arriba a la
izquierda:

```python
system.visualizers.matrix.set_matrix_rotation(0)
```

Las rotaciones soportadas son `0`, `90`, `180` y `270` grados clockwise. Los
clicks del visualizer se convierten de vuelta a `(row, col)` antes de llamar al
callback.

`bg_rotation_deg` es independiente: corrige solo la imagen de fondo/camara, no
la matriz logica.

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
