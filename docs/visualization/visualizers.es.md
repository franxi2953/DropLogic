# Visualizadores

## MatrixVisualizer

`MatrixVisualizer` muestra la matriz de electrodos y el estado de ejecucion. Es util para simulacion, depuracion e inspeccion de planes.

Puede mostrar:

- frame actual de la matriz
- rutas de gotas
- posiciones de breakpoints
- posiciones de electrodos al hacer click
- snapshots para grabacion o diagnostico

## Orientacion de la Matriz

El visualizer recibe coordenadas logicas en el orden estandar de AdvancedDrop:
`(row, col)`. Luego rota la matriz solo para mostrarla en la ventana.

Default:

- `matrix_rotation_degrees=90`
- la matriz se muestra rotada 90 grados clockwise
- el `(0, 0)` logico aparece cerca de la parte superior derecha
- aumentar `row` se ve como movimiento hacia la izquierda
- aumentar `col` se ve como movimiento hacia abajo

Este default existe porque la configuracion tipo Acxel DMLite/BOXMini se
observa fisicamente rotada respecto a la matriz logica tipo NumPy. El codigo de
planificacion sigue usando coordenadas `(row, col)` 0-indexed; el visualizer
solo cambia como se dibuja la matriz.

Puedes cambiar la rotacion de display asi:

```python
system.visualizers.matrix.set_matrix_rotation(0)    # sin rotar
system.visualizers.matrix.set_matrix_rotation(90)   # default
system.visualizers.matrix.set_matrix_rotation(180)
system.visualizers.matrix.set_matrix_rotation(270)
```

Los clicks se convierten de vuelta a coordenadas logicas `(row, col)` antes de
llamar al callback:

```python
def on_click(electrode):
    row, col = electrode
    print(row, col)

system.visualizers.matrix.set_electrode_click_callback(on_click)
```

La rotacion de imagen de fondo es independiente. `bg_rotation_deg` solo rota la
imagen de camara/fondo detras de la matriz; no rota las coordenadas de
AdvancedDrop:

```python
system.visualizers.matrix.bg_rot = 0.0
```

## StreamerVisualizer

`StreamerVisualizer` muestra frames en vivo desde un dispositivo de captura, como una camara o microscopio.

Puede mostrar:

- frames raw y procesados
- overlays de electrodos
- overlays de deteccion de gotas
- overlays de deteccion de condensados
- mapeo de electrodos en el campo de vision

## Comportamiento por Plataforma

Los visualizadores detectan la plataforma mediante el `DropSystem` padre. En macOS, las ventanas OpenCV necesitan correr en el thread principal, asi que el comportamiento de display es mas conservador. En Windows, los visualizadores pueden usar threads de display en background.
