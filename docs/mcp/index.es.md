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
droplogic-mcp --transport stdio
```

Para un cliente remoto o un daemon local de larga duracion, usa transporte HTTP:

```bash
droplogic-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765
```

El servidor arranca en reposo. No instancia simulador, DMLite ni BOXMini hasta que un agente llama `load_system(...)`.

Por defecto, el servidor solo puede cargar el simulador. El hardware real debe habilitarse explicitamente, pero eso tampoco abre hardware al arrancar:

```bash
droplogic-mcp --allow-real-hardware
```

Las escrituras crudas de estado y operaciones crudas de modulos tambien estan deshabilitadas por defecto:

```bash
droplogic-mcp --allow-real-hardware --allow-unsafe-tools
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
| `runtime_status` | Devuelve estado de sistema, colas, executor, plan y gotas apto para polling |
| `health_check` | Comprueba workers de cola, executor, modulos ocupados y ultimo error |
| `restart_system` | Cierra y recarga el sistema actual o solicitado tras un fallo |
| `capabilities` | Lista las funciones disponibles para agentes |
| `read_state` | Lee todo el estado o una ruta como `electrode_matrix.voltage` |
| `emergency_stop` | Para ejecucion, limpia colas y opcionalmente apaga electrodos |

Cuando el servidor arranca, no hay ningun sistema cargado. Usa `load_system(...)` para crear uno, `close_system()` para liberarlo y `restart_system(...)` solo tras un fallo observado. `capabilities()` es util despues de cargar, porque los modulos disponibles dependen del sistema activo. La carga de BOXMini requiere que se inicialicen todos los modulos principales, incluido el XY stage; una carga fallida cierra los recursos parciales y no deja ningun sistema cargado que el caller pueda usar o reiniciar automaticamente.

`runtime_status()` usa `detail="compact"` por defecto y es adecuado para polling frecuente del dashboard, incluso mientras el planner esta ocupado. No inicia el servidor MJPEG. En sistemas con colas, `system.queue_summary.pending_commands` es el numero total de comandos sin finalizar, incluidos los que se estan procesando, y `system.queue_summary.queues` contiene entradas `CRITICAL`, `HIGH`, `MEDIUM` y `LOW` con `pending_commands`, `worker_alive` e `interval_ms`. Usa `detail="full"` para ver tamanos de cola sin resumir, errores del ultimo comando y diagnosticos de guardado de estado.

### Definicion De Gotas

Usa estas tools para definir y editar el conjunto logico de gotas:

| Tool | Uso |
| --- | --- |
| `clear_droplet_state` | Limpia gotas logicas y frames de plan, y opcionalmente reinicia el cursor del executor |
| `create_droplet` | Crea una gota |
| `add_droplets` | Crea varias gotas |
| `delete_droplet` | Elimina una gota de la lista logica |
| `update_droplet_target` | Cambia el objetivo antes de planificar |
| `update_droplet_targets` | Cambia varios objetivos antes de planificar |
| `update_droplet_position` | Corrige la posicion logica actual |
| `droplets_summary` | Inspecciona todas las gotas |

`update_droplet_target` y `update_droplet_targets` validan el layout final de gotas activas antes de mutar objetivos. Si el resultado contiene `target_validation.ok=false`, los objetivos no cambiaron; inspecciona `blocking_issues`, `warnings` y `suggested_targets` antes de llamar `plan_move`. Usa `clear_droplet_state(reset_executor=true)` al empezar un protocolo logico limpio en un runtime ya cargado; reinicia estado AdvancedDrop, no electrodos fisicos, asi que llama primero `emergency_stop(deactivate_electrodes=true)` si el hardware debe apagarse.

### Primitivas De Planificacion

Usa estas tools para anadir una primitiva logica al plan actual. No ejecutan hardware. El agente debe planificar, inspeccionar `plan_summary`, y despues ejecutar deliberadamente con `PlanExecutor`.

