# Empezando

## Instalación

Dado que **DropLogic** se distribuye como una librería estándar, los usuarios pueden instalarla fácilmente usando `pip`:

```bash
git clone https://github.com/your-org/droplogic.git
cd droplogic
pip install .
```

Para desarrollo (modo edición):
```bash
pip install -e .
```

!!! warning "Requisito para Controladores de Hardware"
    Para utilizar dispositivos físicos (como la Matriz de Electrodos, la Platina XY o la Cámara), debes instalar el **DropLogic Runtime Installer** correspondiente a tu plataforma. Este paquete de runtime se distribuye por separado de la librería de Python a través del proveedor de hardware o del mantenedor de la plataforma.
    
    Adicionalmente, para habilitar el soporte de cámara (MVS), deberás descargar e instalar el Machine Vision Software oficial de Hikrobot desde su web:
    [https://www.hikrobotics.com/en/machinevision/service/download/](https://www.hikrobotics.com/en/machinevision/service/download/)

## Uso Básico: Sistemas y Módulos

Para empezar a usar **DropLogic**, primero necesitas entender dos conceptos clave: **Sistemas (Systems)** y **Módulos (Modules)**.

- **Sistema (System):** Un sistema representa toda la máquina de hardware o el entorno de simulación. DropLogic dispone de algunos sistemas preconstruidos como `box_mini1` y `DMLite` (plataformas de referencia basadas en la tecnología de Mojado Eléctrico de Matriz Activa sobre un Dieléctrico o AM-EWOD), y también el módulo computacional `simulator.py` (un entorno puramente computacional de prueba, totalmente agnóstico de su tecnología de hardware).
- **Módulo (Module):** Un sistema es esencialmente una colección de módulos. Un módulo controla un componente de hardware específico, como la matriz de electrodos, la cámara o los controladores de temperatura. Los módulos pueden tener diferentes **versiones o implementaciones** (ej. `CameraV1` o `MicroscopeV2`), lo que te permite intercambiar componentes físicos de hardware manteniendo exactamente la misma sintaxis en tu código de DropLogic.

*(Para una explicación más estructurada de sistemas, módulos y de cómo se ensamblan nuevas máquinas, consulta la sección **Systems** del menú de navegación, que termina con nuestra guía [Creating New Systems](creating_systems.md)).*

A continuación se muestra un ejemplo rápido de cómo empezar a usar un sistema **Simulador** dentro de tus scripts:

```python
from droplogic.hardware.simulator import Simulator

# 1. Inicializar el sistema
system = Simulator(log_level="INFO")

# 2. Comanda y configura tus módulos (ej. crea una gota de 2x2 en un hueco de la matriz)
system.advanced_drop.droplets.create_droplet(
    droplet_id=1,
    origin=(10, 10),
    target=(50, 50),
    width=2, height=2
)

# 3. Pídele al planificador que genere el ruteo interno (routing)
system.advanced_drop.move(mode="sipp")
system.advanced_drop.executor.start(frame_delay=0.5, enable_visualizers=True)
```

## Ejemplos Incluidos

Si deseas ver casos de uso continuo más complejos, puedes consultar la carpeta `examples/` incluida en el repositorio, o abrir la nueva subsección **Getting Started > Example Scripts** del menú de navegación para ver el código completo y los enlaces directos a GitHub:

- `examples/simulator_example.py`: Una demostración 100% de software donde una matriz virtual de 128x128 instancia 20 gotas gigantes y las comanda en un bucle infinito que se regenera automáticamente.
- `examples/DMLite_example.py`: Se trata exactamente del mismo código de enrutamiento, pero interconectándose al hardware físico de AM-EWOD (como `BOXMini` o `DMLite`). Implementa un `frame_delay` mayor para que respete de forma segura las demoras introducidas al interconectar voltajes y esperar a la propia física de los fluidos.
