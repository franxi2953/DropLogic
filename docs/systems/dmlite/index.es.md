# DMLite

`DMLite` es un sistema real mínimo dentro de esta librería centrado en una matriz de electrodos física de [Acxel](https://www.acxel.com/). El hardware lo proporciona Acxel; este repositorio contiene el sistema Python y el adaptador de módulo usado para controlarlo.

El nombre `DMLite` se usa tanto para el sistema de alto nivel de DropLogic como para la versión del módulo de matriz de electrodos dentro de ese sistema. En esta sección, **el sistema** significa `droplogic.hardware.DMLite`; **la versión de módulo** significa `droplogic.hardware.modules.electrode_matrix.versions.DMLite`.

Comparado con máquinas más grandes, mantiene una superficie hardware intencionalmente pequeña. Eso lo convierte en un sistema de referencia útil para entender cómo se puede montar una máquina real a partir de módulos de esta librería.

## Qué Incluye

El sistema `DMLite` actual incluye:

- el `ElectrodeMatrixModule`
- un `MatrixVisualizer`
- la capa de planificación `AdvancedDrop`

Actualmente **no** incluye módulos de cámara, microscopio, temperatura o iluminación.

## Por Qué Es Importante

`DMLite` muestra el patrón central de un sistema real:

- heredar de `DropSystem`
- cargar el estado de la máquina desde configuración
- instanciar los módulos hardware necesarios
- enrutar actualizaciones de estado de alto nivel hacia comandos de módulo
- mantener la capa de planificación independiente de los detalles del driver hardware

En otras palabras, es un ejemplo pequeño pero real de la arquitectura de sistemas de DropLogic.

## Enfoque Hardware

Este sistema está enfocado en la actuación de electrodos:

- establecer el estado de la matriz
- actualizar el voltaje de operación
- pasar los cambios de la matriz a la implementación de bajo nivel

La implementación concreta del hardware queda detrás de la capa de módulo, de modo que el sistema sigue siendo legible y reemplazable.

## Punto de Entrada Típico

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

## Módulos

Como `DMLite` es un sistema real respaldado por hardware, su composición modular se documenta explícitamente en las páginas anidadas dentro de esta sección. Por ahora esa composición es intencionalmente simple: el sistema consta del módulo de matriz de electrodos `DMLite` de Acxel más las capas compartidas de planificación y visualización de DropLogic.
