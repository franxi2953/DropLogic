import sys, signal, atexit, time, threading
from collections import deque
import numpy as np
from scipy.ndimage import label, binary_dilation
from datetime import datetime
from pathlib import Path
import pathlib
import cv2
import os
import math
from scipy.ndimage import distance_transform_edt

class BasicDrop:
    """
    Path-planning helper for BOXMini droplets, **headless version**

    Parameters
    ----------
    parent : object
        Reference to the BOXMini (or similar) instance.
    """

    _global_instance = None  # for Ctrl-C cleanup

    def __init__(self, parent):
        self.parent = parent

        # Register clean-up handlers
        BasicDrop._global_instance = self
        signal.signal(signal.SIGINT, self._signal_handler)
        atexit.register(self.close)

    # ───────────────────────── position / connectivity ──────────────────────
    @staticmethod
    def _find_positions(matrix, value):
        return [(x, y) for x in range(matrix.shape[0])
                        for y in range(matrix.shape[1]) if matrix[x, y] == value]

    @staticmethod
    def _is_connected(positions):
        if not positions:
            return False
        visited, queue = set(), deque([next(iter(positions))])
        while queue:
            x, y = queue.popleft()
            if (x, y) in visited:
                continue
            visited.add((x, y))
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                n = (x+dx, y+dy)
                if n in positions and n not in visited:
                    queue.append(n)
        return len(visited) == len(positions)
    
    def prune_droplet(self, expanded, size, forbidden, direction, prev_shape, bfs_center, matrix_shape):
        """
        Prune droplet while ensuring center aligns with BFS and remains within bounds.
        """
        if len(expanded) <= size:
            return expanded  # Already correct size

        rows, cols = matrix_shape
        shape = set(expanded)

        def score(cell):
            """
            Compute pruning score:
            - Prefer forward movement.
            - Keep shape close to previous droplet.
            - Maintain compactness and BFS center.
            """
            cell_vector = np.array(cell) - bfs_center
            direction_score = np.dot(cell_vector, direction)
            overlap_score = max(1 / (1 + np.linalg.norm(np.array(cell) - np.array(p))) for p in prev_shape)
            center_penalty = np.linalg.norm(np.array(cell) - bfs_center)
            return 0.1 * direction_score + 0.3 * overlap_score - 0.6 * center_penalty

        # Sort cells: prune the worst first
        sorted_cells = sorted(shape, key=score)

        # Remove worst cells while maintaining size & connectivity
        for cell in sorted_cells:
            if len(shape) <= size:
                break
            candidate = shape - {cell}
            if self._is_connected(candidate) and not candidate & forbidden:
                shape = candidate

        # **Ensure center matches BFS center**
        pruned_center = np.mean(np.array(list(shape)), axis=0)

        # **Compute shift while ensuring in-bounds**
        shift_vector = bfs_center - pruned_center
        shift_vector = np.round(shift_vector).astype(int)  # Integer move only

        adjusted_shape = set()
        for x, y in shape:
            nx, ny = x + shift_vector[0], y + shift_vector[1]
            if 0 <= nx < rows and 0 <= ny < cols:  # **Check bounds**
                adjusted_shape.add((nx, ny))

        # If shifting failed due to bounds, return unshifted shape
        if len(adjusted_shape) == size and self._is_connected(adjusted_shape) and not adjusted_shape & forbidden:
            return adjusted_shape
        else:
            return shape

    def generate_frames(self, matrix, path_shapes):
        frames = []
        for shape in path_shapes:
            frame = np.zeros_like(matrix)
            frame[matrix == -1] = -1
            frame[matrix == 2] = 2
            for x, y in shape:
                frame[x, y] = 1
            frames.append(frame)
        return frames

    # ---------------- PATHFINDING AND SMOOTHING ----------------

    def bfs_pathfinding(self, matrix, droplet, targets, forbidden):
        """
        BFS that **moves the droplet's center of mass** towards the target.
        """
        rows, cols = matrix.shape
        visited, queue = set(), deque()
        queue.append((droplet, [droplet]))  

        while queue:
            current_shape, path_shapes = queue.popleft()
            shape_frozen = frozenset(current_shape)
            if shape_frozen in visited:
                continue
            visited.add(shape_frozen)

            # Compute center of mass and check if it's inside target
            center_of_mass = np.mean(np.array(list(current_shape)), axis=0).astype(int)
            if tuple(center_of_mass) in targets:
                return path_shapes

            # Expand in 4 directions
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                candidate = {(x + dx, y + dy) for x, y in current_shape}
                if any(x < 0 or x >= rows or y < 0 or y >= cols for x, y in candidate):
                    continue
                if candidate & forbidden:
                    continue
                if not self._is_connected(candidate):
                    continue
                queue.append((candidate, path_shapes + [candidate]))

        return None

    def smooth_path(self, path_shapes, matrix, forbidden):
        """
        Smooth BFS path while enforcing center alignment **within matrix bounds**.
        """
        smoothed_shapes = [path_shapes[0]]
        droplet_size = len(path_shapes[0])
        rows, cols = matrix.shape

        for i in range(1, len(path_shapes)):
            prev_shape = smoothed_shapes[-1]
            next_bfs_shape = path_shapes[i]

            # Compute centers
            prev_center = np.mean(np.array(list(prev_shape)), axis=0)
            bfs_center = np.mean(np.array(list(next_bfs_shape)), axis=0)
            direction = bfs_center - prev_center
            direction = direction / np.linalg.norm(direction) if np.linalg.norm(direction) != 0 else np.zeros_like(direction)

            # Expand only within BFS bounding box
            expanded = set()
            for x, y in prev_shape:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < rows and 0 <= ny < cols) and (nx, ny) not in prev_shape:
                        expanded.add((nx, ny))

            expanded |= prev_shape
            expanded -= forbidden  # Remove forbidden areas

            # **Pass matrix shape to prevent out-of-bounds shifting**
            pruned_shape = self.prune_droplet(expanded, droplet_size, forbidden, direction, prev_shape, bfs_center, matrix.shape)

            # Fallback to BFS shape if pruning fails
            smoothed_shapes.append(pruned_shape if pruned_shape else next_bfs_shape)

        return smoothed_shapes

    def find_parent_drop(self, matrix, droplet, boundary_value=-1):
        boundary_mask = (matrix == boundary_value)
        labeled_array, num_features = label(boundary_mask)
        for x, y in droplet:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < matrix.shape[0] and 0 <= ny < matrix.shape[1]:
                    label_value = labeled_array[nx, ny]
                    if label_value > 0:
                        return set(map(tuple, np.argwhere(labeled_array == label_value)))
        return set()

    def dump_debug_frame(self,tag, board, out_dir, debug):
        if not debug:
            return
        Path(out_dir).mkdir(exist_ok=True, parents=True)
        img = np.zeros((*board.shape, 3), np.uint8)
        img[board == -1] = (0, 0, 255)
        img[board == 2] = (0, 255, 0)
        img[board == 1] = (255, 255, 0)
        cv2.imwrite(os.path.join(out_dir, f"{tag}.png"),
                    cv2.resize(img, (512, 512), interpolation=cv2.INTER_NEAREST))

    def inflate_forbidden(self, board, offset):
        base_forbidden = set(map(tuple, np.argwhere(board == -1)))
        if offset < 1:
            return base_forbidden
        mask = (board == -1)
        se_f = np.ones((2 * offset + 1, 2 * offset + 1), bool)
        inf_mask = binary_dilation(mask, structure=se_f)
        return set(map(tuple, np.argwhere(inf_mask)))

    def compute_centers(self, path_shapes):
        return [
            (math.ceil(sum(xs) / len(xs)), math.ceil(sum(ys) / len(ys)))
            for xs, ys in (zip(*shape) for shape in path_shapes)
        ]

    def extend_until_target_covered(self, smooth, targets, forbidden, max_steps=10):
        if len(smooth) < 2 or targets <= smooth[-1]:
            return smooth
        prev = np.mean(np.array(list(smooth[-2])), axis=0)
        curr = np.mean(np.array(list(smooth[-1])), axis=0)
        direction = curr - prev
        if np.linalg.norm(direction) == 0:
            return smooth
        direction = np.round(direction / np.linalg.norm(direction)).astype(int)
        rows, cols = max(x for x, _ in smooth[-1]) + 1, max(y for _, y in smooth[-1]) + 1
        current = smooth[-1]
        for _ in range(max_steps):
            moved = {(x + direction[0], y + direction[1]) for x, y in current}
            if any(x < 0 or x >= rows or y < 0 or y >= cols for x, y in moved):
                break
            if moved & forbidden or not BasicDrop._is_connected(moved):
                break
            smooth.append(moved)
            current = moved
            if targets <= current:
                break
        return smooth

    # ---------------- MAIN FUNCTIONS ----------------

    def move_droplet(self,
                 matrix,
                 *,
                 keep_initial: bool = False,
                 keep_targets: bool = False,
                 deactivated_offset: int = -1,
                 offset_forbidden: int = -1,
                 debug: bool = False,
                 out_dir: str = "debug_out"):

        board = np.array(matrix, int).copy()
        pristine = board.copy() 
        ttag = datetime.now().strftime("%H%M%S")

        self.dump_debug_frame(f"{ttag}_0_original", board, out_dir, debug)

        # 1. Initial state
        droplet = set(self._find_positions(board, 1))
        if not droplet:
            raise ValueError("No droplet on the board")
        if not self._is_connected(droplet):
            raise ValueError("Droplet is not connected")

        original_ones = set(droplet)

        # 2. Remove surrounding blob for planning
        parent_mask, _ = label(board == 1)
        parent_lbl = parent_mask[next(iter(droplet))]
        parent_blob = set(map(tuple, np.argwhere(parent_mask == parent_lbl)))
        has_parent_blob = len(parent_blob) > len(droplet)
        if has_parent_blob:
            for (x, y) in parent_blob - droplet:
                board[x, y] = 0
        else:
            if not keep_initial:
                pristine[pristine == 1] = 0

        self.dump_debug_frame(f"{ttag}_1_parent_removed", board, out_dir, debug)
        self.dump_debug_frame(f"{ttag}_1_parent_removed_pristine", pristine, out_dir, debug)

        # 3. Remove -1s touching the droplet
        boundary = self.find_parent_drop(board, droplet, boundary_value=-1)
        for (x, y) in boundary:
            board[x, y] = 0

        self.dump_debug_frame(f"{ttag}_2_boundary_removed", board, out_dir, debug)

        # 4. Pathfinding
        targets = set(self._find_positions(board, 2))
        forbidden = self.inflate_forbidden(board, offset_forbidden)

        path = self.bfs_pathfinding(board, droplet, targets, forbidden)
        if path is None:
            raise ValueError("No valid path found")

        smooth = self.smooth_path(path, board, forbidden)
        smooth = self.extend_until_target_covered(smooth, targets, forbidden)

        # 5. Compute centers
        centers = self.compute_centers(smooth)

        # 6. Restore boundary
        for (x, y) in boundary:
            board[x, y] = -1

        frames = self.generate_frames(board, smooth)

        # 7. Static-on electrodes with corrected logic

        static_on = set()
        if keep_initial:
            static_on |= original_ones
            if has_parent_blob:
                static_on |= parent_blob
        else:
            if has_parent_blob:
                static_on |= parent_blob

        if static_on:
            for f in frames:
                for (x, y) in static_on:
                    f[x, y] = 1

        # 8. Halo around the moving droplet
        if deactivated_offset >= 0:
            se_h = np.ones((2 * deactivated_offset + 1, 2 * deactivated_offset + 1), bool)
            static_mask = np.zeros_like(pristine, bool)
            for (x, y) in static_on:
                static_mask[x, y] = True

            updated_frames = []
            for f in frames:
                f2 = pristine.copy()
                f2[static_mask] = 1
                droplet_mask = (f == 1) & ~static_mask
                f2[droplet_mask] = 1
                halo = binary_dilation(droplet_mask, structure=se_h) & ~droplet_mask & ~static_mask
                f2[halo] = 0
                updated_frames.append(f2)
            frames = updated_frames

        self.dump_debug_frame(f"{ttag}_3_first_frame", frames[0], out_dir, debug)
        self.dump_debug_frame(f"{ttag}_last_frame", frames[-1], out_dir, debug)

        # 9. Convert to binary format
        orig_mask = (pristine == -1)
        frames_out = []
        for idx, f in enumerate(frames):
            f_mod = f.copy()
            if idx == len(frames) - 1:
                f_mod[orig_mask] = 1
            g = f_mod.copy()
            g[(g == -1) | (g == 1)] = 1
            g[g == 2] = 1 if keep_targets else 0
            frames_out.append(g)

        return frames_out, centers

    def mix(self,
            matrix: np.ndarray,
            electrode: tuple[int, int],
            drop_width: int,
            drop_height: int,
            *,
            steps_up: int = 1,
            steps_down: int = 1,
            steps_left: int = 1,
            steps_right: int = 1,
            cycles: int = 1,
            keep_initial: bool = False,
            deactivated_offset: int = -1
    ) -> list[np.ndarray]:
        """
        Oscillate a rectangular droplet in each cardinal direction,
        always returning to its start position before switching direction.

        - Preserves ALL original 1's in `matrix`.
        - Optionally preserves the seed rect if keep_initial=True.
        - Can draw a halo of zeros around just the moving droplet.
        """

        R, C = matrix.shape
        row, col = electrode

        # 0) record every pad that was originally active → must stay on
        original_ones = set(self._find_positions(matrix, 1))

        # 1) compute seed rectangle (init droplet)
        r0 = row - drop_height//2
        c0 = col - drop_width //2
        init = {
            (r0+dr, c0+dc)
            for dr in range(drop_height)
            for dc in range(drop_width)
            if 0 <= r0+dr < R and 0 <= c0+dc < C
        }

        # 2) build static_on = original ones ∪ optionally init
        static_on = set(original_ones)
        if keep_initial:
            static_on |= init

        # 3) helper: build frame from a shape set
        def build(shape):
            f = np.zeros((R, C), int)
            for (x, y) in static_on | shape:
                f[x, y] = 1
            return f

        # 4) helper: single‐step shift (dx,dy) with bounds check
        def step(shape, dx, dy):
            cand = {(x+dx, y+dy) for x,y in shape}
            if any(x<0 or x>=R or y<0 or y>=C for x,y in cand):
                return shape
            return cand

        # 5) precompute halo structuring element if needed
        if deactivated_offset >= 0:
            se = np.ones((2*deactivated_offset+1,
                          2*deactivated_offset+1), bool)

        frames = []
        for _ in range(cycles):
            # for each direction: start from init, step N times, then reset

            # Up
            shape = set(init)
            for _ in range(steps_up):
                shape = step(shape, -1, 0)
                f2 = build(shape)
                if deactivated_offset >= 0:
                    # remove halo around just the moving droplet
                    droplet_mask = np.zeros((R, C), bool)
                    for x,y in shape:
                        droplet_mask[x,y] = True
                    halo = binary_dilation(droplet_mask, structure=se) \
                           & ~droplet_mask \
                           & ~np.isin(list(zip(*static_on)),
                                      list(zip(*static_on)))  # never halo static_on
                    # easier to build a mask array:
                    static_mask = np.zeros((R,C), bool)
                    for x,y in static_on:
                        static_mask[x,y] = True
                    halo = binary_dilation(droplet_mask, structure=se) \
                           & ~droplet_mask & ~static_mask
                    f2[halo] = 0
                frames.append(f2)

            # Down
            shape = set(init)
            for _ in range(steps_down):
                shape = step(shape, +1, 0)
                f2 = build(shape)
                if deactivated_offset >= 0:
                    droplet_mask = np.zeros((R, C), bool)
                    for x,y in shape:
                        droplet_mask[x,y] = True
                    static_mask = np.zeros((R,C), bool)
                    for x,y in static_on:
                        static_mask[x,y] = True
                    halo = binary_dilation(droplet_mask, structure=se) \
                           & ~droplet_mask & ~static_mask
                    f2[halo] = 0
                frames.append(f2)

            # Left
            shape = set(init)
            for _ in range(steps_left):
                shape = step(shape, 0, -1)
                f2 = build(shape)
                if deactivated_offset >= 0:
                    droplet_mask = np.zeros((R, C), bool)
                    for x,y in shape:
                        droplet_mask[x,y] = True
                    static_mask = np.zeros((R,C), bool)
                    for x,y in static_on:
                        static_mask[x,y] = True
                    halo = binary_dilation(droplet_mask, structure=se) \
                           & ~droplet_mask & ~static_mask
                    f2[halo] = 0
                frames.append(f2)

            # Right
            shape = set(init)
            for _ in range(steps_right):
                shape = step(shape, 0, +1)
                f2 = build(shape)
                if deactivated_offset >= 0:
                    droplet_mask = np.zeros((R, C), bool)
                    for x,y in shape:
                        droplet_mask[x,y] = True
                    static_mask = np.zeros((R,C), bool)
                    for x,y in static_on:
                        static_mask[x,y] = True
                    halo = binary_dilation(droplet_mask, structure=se) \
                           & ~droplet_mask & ~static_mask
                    f2[halo] = 0
                frames.append(f2)

        frames.append(build(set()))
        return frames

    def split_droplet(self,
              matrix: np.ndarray,
              corner: tuple[int, int],
              width: int,
              height: int,
              direction: str = 'horizontal',
              moving_half: str | None = None,
              gap: int = 2,
              debug: bool = False,
              out_dir: str = "debug_out",
              return_centers: bool = False,
              alternating: bool = False) -> list[np.ndarray] | tuple[list[np.ndarray], list[tuple[int, int]]]:
        """
        Splits a rectangular droplet into two parts and moves them apart.
        Preserves the initial matrix state except for the splitting droplet.

        arguments:
            matrix: the initial state of the electrode matrix
            corner: the upper left corner of the droplet
            width: the width of the droplet
            height: the height of the droplet
            direction: 'horizontal' or 'vertical'
            moving_half: 'top', 'bottom', 'left', 'right' or None. If None, both parts are moved.
            gap: the final number of steps of separation between the two halves
            debug: whether to show debug images
            out_dir: the directory to save debug images
            return_centers: whether to return the centers of the split halves
            alternating: whether to stagger movements instead of symmetrical split
        """
        rows, cols = matrix.shape
        tl_x, tl_y = corner
        br_x = tl_x + height - 1
        br_y = tl_y   

        full_shape = {
            (x, y)
            for x in range(tl_x, tl_x + height)
            for y in range(tl_y, tl_y + width)
            if 0 <= x < rows and 0 <= y < cols
        }

        if debug:
            debug_matrix = np.zeros_like(matrix)
            for x, y in full_shape:
                debug_matrix[x, y] = -1
            self.dump_debug_frame(f"{datetime.now().strftime('%H%M%S')}_initial_droplet_area", debug_matrix, out_dir, True)

        if direction == 'horizontal':
            mid = (tl_x + br_x) // 2
            top_half = {(x, y) for x, y in full_shape if x <= mid}
            bottom_half = full_shape - top_half
        elif direction == 'vertical':
            mid = (tl_y + br_y) // 2
            left_half = {(x, y) for x, y in full_shape if y <= mid}
            right_half = full_shape - left_half
        else:
            raise ValueError("Direction must be 'horizontal' or 'vertical'")

        ttag = datetime.now().strftime("%H%M%S")
        frames = []

        if alternating:
            top_offset, bot_offset = 0, 0
            left_offset, right_offset = 0, 0
            for i in range(gap * 2):
                f = matrix.copy()
                for x, y in full_shape:
                    f[x, y] = 0

                if direction == 'horizontal':
                    if i % 2 == 0:
                        top_offset += 1
                    else:
                        bot_offset += 1
                    top_moved = {(x - top_offset, y) for x, y in top_half if 0 <= x - top_offset < rows}
                    bot_moved = {(x + bot_offset, y) for x, y in bottom_half if 0 <= x + bot_offset < rows}
                    full = top_moved | bot_moved
                else:
                    if i % 2 == 0:
                        left_offset += 1
                    else:
                        right_offset += 1
                    left_moved = {(x, y - left_offset) for x, y in left_half if 0 <= y - left_offset < cols}
                    right_moved = {(x, y + right_offset) for x, y in right_half if 0 <= y + right_offset < cols}
                    full = left_moved | right_moved

                for x, y in full:
                    f[x, y] = 1
                frames.append(f)
                self.dump_debug_frame(f"{ttag}_split_{len(frames)}", f, out_dir, debug)
        else:
            for step in range(gap + 1):
                f = matrix.copy()
                for x, y in full_shape:
                    f[x, y] = 0

                if direction == 'horizontal':
                    top_moved = {(x - step, y) for x, y in top_half if 0 <= x - step < rows}
                    bot_moved = {(x + step, y) for x, y in bottom_half if 0 <= x + step < rows}
                    full = top_moved | bot_moved
                else:
                    left_moved = {(x, y - step) for x, y in left_half if 0 <= y - step < cols}
                    right_moved = {(x, y + step) for x, y in right_half if 0 <= y + step < cols}
                    full = left_moved | right_moved

                for x, y in full:
                    f[x, y] = 1
                frames.append(f)
                self.dump_debug_frame(f"{ttag}_split_{step}", f, out_dir, debug)

        if return_centers:
            def center_of_mass(cells):
                arr = np.array(list(cells))
                return tuple(np.round(np.mean(arr, axis=0)).astype(int))

            if direction == 'horizontal':
                return frames, [center_of_mass(top_half), center_of_mass(bottom_half)]
            else:
                return frames, [center_of_mass(left_half), center_of_mass(right_half)]

        return frames

    def clean_electrode(self, matrix: np.ndarray,
                                 wave_width: int = 2,
                                 spacing: int = 3,
                                 waves: int = 3,
                                 keep_initial: bool = False,
                                 debug: bool = False,
                                 out_dir: str = "debug_out") -> list[np.ndarray]:
        """
        Create N overlapping cleaning waves that sweep from furthest electrodes
        toward trash electrodes (value 2), starting each wave every `spacing` frames,
        each wave having a width of `wave_width`.
        """

        R, C = matrix.shape
        original_ones = set(zip(*np.where(matrix == 1))) if keep_initial else set()

        # 1. Compute distance from each cell to nearest trash cell
        trash_mask = (matrix == 2)
        distance_map = distance_transform_edt(~trash_mask)
        max_dist = int(np.max(distance_map))

        # 2. Map distances to coordinate sets
        distance_levels = {d: set(zip(*np.where(np.isclose(distance_map, d)))) for d in range(max_dist + 1)}

        # 3. Simulate frame-by-frame
        frames = []
        total_steps = max_dist + wave_width + spacing * (waves - 1)
        for t in range(total_steps):
            active = set()

            for wave_idx in range(waves):
                start_time = wave_idx * spacing
                age = t - start_time
                if age < 0:
                    continue  # This wave hasn't started yet

                for offset in range(wave_width):
                    dist = max_dist - (age - offset)
                    if 0 <= dist <= max_dist:
                        active |= distance_levels.get(dist, set())

            frame = np.zeros((R, C), int)
            for x, y in active | original_ones:
                frame[x, y] = 1
            frames.append(frame)

        # Debug images
        if debug:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            for idx, f in enumerate(frames):
                img = np.zeros((R, C, 3), np.uint8)
                img[matrix == -1] = (0, 0, 255)
                img[matrix == 2] = (0, 255, 0)
                img[f == 1] = (255, 255, 0)
                cv2.imwrite(os.path.join(out_dir, f"wave_multi_{idx:03}.png"),
                            cv2.resize(img, (512, 512), interpolation=cv2.INTER_NEAREST))

        return frames

    # ───────────────────────── cleanup & signal handling ────────────────────
    def close(self, *args):
        """Nothing special to clean up in the headless version."""
        pass

    def _signal_handler(self, sig, frame):
        print("\n[INFO] Caught interrupt signal. Exiting…")
        self.close()
        sys.exit(0)

    def __del__(self):
        self.close()