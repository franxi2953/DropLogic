# Depuracion y Diagnosticos

Las herramientas de depuracion ayudan a inspeccionar planes, fallos de runtime y problemas de instalacion local.

## Piezas Principales

- `plan_debugger.py`: explorador visual de frames para planes guardados
- `doctor.py`: comprobaciones de archivos nativos requeridos en runtime
- `logging_config.py`: configuracion compartida de logger y helpers de nivel de log
- reportes de timeout del executor: logs de diagnostico escritos cuando la ejecucion hasta breakpoint se queda bloqueada

## Donde Vive

- `droplogic/utils/debug/plan_debugger.py`
- `droplogic/utils/doctor.py`
- `droplogic/utils/logging_config.py`
- `droplogic/utils/advanced_drop/plan_executor.py`

Los artefactos de depuracion mas utiles suelen ser planes guardados, diagnosticos del executor, y capturas o grabaciones desde la salida sincronizada de los visualizadores.
