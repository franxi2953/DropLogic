# Visualizacion

La visualizacion da feedback durante la planificacion, ejecucion y depuracion de protocolos con gotas.

DropLogic tiene actualmente dos familias principales de visualizadores:

- **MatrixVisualizer**: muestra la matriz de electrodos, rutas planificadas, breakpoints y el estado del frame actual
- **StreamerVisualizer**: muestra frames en vivo de camara o microscopio, opcionalmente con overlays

La grabacion se maneja aparte para que el video sincronizado con ejecucion pertenezca a `PlanExecutor`.

## Donde Vive

- `droplogic/utils/visualizer/visualizer.py`
- `droplogic/utils/recording.py`
- `droplogic/visualization/visual_frame_explorer.py`
- `droplogic/utils/debug/plan_debugger.py`
