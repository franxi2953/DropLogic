# Módulo de DMLite: Matriz de Electrodos

El sistema `DMLite` está construido actualmente alrededor de un único módulo hardware real: la matriz de electrodos.

`DMLite` es una plataforma hardware de Acxel. Esta página documenta el adaptador Python alrededor de ese hardware; el hardware en sí no forma parte de este repositorio. Consulta [Acxel](https://www.acxel.com/) para la información del proveedor.

## Papel Dentro del Sistema

Este módulo se encarga de traducir comandos de electrodos a nivel de sistema hacia la implementación concreta de bajo nivel usada por el hardware DMLite de Acxel.

A nivel de sistema, `DMLite` usa el módulo para:

- aplicar actualizaciones de la matriz
- establecer el voltaje de operación
- desactivar electrodos
- enviar patrones de actuación relacionados con gotas

## Capas

La pila de electrodos está dividida intencionalmente en capas:

1. **Capa de sistema**: `droplogic.hardware.DMLite`
2. **Wrapper de módulo**: `droplogic.hardware.modules.electrode_matrix.ElectrodeMatrixModule`
3. **Implementación de versión**: `droplogic.hardware.modules.electrode_matrix.versions.DMLite`

Esta separación es importante porque mantiene limpia la definición del sistema y permite que la implementación hardware subyacente cambie según la plataforma host.

## Backends

El sistema `DMLite` usa un backend Python que selecciona el runtime nativo correspondiente al host actual:

| Host | Archivo de runtime | Caso de uso |
| --- | --- | --- |
| Windows x86_64 | `sdk.dll` | Control nativo de hardware. |
| macOS Apple Silicon | `sdk.dylib` | Control nativo de hardware. |
| Linux x86_64 | `linux-x86_64/sdk.so` | Control nativo de hardware con `libusb`. |
| Raspberry Pi OS 64-bit | `linux-aarch64/sdk.so` | Control nativo de hardware con `libusb`. |
| Raspberry Pi OS 32-bit | `linux-armv7l/sdk.so` | Control nativo de hardware con `libusb`. |

Usa la misma API Python en todas las plataformas soportadas:

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite()
```

El runtime nativo se resuelve desde la carpeta de runtime instalada de DropLogic, `DROPLOGIC_RUNTIME_DIR`, o la carpeta local `vendor_bin/electrode_matrix/dmlite/` en un checkout de desarrollo. Hosts no soportados o archivos de runtime ausentes lanzan un error claro.

En Linux y Raspberry Pi OS, instala `libusb-1.0-0` antes de usar control de hardware. macOS Apple Silicon usa `libusb` de Homebrew salvo que tu paquete de runtime ya lo incluya.

## Por Qué Existe un Wrapper de Módulo

El wrapper no es solo estructura extra. Permite:

- estandarizar la API pública que ven los sistemas
- intercambiar implementaciones más adelante sin reescribir el sistema
- mantener los detalles específicos de versión fuera de la definición de máquina de alto nivel

## Comportamiento Actual

En la configuración actual de DMLite, el módulo expone operaciones como:

- `set_chip(...)`
- `set_voltage(...)`
- `deactivate_all()`
- `set_droplet(...)`
- `set_droplets(...)`
- `send_ascii_command(...)`

Con eso es suficiente para que el sistema controle la superficie de electrodos mientras `AdvancedDrop` se mantiene centrado en la planificación y no en los detalles del protocolo hardware.

## Idea de Diseño

Esta página es un buen ejemplo del patrón de DropLogic:

- el **sistema** define qué es la máquina
- el **módulo** define qué bloque de capacidad está presente
- la **versión** define cómo se implementa esa capacidad en un dispositivo concreto
