# Servidor MCP

El servidor MCP de DropLogic permite que agentes de IA controlen la libreria mediante el Model Context Protocol, manteniendo la propiedad del hardware dentro de un unico proceso local de Python.

Usalo cuando quieras que un agente inspeccione el sistema, cree o modifique planes de gotas, ejecute protocolos, pause en breakpoints, lea frames de visualizadores, o lance comprobaciones de vision como verificacion de gotas y deteccion de condensados.

## Por Que Existe

Un script normal de DropLogic usa Python directamente:

```python
from droplogic.hardware.simulator import Simulator

system = Simulator()
system.advanced_drop.droplets.create_droplet(1, (5, 5), (20, 20))
system.advanced_drop.move()
system.advanced_drop.executor.start()
```

El servidor MCP envuelve la misma libreria en tools que puede llamar un agente. La frontera importante es que el agente habla con el servidor, y el servidor posee el unico `DropSystem` vivo.

Esto evita que varios notebooks, agentes o scripts compitan por las mismas colas de hardware, el lock de estado, los visualizadores o el `PlanExecutor`.

## Instalacion

El soporte MCP es opcional para que la libreria base no instale dependencias de servidor/agente por defecto.

Desde la raiz del repositorio:

```bash
pip install -e ".[agent]"
```

Ese extra instala el paquete `mcp` y habilita el comando `droplogic-mcp`.

## Lanzar El Servidor

Para un cliente MCP local de escritorio, usa `stdio`:

```bash
droplogic-mcp --transport stdio --load-system simulator
```

Para un cliente remoto o un daemon local de larga duracion, usa transporte HTTP:

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --load-system simulator
```

Por defecto, el servidor solo puede cargar el simulador. El hardware real debe habilitarse explicitamente:

```bash
droplogic-mcp --allow-real-hardware --load-system dmlite
```

Las escrituras crudas de estado y operaciones crudas de modulos tambien estan deshabilitadas por defecto:

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools --load-system boxmini
```

Usa `--allow-unsafe-tools` solo para depuracion supervisada.

## Arquitectura

La capa MCP es deliberadamente fina:

| Capa | Papel |
| --- | --- |
| `droplogic.mcp.server` | Transporte MCP, tools, recursos y CLI |
| `droplogic.mcp.runtime` | Posee un `DropSystem`, aplica seguridad y serializa salidas |
| `DropSystem` | Simulator, DMLite, BOXMini u otro sistema |
| `AdvancedDrop` | Crea gotas y construye planes |
| `PlanExecutor` | Ejecuta planes, breakpoints, guardado y grabacion |
| Visualizadores | Entregan frames de matriz o streamer al agente |

Normalmente el agente deberia controlar experimentos mediante `AdvancedDrop` y `PlanExecutor`, no escribiendo matrices arbitrarias.

## Grupos De Tools

El servidor expone varios grupos de tools.

### Runtime

| Tool | Uso |
| --- | --- |
| `load_system` | Carga `simulator`, `dmlite` o `boxmini` |
| `close_system` | Cierra el sistema actual |
| `runtime_status` | Devuelve estado de sistema, executor, plan y gotas |
| `health_check` | Comprueba workers de cola, executor, modulos ocupados y ultimo error |
| `restart_system` | Cierra y recarga el sistema actual o solicitado tras un fallo |
| `capabilities` | Lista las funciones disponibles para agentes |
| `read_state` | Lee todo el estado o una ruta como `electrode_matrix.voltage` |
| `emergency_stop` | Para ejecucion, limpia colas y opcionalmente apaga electrodos |

`capabilities()` deberia ser la primera llamada de un agente, porque los modulos disponibles dependen del sistema cargado.

### Gotas Y Planificacion

