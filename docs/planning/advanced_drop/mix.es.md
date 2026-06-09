# Mezcla

`mix()` crea movimiento de mezcla para una gota.

```python
new_ids = system.advanced_drop.mix(
    droplet_id=1,
    mode="split_recombine",
    cycles=5,
)
```

La funcion extiende `system.advanced_drop.plan` y devuelve IDs de gotas nuevas creadas durante la operacion.

Los dos modos incluidos siguen estrategias clasicas de DMF: mover la gota intacta en un loop 2D, o dividirla y recombinarla cuando la geometria lo permite.

## Elegir Un Modo

| Modo | Usalo cuando | Ten cuidado cuando | Parametros principales |
| --- | --- | --- | --- |
| `split_recombine` | La gota puede dividirse limpiamente y quieres reordenamiento interno fuerte. | La huella es pequena, asimetrica, cerca de obstaculos, o el sistema fisico no divide de forma fiable. | `cycles`, `split_area` |
| `2d_loop` | La gota debe permanecer intacta mientras se mueve por un loop 2D. | El area disponible es pequena, bloqueada o demasiado cerca de otras gotas. | `cycles`, `mixing_area_size` |

## Firma Publica

```python
system.advanced_drop.mix(
    droplet_id,
    mode="split_recombine",
    split_area=None,
    mixing_area_size=None,
    cycles=5,
    event_id=None,
    remove_duplicate_frames=False,
)
```

## `split_recombine`

Este modo divide y recombina repetidamente una gota cuando su forma lo permite.

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando mix(mode=\"split_recombine\") dividiendo y recombinando una gota 2x2](../../assets/advanced-drop/mix-split-recombine.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>mix(mode="split_recombine")</code>: una gota 2x2 dividida y recombinada durante un ciclo</figcaption>
</figure>

```python
ad.droplets.create_droplet(1, origin=(28, 28), target=(28, 28), width=2, height=2)
new_ids = ad.mix(droplet_id=1, mode="split_recombine", cycles=1)
```

Usa `split_area` si la operacion necesita un area especifica para extension simetrica.

Si la gota no puede dividirse con seguridad, la implementacion puede volver a movimiento tipo loop para los ciclos restantes.

## `2d_loop`

Este modo mueve la gota alrededor de un loop rectangular.

<figure class="dl-plan-demo" markdown>
  ![GIF del simulador mostrando mix(mode=\"2d_loop\") moviendo una gota 2x2 alrededor de un loop rectangular](../../assets/advanced-drop/mix-2d-loop.gif)
  <figcaption>Grabacion de <code>PlanExecutor</code> de <code>mix(mode="2d_loop")</code>: una gota 2x2 movida alrededor de un loop rectangular</figcaption>
</figure>

```python
ad.droplets.create_droplet(1, origin=(24, 24), target=(24, 24), width=2, height=2)
ad.mix(droplet_id=1, mode="2d_loop", mixing_area_size=8, cycles=1)
```

Usalo cuando quieras mezclar mediante traslacion repetida en vez de dividir la gota.

## Etiquetas De Evento

```python
ad.mix(
    droplet_id=1,
    mode="2d_loop",
    cycles=4,
    event_id="mix_sample",
)
```

Las etiquetas facilitan inspeccionar protocolos largos en el plan debugger.

## Referencias

<ol class="dl-references-list">
  <li id="ref-paik-2003">P. Paik, V. K. Pamula and R. B. Fair, <a href="https://pubs.rsc.org/en/content/articlelanding/2003/lc/b307628h">"Rapid droplet mixers for digital microfluidic systems"</a>, <em>Lab on a Chip</em> 3, 253-259 (2003), DOI: <a href="https://doi.org/10.1039/B307628H">10.1039/B307628H</a>.</li>
</ol>
