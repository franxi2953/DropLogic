# Calibracion

La calibracion conecta coordenadas fisicas, pixeles de camara y posiciones de electrodos.

DropLogic mantiene la calibracion separada de los sistemas para que el mismo sistema pueda ajustarse a distintas maquinas, chips, camaras y configuraciones opticas.

## Piezas Principales

- `CalibrationManager`: guarda y recupera datos de calibracion
- `XYCalibration`: mapea el espacio de platina XY con referencias de electrodos e imagen
- funciones de conversion en utilidades de hardware

## Donde Vive

- `droplogic/calibration/calibration_manager.py`
- `droplogic/calibration/xy_calibration.py`
- `droplogic/utils/hardware_utils/utils.py`

Los datos de calibracion deben tratarse como estado especifico de despliegue. La libreria proporciona estructura y rutinas de conversion, pero los valores medidos pertenecen a la maquina instalada.
