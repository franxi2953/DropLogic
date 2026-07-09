## Droplets, Reservoirs, And Injection
Droplet tools:
- Use `clear_droplet_state(reset_executor=true)` to start a clean logical protocol: it clears all AdvancedDrop droplets, removes old plan frames, and resets the PlanExecutor cursor. It does not replace visual verification or physical deactivation; use `emergency_stop(deactivate_electrodes=true)` first when electrodes must be turned off.
- Use `create_droplet(droplet_id=1, origin=[row, col], target=[row, col], width=1, height=1)` for one droplet.
- Use `add_droplets(droplets=[...])` for batches. Each entry needs `id`/`droplet_id` and `origin`; include `target` unless explicitly optional.
- Valid batch entry: `{"id": 1, "origin": [42, 1], "target": [30, 30], "width": 1, "height": 1}`.
- After `add_droplets`, verify `created_count == requested_count` and `droplets.total_droplets` increased; otherwise stop and report the error.
- Retarget with `update_droplet_targets(targets=[{"id": 1, "target": [30, 30]}])` or `update_droplet_targets(targets={"1": [30, 30]})`; do not delete/recreate just to retarget.
- Choose all movement targets so final footprints and vital spaces do not overlap any active droplet's current or final footprint. If the final target for a droplet uses space currently occupied or protected by another active droplet, first move the blocker to an intermediate parking position, execute that segment, then retarget to the final layout.
- Keep movement batch target grids conservatively away from cartridge edges. Passing target validation only proves the final footprint is legal; SIPP can still fail when a target is tight against an edge or leaves poor approach corridors. For larger footprints or larger `vital_space`, keep extra margin beyond the validated footprint/vital space, and use nearer/intermediate targets after one failed edge-side target attempt.
- Use `update_droplet_position` only after visual/user confirmation that the physical droplet is at that coordinate.
- `update_droplet_targets` returns compact count/id summary by default. Set `include_summary=true` only when the full droplet summary is needed.
- `delete_droplet(droplet_id=...)` removes the logical droplet and, by default, clears that droplet's electrodes in the next plan frame (`persist_electrodes=false`). Use `persist_electrodes=true` only for explicit supervised debugging where the physical/electrical footprint must remain active; otherwise it leaves ghost electrodes that can confuse later planning and visual interpretation.
- For droplets larger than `1 x 1`, default `vital_space=2` and at least `2` electrodes between extraction targets/reservoir exits unless specified otherwise.
- SIPP gets expensive with many droplets, dense routes, narrow corridors, overlapping vital spaces, or crossing/reordering. For hardware, keep each movement planning batch to `5-10` droplets maximum and prefer `5` in crowded or crossing layouts.
- Check that intended final positions and vital spaces do not intersect current droplet positions. If they do, do not ask SIPP to solve the swap in one call; move the blockers to intermediate parking positions first.

Reservoir and injection rules:
- Default cartridge family: Acxel 16k.
- User injections enter from lateral input holes; hole definitions belong in cartridge JSON.
- Manual injection/loading position is `config.json.presets.stage.manual_injection.position`; use `move_stage(preset="manual_injection")` instead of hardcoded stage coordinates.
- Unless user or cartridge JSON defines blocked/no-go regions, assume the matrix is usable.
- Reservoirs for injected liquid should be near the relevant border but not on the border. Leave at least one row/column margin.
- Before asking the user to inject, reservoir electrodes must already be active on the real matrix. Create reservoir, execute activation, verify/inspect it, then move to injection position or tell the user to inject.
- Create-only reservoir activation is a valid physical segment when the plan is executable; do not add fake moves just to make an activation visible.
- After moving to manual injection position, wait for user confirmation that injection is complete.
- After confirmation, return to the previous Y position unless the protocol profile defines another operating/imaging position.
- Before extraction/downstream operations, move injected reservoir `5-10` electrodes from the edge. Execute and verify this relocation before extracting.
- Keep experiment-specific stage or imaging overrides in a protocol profile.

Reservoir sizing:
- Size reservoirs for consumed electrode area plus at least `20` extra electrodes unless specified otherwise.
- Consumed area is approximately `count * width * height`; use that formula for any droplet footprint rather than assuming a fixed shape.
- Extra area covers residual liquid, edge loss, imperfect splitting, and dead volume.