| Tool | Uso |
| --- | --- |
| `plan_activation_frame` | Anade un frame de activacion para las gotas actuales |
| `plan_move` | Planifica movimiento de gotas cuyo target difiere de su posicion actual |
| `plan_reservoir_extraction` | Planifica extraccion de gotas desde un reservorio |
| `plan_isometric_split` | Planifica un split isometrico |
| `plan_mix` | Planifica una secuencia de mezcla |
| `plan_merge` | Planifica merge de gotas |
| `planning_job_status` | Consulta un job de planificacion y la espera recomendada |
| `cancel_planning_job` | Solicita cancelar un job de planificacion |
| `plan_summary` | Inspecciona frames, eventos, trayectorias y resultado |
| `save_protocol` | Guarda plan y gotas en un pickle |

Para movimientos grandes o planes dificiles, usa `background=true` y consulta `planning_job_status()` en vez de mantener una llamada MCP abierta. Mientras el job sigue ejecutandose, la respuesta incluye `recommended_wait_seconds`, `next_check_after_seconds` y `recommended_status_call`; espera ese intervalo antes de consultar de nuevo en vez de hacer polling repetido.

En hardware real como DMLite y BOXMini, `plan_move` rechaza mas de 10 gotas activas moviendose en una sola llamada. Divide el movimiento en lotes ejecutados de 5-10 gotas, prefiriendo 5 para layouts densos, cruces, rutas largas o gotas 2 x 2.

`plan_merge` valida previamente el hub de fusion mediante la API core de AdvancedDrop. Los hubs inseguros devuelven `ok=false` con `primitive_validation.merge_target_validation`, y pueden incluir `blocker_parking_suggestions`, `suggested_target` o `recommended_action` para apartar bloqueadores o reintentar en un hub cercano.

Ejemplo de planificacion de movimiento:

```json
{
  "mode": "sipp",
  "remove_duplicate_frames": false,
  "planning_timeout": 1200,
  "background": true
}
```

Las tools genericas `advanced_drop_call` y `list_advanced_drop_methods` son superficies de depuracion y solo se registran si el servidor arranca con `--allow-unsafe-tools`.

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
| `start_execute_until_breakpoint` | Inicia una espera en background hasta breakpoint o fin del plan |
| `execution_wait_status` | Consulta la espera activa o ultima |
| `cancel_execution_wait` | Cancela solo la espera, no la ejecucion fisica |

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

### Estado Y Escena

Usa estas tools cuando un agente o una app externa necesita estado estructurado en vez de una imagen:

| Tool | Uso |
| --- | --- |
| `state_summary` | Lee estado resumido sin expandir arrays grandes |
| `read_state` | Lee una ruta pequena exacta |
| `matrix_summary` | Devuelve rangos activos compactos de matriz; los ceros son implicitos |
| `execution_scene` | Devuelve estado compacto de plan/executor/matriz/gotas |

`execution_scene` combina lo que normalmente necesita un dashboard: cursor del executor, ultimo frame aplicado, resumen del frame de plan, rangos activos de matriz, evento actual, posiciones de gotas, targets, bounding boxes y paths acotados. Usa la misma codificacion compacta de matriz que `matrix_summary`, asi que es segura para uso MCP normal. Por defecto no devuelve cada celda de cada gota; pide `include_droplet_cells=true` solo si el cliente necesita esas celdas y puede asumir mas contexto.

Usa `matrix_summary` si la pregunta es solo sobre la matriz de electrodos. Usa `execution_scene` si la pregunta relaciona matriz, plan, frame del executor, eventos y gotas. Usa `visualizer_frame` solo cuando el agente necesita pixeles.

Las lecturas crudas de matriz 128 x 128 estan protegidas porque el transporte MCP puede duplicar datos en texto y payload estructurado. `read_large_state` solo se registra si el servidor arranca con `--allow-large-state-tools`; usalo solo para depuracion supervisada.

