# Simulator

`Simulator` es el sistema puramente software por defecto en DropLogic. Es el mejor punto de partida cuando quieres validar protocolos, probar la lógica de planificación o inspeccionar el comportamiento de la matriz sin conectar hardware físico.

## Qué Proporciona

Actualmente el simulador agrupa:

- una matriz de electrodos simulada
- una interfaz simulada de platina XY
- un `MatrixVisualizer`
- la capa de planificación `AdvancedDrop`

Esto lo hace especialmente útil para las primeras fases de desarrollo, sobre todo al iterar sobre routing de gotas o depurar transiciones de estado.

## Por Qué Importa

El simulador conserva la misma estructura de sistema usada por las máquinas reales:

- deriva de `DropSystem`
- enruta comandos mediante el mismo mecanismo basado en colas
- expone componentes del sistema con atributos familiares

Eso significa que muchos protocolos escritos contra el simulador pueden trasladarse a un sistema real con cambios mínimos.

## Casos de Uso Principales

- desarrollo sin hardware conectado
- depuración de planificación y ejecución
- validación visual del movimiento de gotas
- prueba de transiciones de estado y enrutado de comandos

## Alcance Actual

El simulador es intencionalmente ligero. Se centra en las piezas más útiles para desarrollo de algoritmos:

- estado de activación de electrodos
- estado de posición XY
- visualización de matriz

No intenta emular todos los efectos físicos de una máquina real.

## Punto de Entrada Típico

```python
from droplogic.hardware.simulator import Simulator

system = Simulator(log_level="INFO")
```

Desde ahí puedes usar el flujo estándar de `advanced_drop` y el visualizador de matriz igual que en un script apoyado por un sistema real.
