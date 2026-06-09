# Division Y Extraccion

DropLogic tiene dos operaciones publicas de tipo split:

- `reservoir_extraction()`: crea una o mas gotas desde una gota-reservorio.
- `isometric_split()`: divide una gota en subgotas simetricas.

Ambas funciones extienden `system.advanced_drop.plan` y devuelven los IDs de las gotas nuevas.

El modo de extraccion `1to3` existe para geometrias compactas de reservorio donde abrir espacio alrededor de la gota hija puede mejorar el control y la repetibilidad del pinch-off.

## Reservoir Extraction

```python
new_ids = system.advanced_drop.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to2",
    steps=(0, 10),
    split_size={(2, 2), (2, 3), (3, 2), (3, 3)},
    new_droplet_id=10,
)
```

Argumentos:

- `reservoir_droplet_id`: ID de la gota-reservorio.
- `split_mode`: `"1to2"`, `"1to3"` o `"linear"`.
- `steps`: desplazamiento desde la esquina del reservorio para `"1to2"` y `"1to3"`.
- `split_size`: forma o tamano de la gota extraida.
- `new_droplet_id`: primer ID nuevo opcional.
- `halo_size`: halo inactivo alrededor de la gota extraida para `"1to2"`.
- `separation_steps`: distancia de separacion para `"1to3"`.
- `remove_duplicate_frames`: recorta frames repetidos tras extender el plan.

`steps` son `(row_delta, col_delta)`. Fila negativa mueve hacia arriba; columna positiva mueve hacia la derecha.

## `1to2`

Extrae una gota desde el reservorio.

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando reservoir_extraction(split_mode=\"1to2\") creando una gota central 2x2 desde un reservorio 6x6](../../assets/advanced-drop/reservoir-extraction-1to2.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>reservoir_extraction(split_mode="1to2")</code>: reservorio 6x6 y gota central 2x2 extraida</figcaption>
</figure>

```python
ad.droplets.create_droplet(1, origin=(20, 16), target=(20, 16), width=6, height=6)

new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to2",
    steps=(0, 10),
    split_size={(2, 2), (2, 3), (3, 2), (3, 3)},
    halo_size=1,
)
```

Usalo cuando quieres que el reservorio conserve la mayor parte de su huella mientras produce una gota menor.

## `1to3`

Extrae una gota central y separa las piezas resultantes.

```python
ad.droplets.create_droplet(1, origin=(24, 16), target=(24, 16), width=12, height=12)

new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="1to3",
    steps=(0, 14),
    split_size=(2, 2),
    separation_steps=4,
)
```

Para `"1to3"`, `split_size` se interpreta como `(height, width)`. Usalo cuando la dispensacion directa desde reservorio esta geometricamente restringida.

## `linear`

Crea multiples gotas en un barrido lineal desde un reservorio.

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando reservoir_extraction(split_mode=\"linear\") creando lineas de gotas desde un reservorio ancho](../../assets/advanced-drop/reservoir-extraction-linear.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>reservoir_extraction(split_mode="linear")</code>: reservorio ancho y tres lineas completas de gotas 1x1</figcaption>
</figure>

```python
new_ids = ad.reservoir_extraction(
    reservoir_droplet_id=1,
    split_mode="linear",
    linear_drops_number=21,
    linear_offset=0,
    linear_space_per_col=3,
    linear_space_per_row=1,
    linear_drop_shape=(1, 1),
    linear_direction=(0, 1),
)
```

Usa `linear_direction=(0, 1)` para barrido horizontal hacia la derecha, `(1, 0)` hacia abajo y valores negativos en la direccion opuesta.

## Isometric Split

`isometric_split()` divide recursivamente una gota en subgotas iguales y las mueve de forma simetrica.

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando isometric_split() dividiendo una gota 4x4 en dieciseis gotas 1x1](../../assets/advanced-drop/isometric-split-1x1.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>isometric_split()</code>: una gota 4x4 dividida hasta dieciseis gotas 1x1 espaciadas uniformemente</figcaption>
</figure>

```python
new_ids = ad.isometric_split(
    droplet_id=1,
    steps=[(0, 8), (8, 0), (0, 4), (4, 0)],
    simultaneous=True,
    new_droplet_id=2,
)
```

Argumentos:

- `droplet_id`: gota origen.
- `steps`: lista de desplazamientos `(row_delta, col_delta)`.
- `simultaneous`: mueve subgotas dentro de un paso juntas o secuencialmente.
- `new_droplet_id`: primer ID nuevo opcional.
- `event_id`: etiqueta de evento opcional.
- `remove_duplicate_frames`: recorta frames repetidos tras extender el plan.

## Fallos Comunes

- El ID de gota o reservorio no existe.
- `steps` colocaria gotas fuera de la matriz.
- La gota extraida solapa con el reservorio.
- La gota origen no tiene suficientes electrodos para el split pedido.
- El area alrededor esta demasiado restringida para separar.

## Referencias

<ol class="dl-references-list">
  <li id="ref-hu-2022">C. Hu, H. Zhang, C. Jiang and H. Ma, <a href="https://pubs.aip.org/aip/apl/article/120/12/121602/2833126/A-geometrical-model-of-pinch-off-in-digital">"A geometrical model of pinch-off in digital microfluidics underpins 'one-to-three' droplet generation"</a>, <em>Applied Physics Letters</em> 120, 121602 (2022), DOI: <a href="https://doi.org/10.1063/5.0086953">10.1063/5.0086953</a>.</li>
  <li id="ref-jin-2021">K. Jin, C. Hu, S. Hu, C. Hu, J. Li and H. Ma, <a href="https://pubs.rsc.org/it-it/content/articlelanding/2021/lc/d1lc00421b">"'One-to-three' droplet generation in digital microfluidics for parallel chemiluminescence immunoassays"</a>, <em>Lab on a Chip</em> 21, 2892-2900 (2021), DOI: <a href="https://doi.org/10.1039/D1LC00421B">10.1039/D1LC00421B</a>.</li>
</ol>
