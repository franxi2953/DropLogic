# Configuracion

`config.json` es el archivo de estado por defecto que usan los sistemas de DropLogic.

El default publico vive en la raiz del repositorio:

```text
config.json
```

Si instancias un sistema sin pasar una ruta alternativa, el sistema carga `config.json` desde el directorio actual de ejecucion. Si lanzas los ejemplos desde la raiz del repositorio clonado, ese archivo es el default del repositorio:

```python
from droplogic.hardware.DMLite import DMLite

system = DMLite(config_file="config.json")
```

Si tu script corre desde otra carpeta, pasa una ruta explicita. Puedes conservar el default del repositorio y usar una copia especifica de tu maquina:

```python
system = DMLite(config_file="local_config.json")
```

`local_config*.json`, `config.local.json` y `calibration_data.json` estan ignorados por Git para que la calibracion privada de una maquina se quede local.

`DMLite` y `BOXMini` son plataformas hardware de [Acxel](https://www.acxel.com/). Este repositorio contiene adaptadores Python y logica de control compartida alrededor de hardware compatible; el hardware del proveedor y los SDK/DLL no forman parte de la libreria.

## Se Sube Al Repositorio?

Si. El `config.json` base forma parte del repositorio publico porque define el esquema por defecto y sirve como punto de partida.

No pongas secretos, rutas privadas de SDK, DLLs, API keys ni credenciales personales dentro de este archivo. Los DLLs y SDKs de proveedores quedan excluidos del repositorio.

## Que Necesita DMLite

`DMLite` solo necesita el bloque `electrode_matrix`.

Campos obligatorios:

| Campo | Significado | Default |
| --- | --- | --- |
| `electrode_matrix.rows` | Numero de filas de la matriz | `128` |
| `electrode_matrix.columns` | Numero de columnas de la matriz | `128` |
| `electrode_matrix.voltage` | Voltaje de actuacion | `55` |
| `electrode_matrix.version` | Implementacion de bajo nivel | `DMLite` |
| `electrode_matrix.matrix` | Estado runtime de la matriz | `[]` al inicio |

Para el setup actual de DMLite, los defaults del repositorio son adecuados. El sistema reinicia `electrode_matrix.matrix` al arrancar, asi que normalmente no hay que editar ese campo a mano.

En Windows, `electrode_matrix.version: "DMLite"` usa el adaptador nativo basado en DLL. En macOS, `DMLite()` actualmente lanza un error claro porque el control nativo de hardware aun no esta implementado alli.

## Que Necesita El Simulator

`Simulator` usa:

| Campo | Significado |
| --- | --- |
| `electrode_matrix.rows` / `columns` | Tamano de la matriz simulada |
| `electrode_matrix.voltage` | Valor de voltaje simulado |
| `xy_stage.position` | Posicion inicial de la platina mock |

El resto del archivo puede quedarse con valores por defecto para flujos solo de simulacion.

## Que Necesitan Sistemas Tipo BOXMini

Los sistemas de hardware mas grandes usan mas bloques:

| Bloque | Para Que Se Usa | El Usuario Suele Editar |
| --- | --- | --- |
| `temperature` | Modulo serie de temperatura | `Port`, `version` |
| `xy_stage` | Posicion, parametros de movimiento y limites | `safe_limits`, `position`, `motion_params` |
| `camera_settings` | Exposicion/ganancia de camara MVS | `auto_exposure`, `exposure_time`, `gain`, `version` |
| `microscope_settings` | Exposicion/canal/serie del microscopio | `Port`, `current_channel`, `total_channels` |
| `light_settings` | Controladores de luz ring/coaxial | `VID`, `PID`, `upled_serial`, intensidades, `version` |
| `capacitive_feedback` | Seleccion del modulo de feedback | `version` |

Solo rellena estos bloques si el sistema que instancias realmente crea esos modulos.

## Bloque De Calibracion

`calibration` contiene los valores medidos que se usan en runtime para conversion de pixeles de camara, conversion electrodo/platina y compensacion opcional de backlash XY.

Calibracion de pixeles actual:

| Campo | Valor | Significado |
| --- | --- | --- |
| `calibration.pixel_calibration.AM16k.microns_per_pixel` | `0.51413882` | um por pixel |
| `calibration.pixel_calibration.AM16k.pixels_per_micron` | `1.94500000` | pixeles por um |

Mapeo platina/electrodo:

| Campo | Significado |
| --- | --- |
| `calibration.chip_origin` | Coordenada de platina correspondiente al electrodo `(0, 0)` |
| `calibration.electrode_mapping.inter_row` | Delta de platina al avanzar una fila de electrodo |
| `calibration.electrode_mapping.inter_column` | Delta de platina al avanzar una columna de electrodo |
| `calibration.electrode_mapping.offset_x` / `offset_y` | Offsets extra aplicados antes de convertir |
| `calibration.backlash_steps` | Compensacion opcional de backlash XY por direccion |

Mide y actualiza `chip_origin`, `inter_row` e `inter_column` para cada maquina fisica y alineacion de chip.

## Flujo Practico De Edicion

1. Empieza desde el `config.json` del repositorio.
2. Copialo a `local_config.json` para cambios especificos de tu maquina.
3. Actualiza solo los bloques que usa el sistema que vas a instanciar.
4. Ejecuta una prueba sencilla con Simulator o DMLite.
5. Commitea solo cambios de esquema/default, no calibraciones locales privadas.
