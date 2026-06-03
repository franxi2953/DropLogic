# Sistemas y Módulos

DropLogic está organizado alrededor de una idea simple: un **sistema** se construye componiendo un conjunto de **módulos** reutilizables.

Esta estructura hace que la librería sea flexible. La misma capa de planificación y control puede reutilizarse tanto en entornos simulados como en hardware real, mientras cada sistema conecta solo los módulos que realmente necesita.

## Conceptos Principales

### Sistema

Un **sistema** es la definición de máquina de nivel superior que usa el usuario.

Ejemplos:

- `Simulator`: un entorno puramente software para desarrollo y pruebas.
- `DMLite`: un sistema real centrado en la matriz de electrodos. La plataforma hardware es de [Acxel](https://www.acxel.com/); DropLogic proporciona la capa de integración.

Un sistema normalmente ofrece:

- una interfaz basada en `DropSystem`
- enrutado de estado y comandos
- el conjunto de módulos disponibles en esa máquina
- visualizadores, cuando aplica
- planificación y ejecución con `AdvancedDrop`

### Módulo

Un **módulo** es un bloque de capacidad dentro de un sistema.

Ejemplos:

- matriz de electrodos
- cámara
- microscopio
- platina XY
- control de temperatura
- iluminación

Los módulos son los que dan a cada sistema sus capacidades físicas o simuladas. Un sistema puede entenderse como un conjunto curado de módulos.

### Versión

Una **versión** es la implementación concreta detrás de un módulo.

Ejemplos:

- `CameraV1`
- `DMLite`
- `TemperatureV1`

Esto permite que DropLogic mantenga una API de alto nivel estable mientras intercambia el driver o la implementación específica del dispositivo.

El nombre `DMLite` aparece en dos capas a propósito:

- como **sistema**, `droplogic.hardware.DMLite`, que es la máquina de alto nivel que instancia el usuario
- como **versión de módulo**, `droplogic.hardware.modules.electrode_matrix.versions.DMLite`, que es la implementación específica para la matriz de electrodos de Acxel usada dentro de ese sistema

Por tanto, el sistema `DMLite` actual es simplemente un sistema real compuesto por un módulo hardware principal: el adaptador de matriz de electrodos `DMLite` de Acxel.

## Cómo se Construyen los Sistemas

En la práctica, un sistema de DropLogic es una mezcla de:

1. la clase base compartida `DropSystem`
2. uno o varios módulos de hardware o simulados
3. visualizadores opcionales
4. la capa de planificación `AdvancedDrop`

Esto significa que dos sistemas pueden compartir gran parte de su comportamiento y diferir solo en los módulos que exponen y en las versiones que instancian.

## Sistemas Reales vs Simulados

DropLogic soporta ambos:

- **sistemas simulados**, útiles para planificación, depuración y desarrollo sin hardware
- **sistemas reales**, que conectan esas mismas ideas con dispositivos físicos

Para los sistemas reales, la documentación incluye una subsección de **Módulos** para dejar explícita su composición hardware.

## Sistemas Actuales

### Simulator

`Simulator` es el entorno más sencillo para empezar. Está pensado para desarrollo, validación de algoritmos y depuración visual.

### DMLite

`DMLite` es un sistema real mínimo centrado en una matriz de electrodos de Acxel. Expone una superficie hardware más pequeña que otras máquinas porque actualmente consta de un módulo hardware principal, pero mantiene la misma arquitectura de DropLogic.

## Extender la Librería

Una vez que entiendes sistemas y módulos, crear una nueva máquina en DropLogic consiste principalmente en recombinar módulos existentes y añadir nuevos cuando haga falta.

Consulta **Creating New Systems** al final de esta sección para ver la guía de implementación.
