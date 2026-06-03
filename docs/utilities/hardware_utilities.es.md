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

La calibracion por defecto actual esta definida para `AM16k` en el `config.json` base. Si ese bloque no esta disponible, las utilidades usan los mismos defaults internos como fallback.

- `microns_per_pixel`: `0.51413882` um/px
- `pixels_per_micron`: `1.94500000` px/um

Usa `config_path` cuando quieras que los helpers lean una copia especifica de una maquina:

```python
diameter_um = pixels_to_microns(120, camera_model="AM16k", config_path="local_config.json")
volume_nl = pixels_to_volume_nl(3500, height_microns=50, config_path="local_config.json")
```
