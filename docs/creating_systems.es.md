# Creación de Sistemas de Hardware

Esta guía proporciona un punto de partida completo para implementar nuevos sistemas de hardware en **DropLogic**. Captura todas las buenas prácticas y patrones establecidos en implementaciones existentes como `BOXMini`, `Simulator` y `DMLite`.

## Inicio Rápido

1. **Copia la plantilla**:
   ```bash
   cp droplogic/hardware/template/hardware_template.py droplogic/hardware/my_hardware.py
   ```

2. **Renombra la clase**:
   ```python
   class MyHardware(HardwareTemplate):  # Heredar de DropLogic
   ```

3. **Personaliza el código para tu hardware** (ver las siguientes secciones).

4. **Prueba tu implementación**:
   ```python
   hardware = MyHardware()
   hardware.visualizers.matrix.start()  # Probar visualización de la matriz
   ```

## Estructura de la Plantilla

### Componentes Principales

- **Clase Base DropSystem**: Procesamiento de comandos basado en colas, administración del estado y registro (logging).
- **Módulos de Hardware (Modules)**: Cámara, microscopio, platina XY (XY stage), matriz de electrodos, control de temperatura, etc.
- **Visualizadores**: Configuración automática de `MatrixVisualizer` y `StreamerVisualizer`.
- **AdvancedDrop**: Rutinas avanzadas integradas para la planificación SIPP y la ejecución (se inicializa automáticamente).

## Guía de Implementación

### 1. Configuración Básica

```python
from ..base import DropSystem

class MyHardware(DropSystem):
    def __init__(self, config_file="config.json", log_level="INFO"):
        # Llamar al constructor padre
        super().__init__(config_file=config_file)
        
        # Añade aquí la inicialización de módulos personalizados
        # self.my_custom_module = MyCustomModule(self)
        
        # Inicializar las rutinas avanzadas de movimiento
        from ..utils.advanced_drop import AdvancedDrop
        self.advanced_drop = AdvancedDrop(self)
```

### 2. Inicialización de los Módulos de Hardware

Inyecta los módulos que necesite tu sistema según tus configuraciones:

```python
from .modules.camera import CameraModule
from .modules.xy_stage import XYStageModule
from .modules.electrode_matrix import ElectrodeMatrixModule

# Inicializar los módulos que requiere tu sistema
self.camera = CameraModule(self, self.state.get("camera_settings", {}).get("version", "CameraV1"))
self.xy_stage = XYStageModule(self, self.state.get("xy_stage", {}).get("version", "XYStageV1"))
self.electrode_matrix = ElectrodeMatrixModule(
    self, None, 128, 128, version="DMLite"
)
```

### 3. Procesamiento de Comandos

Añade las rutas (routing) necesarias para los comandos específicos de tu hardware:

```python
def _process_hardware_command(self, path: str, value: Any, priority: Priority):
    try:
        if path.startswith("electrode_matrix."):
            return self._process_electrode_command(path, value)
        elif path.startswith("my_device."):
            return self._process_my_device_command(path, value)
        else:
            self.logger.warning(f"Ruta de comando desconocida: {path}")
            return False
    except Exception as e:
        self.logger.error(f"Fallo en el comando del hardware: {e}")
        return False

def _process_my_device_command(self, path: str, value: Any) -> bool:
    """Procesamiento de comandos para un hardware a medida."""
    path_parts = path.split('.')
    param_name = path_parts[1]

    if param_name == "setting":
        # Implementa aquí la lógica pertinente
        return True

    return False
```

### 4. Limpieza y Gestión de Recursos

Asegúrate de liberar correctamente los recursos y la memoria en el método `close()`:

```python
def close(self):
    """Apagado seguro del hardware."""
    if getattr(self, "_closed", False):
        return

    self._closed = True
    self.logger.info("Cerrando MyHardware")

    # Cierra tus propios módulos
    if hasattr(self, 'my_custom_module') and self.my_custom_module:
        try:
            self.my_custom_module.close()
        except Exception as e:
            self.logger.error(f"Error al cerrar my_custom_module: {e}")

    # Llama al close del padre (se encarga de visualizers y procesos de cola)
    super().close()
```

## Buenas Prácticas

1. **Sigue las convenciones de nombrado** usadas en el resto de implementaciones del código.
2. **Usa los niveles de registro (logging)** adecuados para facilitar el entorno de desarrollo y la depuración.
3. **Maneja las excepciones elegantemente** en las operaciones de componentes físicos para no crashear el thread principal.
4. **Prueba siempre usando el simulador primero** antes de avanzar a integraciones tangibles con el sistema real.
5. **Documenta los parámetros de tu equipo específicos** en el archivo `config.json`.
6. **Desarrolla flujos de recuperación de errores seguros** ante fallos de conexión por serial (USB, etc).

## Implementaciones de Referencia

Puedes explorar todo el repositorio y ver cómo trabajan los sistemas por defecto situados en el directorio `droplogic/hardware/`:

- **BOXMini** (`box_mini1.py`): Controla un equipo completo con matriz, cámara, microscopio y platina XY.
- **Simulator** (`simulator.py`): Recrea un entorno puro de simulación computacional de la matriz de electrodos (perfecto para probar los algoritmos de routing de forma aislada).
