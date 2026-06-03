# Utilidades de Hardware

Las utilidades de hardware proporcionan conversiones comunes y helpers de configuracion usados por sistemas reales.

## Responsabilidades Principales

- cargar y guardar `config.json`
- convertir coordenadas de electrodo a coordenadas de platina
- convertir coordenadas de platina de vuelta a coordenadas de electrodo
- convertir pixeles, micras y volumenes estimados
- exponer metadatos de calibracion para modelos de camara

## Donde Vive

- `droplogic/utils/hardware_utils/utils.py`

Estos helpers deberian mantenerse pequenos y deterministas. La logica especifica de sistema pertenece a sistemas y modulos; estas utilidades deberian seguir siendo reutilizables entre integraciones hardware.

## Calibracion de Pixeles

La calibracion por defecto actual esta definida para `AM16k`.

- `microns_per_pixel`: `0.51413882` um/px
- `pixels_per_micron`: `1.94500000` px/um

Estos valores estan reflejados en los defaults de la libreria y en el bloque de calibracion del `config.json` base.
