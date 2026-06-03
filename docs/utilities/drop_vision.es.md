# Vision de Gotas

Drop vision contiene helpers de analisis de imagen para deteccion de gotas y condensados.

## Piezas Principales

- `DropletDetector`: deteccion de gotas basada en YOLO
- `CondensateDetector`: deteccion de condensados y post-procesado
- `imaging_capture`: helpers para capturar frames de camara o microscopio desde un sistema
- `time_series_analysis`: utilidades para procesar secuencias de imagen en el tiempo

## Donde Vive

- `droplogic/utils/drop_vision/droplet_detector.py`
- `droplogic/utils/drop_vision/condensate_detector.py`
- `droplogic/utils/drop_vision/imaging_capture.py`
- `droplogic/utils/drop_vision/time_series_analysis.py`

Las utilidades de vision son opcionales. Los flujos solo con simulador no las necesitan, y los sistemas reales solo las usan cuando hay modulos de camara o microscopio disponibles.
