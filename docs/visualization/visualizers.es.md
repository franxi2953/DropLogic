# Visualizadores

## MatrixVisualizer

`MatrixVisualizer` muestra la matriz de electrodos y el estado de ejecucion. Es util para simulacion, depuracion e inspeccion de planes.

Puede mostrar:

- frame actual de la matriz
- rutas de gotas
- posiciones de breakpoints
- posiciones de electrodos al hacer click
- snapshots para grabacion o diagnostico

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