### Visualizadores Y Frames

| Tool | Uso |
| --- | --- |
| `visualizer_status` | Inspecciona visualizadores e inicia el endpoint MJPEG auxiliar |
| `visualizer_frame` | Devuelve un frame como base64 y/o lo guarda a disco |
| `start_visualizer` | Abre una ventana si el OS lo permite |
| `stop_visualizer` | Cierra una ventana |
| `bring_visualizer_to_front` | Trae una ventana al frente si el OS lo permite |

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

Los agentes pueden consultar `visualizer_frame` para obtener frames actuales. Los clientes de navegador pueden llamar `visualizer_status()` para asegurar que el endpoint direct-MJPEG auxiliar este activo y obtener sus URLs de matriz y streamer; el polling normal de `runtime_status()` no inicia ese endpoint. Los comandos de hardware permanecen dentro de MCP.

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

### Temperatura

| Tool | Uso |
| --- | --- |
| `temperature_hold` | Fija una temperatura, espera/mantiene y devuelve muestras compactas |
| `start_temperature_routine` | Ejecuta una secuencia de holds de temperatura en background |
| `temperature_routine_status` | Inspecciona la rutina de temperatura activa o ultima |
| `cancel_temperature_routine` | Cancela la rutina de temperatura activa |
| `start_melting_curve_capture` | Mantiene cada paso de temperatura y captura imagenes tras cada paso |
| `melting_curve_capture_status` | Inspecciona la captura de curva activa o ultima |
| `cancel_melting_curve_capture` | Cancela la captura de curva activa |

Los holds y rutinas de temperatura usan `tolerance_c=0.2` por defecto. El runtime espera a que la cola de hardware se estabilice, confirma que el objetivo no haya revertido, y falla el paso si otro objetivo lo reemplaza durante la espera o el hold.

### Modulos

| Tool | Uso |
| --- | --- |
| `list_system_modules` | Lista modulos cargados y metodos permitidos |
| `module_busy_status` | Comprueba si un modulo, o todos, parecen ocupados |
| `module_call` | Llamada de debug/fallback a un metodo permitido de modulo |

Los workflows normales deben preferir las tools dedicadas de stage, luz, imaging, temperatura, planificacion, ejecucion y estado. `module_call` queda disponible para lecturas u operaciones supervisadas de bajo nivel que aun no tengan tool dedicada.

Metodos crudos de matriz como `set_chip` se consideran inseguros y requieren `--allow-unsafe-tools`. `system_call`, `set_system_state` y las tools genericas de AdvancedDrop tambien son de depuracion y solo se registran con `--allow-unsafe-tools`. La ruta privada de comandos del proveedor, incluido `send_ascii_command`, no se expone.

## Modulos Ocupados Y Recuperacion

Los modulos de hardware pueden estar temporalmente ocupados aunque el servidor MCP este sano. Por ejemplo, la matriz de electrodos esta ocupada mientras `PlanExecutor` ejecuta frames, y el XY stage esta ocupado mientras el movimiento no haya terminado.

Los agentes deberian usar este patron antes de llamadas directas a modulos:

```text
1. module_busy_status(module="electrode_matrix")
2. Si hace falta una llamada de modulo, module_call(..., wait_if_busy=true, timeout_seconds=30)
```

`module_call` acepta `wait_if_busy`, `timeout_seconds` y `poll_interval`:

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
4. plan_move(mode="sipp")
5. visualizer_frame(visualizer="matrix", frame_source="snapshot")
6. start_plan(frame_delay=0.5, verify_positions=false)
7. executor_status()
8. save_protocol(output_path="runs/example.pkl")
9. close_system()
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
| `--allow-real-hardware` | Permite cargar DMLite o BOXMini |
| `--allow-unsafe-tools` | Permite escrituras crudas y tools crudas |
| `--snapshots-dir` | Directorio para snapshots |
