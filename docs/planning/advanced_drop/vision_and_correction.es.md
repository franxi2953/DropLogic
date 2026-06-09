# Vision Y Correccion

Los helpers de vision son opcionales. Solo funcionan cuando el sistema tiene los modulos necesarios de camara, microscopio y/o XY stage.

Los flujos con Simulator y DMLite pueden usar modos debug y utilidades de correccion logica.

## Verificar Gotas

`verify_droplets()` comprueba si las gotas estan donde el plan espera.

```python
results, frame_files = system.advanced_drop.verify_droplets(
    frame_idx=20,
    droplet_ids=[1, 2],
    save_frames_path="runs/verification_frames",
)
```

Devuelve:

- `results`: diccionario de `droplet_id` a `True` o `False`.
- `frame_files`: rutas de imagen guardadas cuando se pasa `save_frames_path`.

Requisitos:

- modulo XY stage
- modulo de camara o microscopio
- `DropletPositionValidator` inicializado

Usa debug mode para probar recuperacion sin vision hardware:

```python
results, frame_files = ad.verify_droplets(
    frame_idx=10,
    droplet_ids=[1],
    debug=True,
    save_frames_path="runs/debug_verification",
)
```

## Corregir Posicion Logica

Usa `correct_droplet_position()` cuando la gota fisica esta en un electrodo distinto al que cree el planner.

```python
ad.correct_droplet_position(
    droplet_id=1,
    correct_pos=(34, 42),
)
```

Esto anade un frame de correccion, actualiza la trayectoria y actualiza la esquina actual de la gota.

Haz esto en vez de asignar `droplet.origin_corner = ...` desde un script de protocolo.

## Mover Stage Al Centro De La Gota

```python
ok = ad.move_to_droplet_center(
    droplet_id=1,
    wait_before_check=0.5,
    wait_after_check=0.5,
)
```

Calcula el centro de la gota, lo convierte a coordenadas de stage, actualiza `xy_stage.position` y espera a que termine el movimiento.

Devuelve `True` si tiene exito y `False` si falta la gota, hay timeout o falla el comando de stage.

## Detectar Condensados

`detect_condensates()` ejecuta deteccion de gotas y condensados sobre un frame proporcionado o sobre frames capturados por el microscopio.

```python
results, annotated = ad.detect_condensates(
    confidence_threshold=0.25,
    crop_droplet=True,
    crop_padding=50,
    return_annotated=True,
    save_image_path="runs/condensates.png",
)
```

Devuelve:

- `results`: diccionario indexado por coordenadas normalizadas del centro de la gota.
- `annotated`: imagen anotada cuando `return_annotated=True`.

Debug mode crea detecciones mock:

```python
results, annotated = ad.detect_condensates(
    debug=True,
    return_annotated=True,
)
```

## Ajustes De Captura

Cuando `frame=None`, `detect_condensates()` captura frames de fluorescencia y brightfield usando la ruta de camara/microscopio del sistema, y despues intenta restaurar los ajustes previos.

Opciones principales:

- `fluo_exposure`
- `fluo_light`
- `brightfield_exposure`
- `brightfield_light`

Usa frames explicitos si quieres control total:

```python
frame = system.visualizers.streamer.get_raw_frame()
results, annotated = ad.detect_condensates(frame=frame, return_annotated=True)
```
