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
  ![Executor-recorded simulator GIF showing mix(mode="split_recombine") splitting and recombining a 2x2 droplet](../../assets/advanced-drop/mix-split-recombine.gif)
  <figcaption><code>PlanExecutor</code> recording of <code>mix(mode="split_recombine")</code>: one 2x2 droplet split and recombined for one cycle</figcaption>
</figure>

```python
ad.droplets.create_droplet(
    1,
    origin=(28, 28),
    target=(28, 28),
    width=2,
    height=2,
)

new_ids = ad.mix(
    droplet_id=1,
    mode="split_recombine",
    cycles=1,
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
  ![Executor-recorded simulator GIF showing mix(mode="2d_loop") moving one 2x2 droplet around a rectangular loop](../../assets/advanced-drop/mix-2d-loop.gif)
  <figcaption><code>PlanExecutor</code> recording of <code>mix(mode="2d_loop")</code>: one 2x2 droplet moved around a rectangular loop</figcaption>
</figure>

```python
ad.droplets.create_droplet(
    1,
    origin=(24, 24),
    target=(24, 24),
    width=2,
    height=2,
)

ad.mix(
    droplet_id=1,
    mode="2d_loop",
    mixing_area_size=8,
    cycles=1,
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