| Tool | Uso |
| --- | --- |
| `create_droplet` | Crea una gota |
| `add_droplets` | Crea varias gotas |
| `delete_droplet` | Elimina una gota de la lista logica |
| `update_droplet_target` | Cambia el objetivo antes de planificar |
| `update_droplet_position` | Corrige la posicion logica actual |
| `droplets_summary` | Inspecciona todas las gotas |
| `list_advanced_drop_methods` | Muestra metodos `AdvancedDrop` expuestos |
| `advanced_drop_call` | Llama un metodo `AdvancedDrop` permitido |
| `plan_summary` | Inspecciona frames, eventos, trayectorias y resultado |
| `save_protocol` | Guarda plan y gotas en un pickle |

`advanced_drop_call` expone metodos publicos como `move`, `reservoir_extraction`, `isometric_split`, `mix`, `merge`, `verify_droplets`, `detect_condensates`, `correct_droplet_position`, `clear` y `push_frame`.

Ejemplo:

```json
{
  "method": "move",
  "arguments": {
    "mode": "sipp",
    "remove_duplicate_frames": false
  }
}
```

### Ejecucion

| Tool | Uso |
| --- | --- |
| `start_plan` | Empieza a ejecutar el plan actual |
| `pause_plan` | Pausa la ejecucion |
| `resume_plan` | Reanuda la ejecucion |
| `stop_plan` | Para la ejecucion |
| `executor_status` | Inspecciona frame actual, progreso y breakpoints |
| `add_breakpoint` | Pausa al llegar a un frame |
| `remove_breakpoint` | Elimina un breakpoint |
| `clear_breakpoints` | Elimina todos los breakpoints |
| `execute_until_breakpoint` | Bloquea hasta breakpoint o fin del plan |

Ejemplo:

```json
{
  "frame_delay": 0.5,
  "verify_positions": false,
  "enable_visualizers": false,
  "record_matrix": true,
  "matrix_filename": "runs/matrix.mp4"
}
```

La grabacion sigue perteneciendo a `PlanExecutor`, asi que los videos quedan sincronizados con los frames ejecutados.

### Visualizadores Y Frames

| Tool | Uso |
| --- | --- |
| `visualizer_status` | Inspecciona disponibilidad de matriz y streamer |
| `visualizer_frame` | Devuelve un frame como base64 y/o lo guarda a disco |
| `visualizer_snapshot` | Guarda un snapshot |
| `visualizer_call` | Llama un metodo permitido de visualizador |
| `start_visualizer` | Abre una ventana si el OS lo permite |
| `stop_visualizer` | Cierra una ventana |

Para ver la matriz:

```json
{
  "visualizer": "matrix",
  "frame_source": "snapshot",
  "max_width": 640,
  "include_base64": true
}
```

Para ver camara o microscopio:

```json
{
  "visualizer": "streamer",
  "frame_source": "processed",
  "max_width": 640,
  "include_base64": true
}
```

`StreamerVisualizer` puede ofrecer `raw`, `processed` y `snapshot` segun haya frames vivos. El simulador solo tiene visualizador de matriz.

El servidor MCP no es un servidor de video. Los agentes pueden consultar `visualizer_frame` repetidamente. Si mas adelante necesitamos streaming continuo a alto FPS, deberia ser un endpoint auxiliar, manteniendo los comandos dentro de MCP.

### Vision

| Tool | Uso |
| --- | --- |
| `verify_droplets` | Comprueba posiciones de gotas en un frame del plan |
| `detect_condensates` | Ejecuta deteccion de condensados desde el setup de imagen |

Modo debug sin imagen real:

```json
{
  "frame_idx": 10,
  "droplet_ids": [1, 2],
  "debug": true
}
```

Para workflows reales de vision, el sistema cargado debe tener camara, microscopio, stage y modelos disponibles.

### Modulos

| Tool | Uso |
| --- | --- |
| `list_system_modules` | Lista modulos cargados y metodos permitidos |
| `module_call` | Llama un metodo permitido de modulo |
| `module_busy_status` | Comprueba si un modulo, o todos, parecen ocupados |
| `wait_for_module_free` | Espera a que un modulo quede libre, o devuelve timeout |
| `system_call` | Llama un metodo permitido del sistema cargado |

