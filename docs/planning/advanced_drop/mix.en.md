# Mix

`mix()` creates mixing motion for one droplet.

```python
new_ids = system.advanced_drop.mix(
    droplet_id=1,
    mode="split_recombine",
    cycles=5,
)
```

The function extends `system.advanced_drop.plan` and returns the IDs of any new droplets created during the operation.

## Public Signature

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

This mode repeatedly splits and recombines a droplet when the droplet shape allows it.

<figure class="dl-plan-demo" markdown>
  ![Simulator GIF showing mix(mode="split_recombine") splitting and recombining a droplet](../../assets/advanced-drop/mix-split-recombine.gif)
  <figcaption><code>mix(mode="split_recombine")</code> splitting and recombining a droplet</figcaption>
</figure>

```python
new_ids = ad.mix(
    droplet_id=1,
    mode="split_recombine",
    cycles=3,
)
```

Use `split_area` if the operation needs a specific area for symmetric extension:

```python
split_area = {(r, c) for r in range(20, 30) for c in range(20, 30)}

ad.mix(
    droplet_id=1,
    mode="split_recombine",
    split_area=split_area,
    cycles=4,
)
```

If the droplet cannot be split safely, the implementation can fall back to loop-style movement for the remaining cycles.

## `2d_loop`

This mode moves the droplet around a rectangular loop.

<figure class="dl-plan-demo" markdown>
  ![Simulator GIF showing mix(mode="2d_loop") moving a droplet around a loop](../../assets/advanced-drop/mix-2d-loop.gif)
  <figcaption><code>mix(mode="2d_loop")</code> creating a repeated loop trajectory</figcaption>
</figure>

```python
ad.mix(
    droplet_id=1,
    mode="2d_loop",
    mixing_area_size=8,
    cycles=5,
)
```

Use this when you want mixing by repeated translation rather than splitting.

## Choosing a Mode

- Use `split_recombine` for larger droplets where split/rejoin mixing is physically meaningful.
- Use `2d_loop` for smaller droplets, constrained layouts, or protocols where you want one droplet to stay intact.
- Increase `cycles` for stronger mixing, but remember that this also increases plan length.

## Event Labels

```python
ad.mix(
    droplet_id=1,
    mode="2d_loop",
    cycles=4,
    event_id="mix_sample",
)
```

Event labels make long protocols easier to inspect in the plan debugger.
