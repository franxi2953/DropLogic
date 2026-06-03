# Grabacion

La grabacion esta separada intencionalmente del codigo de display de los visualizadores.

`SegmentedVideoWriter` escribe frames bajo demanda, rota segmentos de salida y mantiene un manifiesto `ffconcat` que permite unir los segmentos mas adelante.

## Por Que Existe

Los experimentos largos pueden crear videos grandes. La segmentacion hace la grabacion mas segura porque:

- limita el tamano de cada segmento de video
- conserva un manifiesto vivo de las partes grabadas
- permite al executor cambiar FPS limpiamente cuando cambia `frame_delay`
- evita duplicar logica de grabacion dentro de los visualizadores

## Grabacion Sincronizada con Ejecucion

La grabacion sincronizada con ejecucion la coordina `PlanExecutor`, no los visualizadores por su cuenta. Asi los frames de video quedan alineados con los frames del plan.

Los snapshots de visualizadores siguen siendo utiles para captura manual y diagnostico, pero la grabacion continua sincronizada debe estar dirigida por el executor.
