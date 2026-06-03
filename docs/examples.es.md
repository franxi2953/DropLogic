# Ejemplos de DropLogic

Para ayudarte a ponerte al día rápidamente, DropLogic incluye el directorio `examples/` en su código fuente, con scripts funcionales listos para ejecutar.

En ellos podrás ver cómo inicializar los sistemas, instanciar múltiples gotas en puntos del grid, calcular rutas usando nuestro planificador SIPP y ejecutar movimientos de manera asíncrona.

Estos son los dos ejemplos principales que incluimos por defecto:

## 1. Ejemplo de Simulador (`simulator_example.py`)

Este script ejecuta un ruteo puramente virtual en caso de que no tengas hardware conectado a tu ordenador. Instancia una matriz virtual de 128x128 usando el sistema `Simulator`, crea 20 gotas gigantes (2x2 píxeles cada una) y genera un bucle infinito de enrutamiento continuo.

- Emplea el sistema puramente computacional `Simulator`.
- El retraso por frame en el plan de ejecución  (delay) es de apenas `0.5s` para que el visualizador muestre el movimiento rápido.
- Cuando las 20 gotas terminan de llegar a su destino, el programa escoge 20 coordenadas nuevas de forma aleatoria, replanifica las rutas y vuelven a moverse.

Lo ejecutas situándote en el directorio principal y tecleando:
```bash
python3 examples/simulator_example.py
```

## 2. Ejemplo con Máquina Real (`DMLite_example.py`)

Este script implementa exactamente el mismo bucle infinito de movimiento que el simulador, pero conectado a hardware físico de Acxel (matrices AM-EWOD `DMLite` / `BOXMini`) mediante la capa adaptadora de DropLogic. `BOXMini` y `DMLite` son dispositivos de Acxel, no módulos propios de DropLogic; consulta [Acxel](https://www.acxel.com/) para la información del proveedor.

- Usa las capas hardware y abstrae la complejidad de la física física.
- Para darle tiempo a los circuitos de alto voltaje de enrutar las gotas físicas entre electrodos, el retardo o _delay_ de ejecución por frame se ubica en un nivel seguro de `1.0s`.
- Al rodar esto, verás cómo los algoritmos de enrutamiento computan y tu chip de microfluídica responde en tiempo real.

Puedes usarlo si tienes la máquina DropLogic conectada a tu USB:
```bash
python3 examples/DMLite_example.py
```