Las superficies expuestas incluyen luces, exposicion de camara, canal de microscopio, temperaturas, posicion de XY stage y feedback capacitivo.

Metodos crudos de matriz como `set_chip` se consideran inseguros y requieren `--allow-unsafe-tools`. La ruta privada de comandos del proveedor, incluido `send_ascii_command`, no se expone.

## Modulos Ocupados Y Recuperacion

Los modulos de hardware pueden estar temporalmente ocupados aunque el servidor MCP este sano. Por ejemplo, la matriz de electrodos esta ocupada mientras `PlanExecutor` ejecuta frames, y el XY stage esta ocupado mientras el movimiento no haya terminado.

Los agentes deberian usar este patron antes de llamadas directas a modulos:

```text
1. module_busy_status(module="electrode_matrix")
2. Si esta ocupado, wait_for_module_free(module="electrode_matrix", timeout_seconds=30)
3. module_call(module="electrode_matrix", method="deactivate_all")
```

`module_call` y `system_call` tambien aceptan `wait_if_busy`, `timeout_seconds` y `poll_interval`:

```json
{
  "module": "xy_stage",
  "method": "get_position",
  "arguments": {"axis": "X"},
  "wait_if_busy": true,
  "timeout_seconds": 10
}
```

Si un modulo esta ocupado y el agente no ha pedido esperar, la tool devuelve una respuesta estructurada de busy en vez de pisar al executor:

```json
{
  "ok": false,
  "busy": true,
  "module": "electrode_matrix",
  "status": {
    "busy": true,
    "reasons": ["PlanExecutor is actively executing frames"]
  }
}
```

Los errores de tools no deberian matar el servidor MCP. Los errores de llamadas runtime se guardan en `last_error`, y `health_check()` informa de si los workers de cola siguen vivos. Si el sistema queda unhealthy, llama a `restart_system()` en vez de depender de recuperacion automatica. El reinicio automatico no se hace a proposito porque reinicializar hardware real sin supervision puede tener consecuencias fisicas.

## Workflow De Ejemplo

Un flujo sencillo con simulador:

```text
1. load_system(system="simulator")
2. capabilities()
3. create_droplet(droplet_id=1, origin=[5, 5], target=[20, 20])
4. advanced_drop_call(method="move", arguments={"mode": "sipp"})
5. visualizer_frame(visualizer="matrix", frame_source="snapshot")
6. start_plan(frame_delay=0.5, verify_positions=false)
7. executor_status()
8. save_protocol(output_path="runs/example.pkl")
```

Para hardware real, manten el mismo flujo, pero arranca el servidor con `--allow-real-hardware` y usa el sistema adecuado.

## Seguridad

El servidor tiene tres restricciones intencionadas:

| Restriccion | Motivo |
| --- | --- |
| Hardware real deshabilitado por defecto | Evita actuacion accidental por un agente |
| Escrituras crudas deshabilitadas por defecto | Mantiene workflows normales en APIs publicas |
| Comandos privados del proveedor no expuestos | Mantiene la libreria en la frontera de API documentada |

`emergency_stop()` esta disponible cuando hay un sistema cargado. Para el executor, limpia comandos en cola y puede desactivar la matriz.

## Referencia CLI

```bash
droplogic-mcp --help
```

Flags importantes:

| Flag | Significado |
| --- | --- |
| `--transport stdio` | Cliente MCP local por stdin/stdout |
| `--transport streamable-http` | Servidor MCP HTTP |
| `--host` / `--port` | Direccion HTTP |
| `--config` | Ruta a `config.json` |
| `--load-system` | Sistema inicial opcional |
| `--allow-real-hardware` | Permite cargar DMLite o BOXMini |
| `--allow-unsafe-tools` | Permite escrituras crudas y tools crudas |
| `--snapshots-dir` | Directorio para snapshots |
