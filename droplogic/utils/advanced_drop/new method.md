Goal

Add a third reservoir-based protocol—linear_drop—that “sweeps” the reservoir and leaves behind a grid of unit (or shaped) droplets, like the figure where droplets are pinned while the reservoir front advances.

Where

Edit #file:splitting.py.

Public API changes

Extend reservoir_extraction():

split_mode now accepts 'linear'.

Add linear_cfg: Optional[LinearConfig] = None.

New dataclass (top of file or a shared models file):

from dataclasses import dataclass
@dataclass
class LinearConfig:
    drops_per_col: int            # along sweep axis
    drops_per_row: int            # number of sweep passes (serpentine)
    space_per_col: int            # electrode pitch between drop sites along sweep axis
    space_per_row: int            # electrode pitch between rows (orthogonal to sweep)
    drop_shape: Union[Tuple[int,int], Set[Tuple[int,int]]] = (1,1) # (h,w) or explicit set
    direction: Tuple[int,int] = (1,0)  # one of (1,0), (-1,0), (0,1), (0,-1)
    neck_len: int = 1             # number of neck cells between reservoir path and site
    halo_size: int = 1            # reuse existing semantics
    dwell_pin: int = 1            # frames to hold site “on” before necking
    dwell_neck: int = 1           # frames to keep neck active before sever

New protocol

Add:

def _split_linear(
    droplets: List[Droplet],
    matrix: np.ndarray,
    reservoir_droplet: Droplet,
    cfg: LinearConfig,
    new_droplet_id: Optional[int],
    logger,
    existing_plan: Optional[DropletPlan]=None
) -> Tuple[List[Droplet], DropletPlan]:
    ...


Dispatch inside reservoir_extraction():

elif split_mode == 'linear':
    if linear_cfg is None:
        raise ValueError("linear_cfg required for split_mode='linear'")
    updated_droplets, new_plan = _split_linear(
        droplets, matrix, reservoir_droplet, linear_cfg, new_droplet_id, logger, existing_plan_copy
    )

Planner logic (sweep-and-leave-behind)

Implement _split_linear() using a serpentine sweep with a “pin–neck–sever” micro-sequence at each site.

1) Initialize plan like other protocols

Start a DropletPlan with only currently active droplets from existing_plan in the first frame.

Add trajectories for all known droplets.

Do not deactivate the reservoir; it stays active throughout the sweep.

2) Site grid

Define unit vectors:

if direction in [(1,0),(-1,0)]: primary_axis='x' and orth=(0,1)

if direction in [(0,1),(0,-1)]: primary_axis='y' and orth=(1,0)

Compute the site list (absolute origin corners) in serpentine order:

Row index r = 0..drops_per_row-1

Column index c = 0..drops_per_col-1

Along the sweep axis use space_per_col; across rows use space_per_row.

Reverse c on odd r to create serpentine.

The first site is the one the reservoir front encounters first along direction.

Bounds-check each site and skip those that would fall outside the matrix or inside forbidden cells.

3) Drop shape

If drop_shape is a tuple (h,w), expand to a set {(i,j)} with 0<=i<h, 0<=j<w.

Else if it is a set, use as-is.

4) Sweep path (reservoir movement)

For each row:

Build a front path along the primary axis long enough to pass the farthest site in that row plus cfg.neck_len+1 extra steps.

Between rows, step by space_per_row along the orthogonal axis and reverse primary direction.

5) Pin–neck–sever micro-sequence per site

For each site in sweep order, interleave with the advancing front:

Pin (frames += cfg.dwell_pin)
Activate the site cells (drop_shape translated at site origin) in the frame. Keep reservoir “on” unchanged.

Neck (frames += cfg.dwell_neck)
Advance the reservoir front one step past the site along direction.
Activate cfg.neck_len cells forming a bridge between the site and the current front path (a straight line of cells from the site’s nearest edge toward the sweep axis). Keep site active.

Sever (1 frame)
Deactivate the neck cells and leave the site active. This simulates the droplet detaching while the reservoir keeps moving.

Implementation notes:

Do not shrink reservoir_droplet.shape during the sweep. After the last site, call relax_droplet_shape(reservoir_droplet, new_plan, droplets, logger) once.

Each pinned site becomes a real Droplet object exactly once—on the sever frame—using _create_split_droplet(...).

position=site_origin, target=site_origin.

Use cfg.halo_size in the sever frame by zeroing via _calculate_droplet_halo_positions() around the site before writing it back.

Maintain new_droplet_id sequencing like 1→2/1→3.

6) Frame construction helper

Add:

def _append_linear_frame(
    new_plan: DropletPlan,
    droplets: List[Droplet],
    active_ids_limit: Optional[Set[int]],
    reservoir_droplet: Droplet,
    on_cells: Set[Tuple[int,int]],
    off_cells: Set[Tuple[int,int]],
    logger
) -> None:
    """
    Start from previous frame; turn 'off_cells' to 0, then 'on_cells' to 1; 
    append frame and recompute active_droplets_per_frame limited to 'active_ids_limit' ∪ {newly created}
    """


Use it to add each pin/neck/sever/front-advance frame. For front advance, on_cells is the new leading band of reservoir electrodes; off_cells can be empty.

7) Active droplets accounting

Mirror the logic used in _generate_extraction_frames():

Allowed active = {existing active from existing_plan} ∪ {all newly created linear droplets}.

Keep reservoir active throughout all sweep frames.

Extend trajectories of non-moving droplets to plan length with _extend_other_trajectories(...).

8) Finalization

After last row:

Append one steady frame with all droplets in their current locations (_create_final_extraction_frame).

Relax reservoir once and update last frame to include relaxed reservoir + all created droplets + previously active ones.

Validation

New _validate_linear_cfg(cfg, logger):

Positive integers for counts/spacings.

direction in allowed set.

drop_shape tuple positive or set of (int,int).

Ensure planned sites do not overlap the reservoir body at its starting location except via the neck phase (use _validate_no_overlap with the site positions if needed).

ID handling

If new_droplet_id is provided, assign it to the first created droplet; increment for each subsequent created droplet.

Performance targets

O(n) in number of frames; avoid copying the whole matrix from scratch—start from last frame and patch with on/off sets.

All trajectories lists must end with new_plan.frame_count length.

Defaults

If linear_cfg.drop_shape is (1,1), the method reproduces the “leave 1×1 behind” high-throughput case.

With drops_per_col * drops_per_row = 256, space_per_col=space_per_row=2, and direction=(1,0), reproduce the 16×16 sweep.

Example usage
cfg = LinearConfig(
    drops_per_col=16, drops_per_row=16,
    space_per_col=2, space_per_row=2,
    drop_shape=(1,1),
    direction=(1,0),
    neck_len=1, halo_size=1, dwell_pin=1, dwell_neck=1
)
droplets, plan = reservoir_extraction(
    droplets, matrix, reservoir_id, split_mode='linear',
    steps=(0,0),  # ignored by linear
    split_size=None,
    new_droplet_id=None,
    halo_size=0,
    separation_steps=0,
    logger=logger,
    existing_plan=plan,
    linear_cfg=cfg
)

Non-breaking guarantees

Existing 1to2/1to3 behavior unchanged.

Frame/trajectory accounting identical to current conventions.