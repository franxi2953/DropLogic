# Hardware

Esta librería Python envuelve código de comunicación e integración para varios dispositivos de hardware abierto y cerrado usados en microfluídica digital:

Cuando esta documentación menciona `DMLite` o `BOXMini`, esos nombres se refieren a plataformas hardware de Acxel. Este repositorio solo contiene código adaptador en Python para hardware compatible; el hardware del proveedor y los assets nativos de runtime no forman parte del árbol de código fuente. Consulta [Acxel](https://www.acxel.com/) para la información del proveedor.

- **Sistemas de Visión**: Integración con cámaras MVS (`mvs_camera`) y algoritmos AI/YOLO para detección de gotas.
- **Plataformas XY**: Controladores (`nmc_controller`).
- **Control Térmico**: Sistemas Peltier y termocuplas.
- **Microscopios**: Control de focalización y captura.
- **Matriz de Electrodos**: Adaptadores para plataformas como `DMLite` de Acxel.
