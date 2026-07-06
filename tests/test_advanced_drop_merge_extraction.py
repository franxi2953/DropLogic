import copy
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace

import numpy as np

from droplogic.mcp.runtime import DropLogicMCPRuntime
from droplogic.utils.advanced_drop import AdvancedDrop
from droplogic.utils.advanced_drop.common import (
    DropletPlan,
    create_droplet,
    get_droplet_positions,
)
from droplogic.utils.advanced_drop.merge import merge
from droplogic.utils.advanced_drop.splitting import reservoir_extraction
from droplogic.utils.advanced_drop.validation import (
    build_merge_product_shape,
    validate_droplet_target_layout,
    validate_merge_target_layout,
)


MATRIX = np.zeros((128, 128), dtype=np.int32)
SHAPE_2X2 = {(0, 0), (0, 1), (1, 0), (1, 1)}


def make_droplet(droplet_id, origin, shape=SHAPE_2X2, vital_space=2):
    return create_droplet(
        droplet_id,
        origin,
        origin,
        shape=shape,
        vital_space=vital_space,
    )


def make_plan(droplets, active_ids):
    frame = np.zeros_like(MATRIX)
    for droplet in droplets:
        if droplet.id not in active_ids:
            continue
        for row, col in get_droplet_positions(droplet, droplet.origin_corner):
            if 0 <= row < frame.shape[0] and 0 <= col < frame.shape[1]:
                frame[row, col] = 1

    return DropletPlan(
        frames=[frame],
        frame_count=1,
        droplet_trajectories={d.id: [d.origin_corner] for d in droplets},
        active_droplets_per_frame=[list(active_ids)],
        events=[],
        planning_success=True,
        conflicts_resolved=[],
        targets_reached={},
        event_id_per_frame=[],
    )


class MergeRegressionTests(unittest.TestCase):
    def make_run_droplets(self):
        reservoir_shape = {(row, col) for row in range(6) for col in range(6)}
        return [
            make_droplet(100, (43, 129), reservoir_shape, 1),
            make_droplet(102, (60, 50)),
            make_droplet(103, (51, 34)),
            make_droplet(104, (43, 38)),
            make_droplet(201, (43, 30), {(0, 0), (0, 1)}),
            make_droplet(202, (43, 31), {(0, 0), (0, 1)}),
        ]

    def test_merge_routes_joiner_missing_from_active_frame(self):
        droplets = self.make_run_droplets()
        plan = make_plan(droplets, active_ids=[100, 102, 104, 201, 202])

        updated, new_plan = merge(
            droplets,
            MATRIX,
            [102, 103],
            (55, 40),
            existing_plan=plan,
        )

        self.assertEqual(new_plan.targets_reached, {102: True, 103: True})
        self.assertIn(203, {droplet.id for droplet in updated})
        self.assertEqual(new_plan.droplet_trajectories[102][-1], (55, 40))
        self.assertEqual(new_plan.droplet_trajectories[103][-1], (55, 40))
        self.assertEqual(new_plan.droplet_trajectories[203][-1], (55, 40))
        self.assertEqual(
            len(new_plan.droplet_trajectories[103]),
            new_plan.frame_count,
        )
        self.assertNotIn(102, new_plan.active_droplets_per_frame[-1])
        self.assertNotIn(103, new_plan.active_droplets_per_frame[-1])
        self.assertIn(203, new_plan.active_droplets_per_frame[-1])

    def test_merge_succeeds_when_target_is_current_joiner_position(self):
        droplets = self.make_run_droplets()
        plan = make_plan(droplets, active_ids=[100, 102, 104, 201, 202])

        updated, new_plan = merge(
            droplets,
            MATRIX,
            [102, 103],
            (60, 50),
            existing_plan=plan,
        )

        self.assertEqual(new_plan.targets_reached, {102: True, 103: True})
        self.assertIn(203, {droplet.id for droplet in updated})
        for trajectory in new_plan.droplet_trajectories.values():
            self.assertEqual(len(trajectory), new_plan.frame_count)

    def test_core_merge_validation_suggests_staging_blocker(self):
        droplets = [
            make_droplet(3, (46, 12)),
            make_droplet(4, (42, 18)),
            make_droplet(5, (40, 24)),
            make_droplet(6, (40, 9), {(0, 0), (0, 1)}),
            make_droplet(7, (40, 16), {(0, 0), (0, 1)}),
        ]

        validation = validate_merge_target_layout(
            droplets,
            [3, 4],
            (48, 18),
            active_droplet_ids=[3, 4, 5, 6, 7],
            matrix_shape=[128, 128],
        )

        self.assertFalse(validation["ok"])
        self.assertEqual(validation["reason"], "stage_blockers_before_merge")
        self.assertIn("7", validation["blocker_parking_suggestions"])

    def test_core_merge_validation_does_not_suggest_alternate_for_open_hub(self):
        droplets = [
            make_droplet(1, (10, 10)),
            make_droplet(2, (20, 20)),
        ]

        validation = validate_merge_target_layout(
            droplets,
            [1, 2],
            (50, 50),
            active_droplet_ids=[1, 2],
            matrix_shape=[128, 128],
        )

        self.assertTrue(validation["ok"])
        self.assertNotIn("suggested_target", validation)

    def test_core_merge_validation_uses_new_product_default_vital_space(self):
        droplets = [
            make_droplet(1, (0, 0), {(0, 0)}, vital_space=2),
            make_droplet(9, (12, 10), {(0, 0)}, vital_space=1),
        ]

        validation = validate_merge_target_layout(
            droplets,
            [1],
            (10, 10),
            active_droplet_ids=[1, 9],
            matrix_shape=[128, 128],
        )

        self.assertTrue(validation["ok"])
        self.assertEqual(validation["merged_vital_space"], 1)

    def test_core_merge_validation_uses_forced_row_major_footprint(self):
        droplets = [
            make_droplet(1, (0, 0), {(0, 0), (0, 1)}),
            make_droplet(2, (5, 5), {(0, 0), (0, 1), (1, 0)}),
            make_droplet(9, (10, 10), {(0, 0)}),
        ]

        self.assertEqual(
            build_merge_product_shape(5, forced_width=3, forced_height=3),
            {(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)},
        )

        validation = validate_merge_target_layout(
            droplets,
            [1, 2],
            (10, 10),
            active_droplet_ids=[1, 2, 9],
            matrix_shape=[128, 128],
            forced_width=3,
            forced_height=3,
        )

        overlap_issues = [
            issue
            for issue in validation["blocking_issues"]
            if issue["type"] == "merge_target_footprint_overlap"
        ]
        self.assertFalse(validation["ok"])
        self.assertEqual(overlap_issues[0]["cells"], [[10, 10]])


class LinearExtractionRegressionTests(unittest.TestCase):
    def make_reservoir_case(self):
        reservoir_shape = {(row, col) for row in range(6) for col in range(8)}
        reservoir = make_droplet(100, (43, 30), reservoir_shape, 1)
        droplets = [reservoir]
        return droplets, make_plan(droplets, active_ids=[100])

    def test_linear_extraction_rejects_droplets_outside_reservoir_sweep_strip(self):
        droplets, plan = self.make_reservoir_case()

        with self.assertRaisesRegex(ValueError, "outside the reservoir sweep strip"):
            reservoir_extraction(
                droplets,
                MATRIX,
                100,
                "linear",
                existing_plan=plan,
                linear_direction=(0, 1),
                linear_drop_shape=(2, 2),
                linear_drops_number=4,
                linear_offset=8,
                linear_space_per_col=4,
                linear_space_per_row=4,
                linear_vital_space=2,
            )

    def test_linear_extraction_allows_droplets_reached_later_by_sweep(self):
        reservoir_shape = {(row, col) for row in range(10) for col in range(12)}
        reservoir = make_droplet(100, (69, 6), reservoir_shape, 1)
        droplets = [reservoir]
        plan = make_plan(droplets, active_ids=[100])
        initial_reservoir_positions = {
            (69 + row, 6 + col)
            for row, col in reservoir_shape
        }

        updated, new_plan = reservoir_extraction(
            droplets,
            MATRIX,
            100,
            "linear",
            existing_plan=plan,
            linear_direction=(0, 1),
            linear_drop_shape=(2, 2),
            linear_drops_number=5,
            linear_offset=2,
            linear_space_per_col=4,
            linear_space_per_row=4,
            linear_vital_space=2,
        )

        late_droplet = next(droplet for droplet in updated if droplet.origin_corner == (69, 18))
        late_positions = get_droplet_positions(late_droplet, late_droplet.origin_corner)

        self.assertFalse(late_positions.issubset(initial_reservoir_positions))
        self.assertIn(late_droplet.id, new_plan.active_droplets_per_frame[-1])
        self.assertTrue(
            any(late_droplet.id in active_ids for active_ids in new_plan.active_droplets_per_frame),
        )

    def test_linear_extraction_activates_every_created_droplet(self):
        droplets, plan = self.make_reservoir_case()

        updated, new_plan = reservoir_extraction(
            droplets,
            MATRIX,
            100,
            "linear",
            existing_plan=plan,
            linear_direction=(0, 1),
            linear_drop_shape=(2, 2),
            linear_drops_number=4,
            linear_offset=0,
            linear_space_per_col=4,
            linear_space_per_row=4,
            linear_vital_space=2,
        )

        self.assertEqual({droplet.id for droplet in updated}, {100, 101, 102, 103, 104})
        self.assertTrue({100, 101, 102, 103, 104}.issubset(new_plan.active_droplets_per_frame[-1]))

    def test_linear_extraction_post_separation_moves_reservoir_extra_steps(self):
        droplets_without_extra, plan_without_extra = self.make_reservoir_case()
        updated_without_extra, plan_without_extra = reservoir_extraction(
            droplets_without_extra,
            MATRIX,
            100,
            "linear",
            existing_plan=plan_without_extra,
            linear_direction=(0, 1),
            linear_drop_shape=(2, 2),
            linear_drops_number=4,
            linear_offset=0,
            linear_space_per_col=4,
            linear_space_per_row=4,
            linear_vital_space=2,
            linear_post_separation_steps=0,
        )

        droplets_with_extra, plan_with_extra = self.make_reservoir_case()
        updated_with_extra, plan_with_extra = reservoir_extraction(
            droplets_with_extra,
            MATRIX,
            100,
            "linear",
            existing_plan=plan_with_extra,
            linear_direction=(0, 1),
            linear_drop_shape=(2, 2),
            linear_drops_number=4,
            linear_offset=0,
            linear_space_per_col=4,
            linear_space_per_row=4,
            linear_vital_space=2,
            linear_post_separation_steps=3,
        )

        reservoir_without_extra = next(d for d in updated_without_extra if d.id == 100)
        reservoir_with_extra = next(d for d in updated_with_extra if d.id == 100)

        self.assertEqual(plan_with_extra.frame_count, plan_without_extra.frame_count + 3)
        self.assertEqual(
            reservoir_with_extra.origin_corner,
            (reservoir_without_extra.origin_corner[0], reservoir_without_extra.origin_corner[1] + 3),
        )


class RuntimeRollbackRegressionTests(unittest.TestCase):
    class FakeDroplets(list):
        def update_droplet_target(self, droplet_id, target):
            for droplet in self:
                if droplet.id == droplet_id:
                    droplet.target_corner = tuple(target)
                    return True
            return False

        def get_droplets_summary(self):
            active_ids = set()
            plan = getattr(self.parent, "plan", None)
            if plan is not None and plan.active_droplets_per_frame:
                active_ids = set(plan.active_droplets_per_frame[-1])
            return {
                "total_droplets": len(self),
                "active_droplet_ids": sorted(active_ids),
                "droplets": [
                    {
                        "id": droplet.id,
                        "active": droplet.id in active_ids,
                        "current_position": droplet.origin_corner,
                        "target_position": droplet.target_corner,
                        "at_target": droplet.origin_corner == droplet.target_corner,
                        "shape_size": len(droplet.shape),
                        "vital_space": droplet.vital_space,
                    }
                    for droplet in self
                ],
                "has_plan": plan is not None,
            }

    class FakeAdvancedDrop:
        def __init__(self, droplets):
            self.plan = make_plan(droplets, active_ids=[droplet.id for droplet in droplets])
            self.droplets = RuntimeRollbackRegressionTests.FakeDroplets(droplets)
            self.droplets.parent = self

    def make_runtime_with_droplets(self, droplets):
        runtime = DropLogicMCPRuntime()
        advanced_drop = self.FakeAdvancedDrop(droplets)
        runtime.system = SimpleNamespace(
            advanced_drop=advanced_drop,
            state={"electrode_matrix": {"rows": 128, "columns": 128}},
        )
        return runtime, advanced_drop

    def test_primitive_exception_restores_plan_and_droplets(self):
        class FakeDroplets(list):
            def get_droplets_summary(self):
                return {"droplets": [{"id": d.id} for d in self], "total_droplets": len(self)}

        class FakeAdvancedDrop:
            def __init__(self):
                self.plan = {"marker": "original"}
                self.droplets = FakeDroplets([SimpleNamespace(id=1, value="original")])

            def reservoir_extraction(self):
                self.plan = {"marker": "mutated"}
                self.droplets.append(SimpleNamespace(id=2, value="partial"))
                raise RuntimeError("boom")

        runtime = DropLogicMCPRuntime()
        advanced_drop = FakeAdvancedDrop()
        runtime.system = SimpleNamespace(advanced_drop=advanced_drop)

        original_plan = copy.deepcopy(advanced_drop.plan)
        original_droplets = copy.deepcopy(list(advanced_drop.droplets))

        with self.assertRaises(RuntimeError):
            runtime._execute_advanced_drop_call("reservoir_extraction", {})

        self.assertEqual(advanced_drop.plan, original_plan)
        self.assertEqual(
            [(d.id, d.value) for d in advanced_drop.droplets],
            [(d.id, d.value) for d in original_droplets],
        )

    def test_trim_plan_tail_runtime_delegates_to_advanced_drop(self):
        class FakeAdvancedDrop:
            def __init__(self):
                self.plan = make_plan([make_droplet(1, (10, 10))], active_ids=[1])
                self.called_with = None

            def trim_plan_tail(self, keep_frames):
                self.called_with = keep_frames
                return {
                    "ok": True,
                    "trimmed": False,
                    "keep_frames": len(self.plan.frames),
                    "removed_frames": 0,
                    "protected_frames": 1,
                    "plan": self.plan,
                    "executor_status": {
                        "is_executing": False,
                        "current_frame": 0,
                        "total_frames": len(self.plan.frames),
                    },
                }

        runtime = DropLogicMCPRuntime()
        advanced_drop = FakeAdvancedDrop()
        runtime.system = SimpleNamespace(advanced_drop=advanced_drop)

        result = runtime.trim_plan_tail(1)

        self.assertEqual(advanced_drop.called_with, 1)
        self.assertTrue(result["ok"])
        self.assertFalse(result["trimmed"])
        self.assertEqual(result["plan"]["frame_count"], 1)

    def test_clear_droplet_state_resets_plan_droplets_and_executor_cursor(self):
        class FakeExecutionState:
            def __init__(self, current_frame=0, total_frames=0):
                self.is_executing = False
                self.current_frame = current_frame
                self.total_frames = total_frames
                self.frames_executed = current_frame
                self.execution_time = 0.0
                self.last_update = 123.0

        class FakeExecutor:
            def __init__(self, plan):
                self.execution_lock = threading.RLock()
                self.state = FakeExecutionState(current_frame=9, total_frames=9)
                self.current_plan = plan
                self.breakpoints = {8}
                self.breakpoint_reached = threading.Event()
                self.breakpoint_reached.set()
                self.stop_event = threading.Event()
                self.stop_event.set()
                self.frame_history = [{"index": 8}]
                self.last_frame_index = 8
                self.last_frame_started_at = 1.0
                self.last_frame_finished_at = 2.0
                self.last_frame_duration_seconds = 1.0
                self.last_frame_error = {"message": "old"}
                self.last_matrix_queue_wait = {"ok": False}
                self.last_applied_frame_index = 8
                self.last_applied_frame_matrix = np.ones((2, 2), dtype=int)
                self.last_applied_frame_plan = plan
                self.last_applied_frame_plan_id = id(plan)
                self.last_applied_frame_plan_frame_count = len(plan.frames)
                self.last_applied_frame_active_droplet_ids = [1]
                self.last_applied_frame_droplets = [make_droplet(1, (10, 10))]
                self.last_applied_frame_at = 3.0

            def stop(self):
                self.state.is_executing = False

            def clear_breakpoints(self):
                self.breakpoints.clear()

            def _clear_last_applied_frame(self):
                self.last_applied_frame_index = None
                self.last_applied_frame_matrix = None
                self.last_applied_frame_plan = None
                self.last_applied_frame_plan_id = None
                self.last_applied_frame_plan_frame_count = None
                self.last_applied_frame_active_droplet_ids = []
                self.last_applied_frame_droplets = []
                self.last_applied_frame_at = None

            def status(self):
                return {
                    "is_executing": self.state.is_executing,
                    "current_frame": self.state.current_frame,
                    "total_frames": self.state.total_frames,
                    "frames_executed": self.state.frames_executed,
                    "breakpoints": sorted(self.breakpoints),
                    "breakpoint_reached": self.breakpoint_reached.is_set(),
                    "last_applied_frame": {
                        "index": self.last_applied_frame_index,
                        "plan_frame_count": self.last_applied_frame_plan_frame_count,
                        "active_droplet_ids": list(self.last_applied_frame_active_droplet_ids),
                    },
                }

        class FakeDroplets(list):
            def get_droplets_summary(self):
                return {
                    "total_droplets": len(self),
                    "active_droplet_ids": [],
                    "droplets": [{"id": droplet.id} for droplet in self],
                    "has_plan": True,
                }

        class FakeAdvancedDrop:
            def __init__(self):
                self.plan = make_plan([make_droplet(1, (10, 10))], active_ids=[1])
                self.droplets = FakeDroplets([make_droplet(1, (10, 10))])
                self.executor = FakeExecutor(self.plan)

            def clear(self):
                self.droplets = FakeDroplets()
                self.plan = DropletPlan(
                    frames=[],
                    frame_count=0,
                    droplet_trajectories={},
                    active_droplets_per_frame=[],
                    events=[],
                    planning_success=True,
                    conflicts_resolved=[],
                    targets_reached={},
                    event_id_per_frame=[],
                )

        runtime = DropLogicMCPRuntime()
        advanced_drop = FakeAdvancedDrop()
        runtime.system = SimpleNamespace(advanced_drop=advanced_drop)

        result = runtime.clear_droplet_state()

        self.assertTrue(result["ok"])
        self.assertEqual(result["droplets"]["total_droplets"], 0)
        self.assertEqual(result["plan"]["frame_count"], 0)
        self.assertEqual(result["executor_status_after"]["current_frame"], 0)
        self.assertEqual(result["executor_status_after"]["total_frames"], 0)
        self.assertEqual(result["executor_status_after"]["breakpoints"], [])
        self.assertFalse(result["executor_status_after"]["breakpoint_reached"])
        self.assertIs(advanced_drop.executor.current_plan, advanced_drop.plan)
        self.assertEqual(advanced_drop.executor.frame_history, [])
        self.assertIsNone(advanced_drop.executor.last_frame_error)
        self.assertIsNone(advanced_drop.executor.last_applied_frame_index)

    def test_update_droplet_targets_rejects_new_final_vital_conflict(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (20, 20))
        runtime, _ = self.make_runtime_with_droplets([droplet_1, droplet_2])

        result = runtime.update_droplet_targets(
            [{"id": 1, "target": [17, 20]}],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["updated_count"], 0)
        self.assertFalse(result["target_validation"]["ok"])
        self.assertEqual(droplet_1.target_corner, (10, 10))
        self.assertEqual(
            result["target_validation"]["blocking_issues"][0]["type"],
            "vital_space_conflict",
        )

    def test_update_droplet_targets_accepts_valid_final_layout(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (20, 20))
        runtime, _ = self.make_runtime_with_droplets([droplet_1, droplet_2])

        result = runtime.update_droplet_targets(
            [{"id": 1, "target": [10, 30]}],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["updated_count"], 1)
        self.assertTrue(result["target_validation"]["ok"])
        self.assertEqual(droplet_1.target_corner, (10, 30))

    def test_core_target_validation_suggests_nearest_available_target(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (20, 20))

        validation = validate_droplet_target_layout(
            [droplet_1, droplet_2],
            {1: (20, 20)},
            matrix_shape=[128, 128],
        )

        self.assertFalse(validation["ok"])
        suggestion = validation["suggested_targets"].get("1")
        self.assertIsNotNone(suggestion)
        self.assertIsNotNone(suggestion["target"])
        self.assertNotEqual(suggestion["target"], (20, 20))

    def test_advanced_drop_exposes_target_validation_api(self):
        class Logger:
            def warning(self, *_args, **_kwargs):
                pass

            def info(self, *_args, **_kwargs):
                pass

            def debug(self, *_args, **_kwargs):
                pass

            def error(self, *_args, **_kwargs):
                pass

        system = SimpleNamespace(
            state={"electrode_matrix": {"matrix": MATRIX.copy()}},
            logger=Logger(),
        )
        advanced_drop = AdvancedDrop(system)
        droplet_1 = advanced_drop.droplets.create_droplet(
            1,
            (10, 10),
            (10, 10),
            shape=SHAPE_2X2,
            vital_space=2,
        )
        advanced_drop.droplets.create_droplet(
            2,
            (20, 20),
            (20, 20),
            shape=SHAPE_2X2,
            vital_space=2,
        )

        validation = advanced_drop.validate_droplet_target_layout({1: (20, 20)})

        self.assertFalse(validation["ok"])
        self.assertIn("1", validation["suggested_targets"])
        self.assertEqual(droplet_1.target_corner, (10, 10))

    def test_background_plan_move_rejects_oversized_real_hardware_batch(self):
        droplets = [make_droplet(i, (10 + i, 10)) for i in range(1, 12)]
        for droplet in droplets:
            droplet.target_corner = (droplet.origin_corner[0], 80)
        runtime, advanced_drop = self.make_runtime_with_droplets(droplets)
        runtime.system_name = "boxmini"
        advanced_drop.move_called = False

        def move(**_kwargs):
            advanced_drop.move_called = True

        advanced_drop.move = move

        with self.assertRaisesRegex(RuntimeError, "too many moving droplets"):
            runtime.plan_move(background=True)

        self.assertFalse(advanced_drop.move_called)

    def test_hardware_batch_guard_counts_only_active_moving_droplets(self):
        droplets = [make_droplet(i, (10 + i, 10)) for i in range(1, 12)]
        for droplet in droplets:
            droplet.target_corner = (droplet.origin_corner[0], 80)
        runtime, advanced_drop = self.make_runtime_with_droplets(droplets)
        runtime.system_name = "boxmini"
        advanced_drop.plan = make_plan(droplets, active_ids=[1, 2, 3, 4, 5])

        self.assertEqual(runtime._advanced_drop_active_move_count(), 5)
        runtime._guard_hardware_plan_move_batch(background=True)

    def test_update_droplet_targets_rejects_target_in_current_reserved_space(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (20, 20))
        runtime, _ = self.make_runtime_with_droplets([droplet_1, droplet_2])

        result = runtime.update_droplet_targets(
            [
                {"id": 1, "target": [20, 20]},
                {"id": 2, "target": [30, 30]},
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(droplet_1.target_corner, (10, 10))
        self.assertEqual(droplet_2.target_corner, (20, 20))
        issue_types = {
            issue["type"]
            for issue in result["target_validation"]["blocking_issues"]
        }
        self.assertIn("target_uses_current_reserved_space", issue_types)

    def test_update_droplet_targets_suggests_nearest_available_target(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (20, 20))
        runtime, _ = self.make_runtime_with_droplets([droplet_1, droplet_2])

        result = runtime.update_droplet_targets(
            [{"id": 1, "target": [20, 20]}],
        )

        self.assertFalse(result["ok"])
        suggestion = result["target_validation"]["suggested_targets"].get("1")
        self.assertIsNotNone(suggestion)
        self.assertIsNotNone(suggestion["target"])
        self.assertNotEqual(suggestion["target"], [20, 20])

        retry = runtime.update_droplet_targets(
            [{"id": 1, "target": suggestion["target"]}],
        )

        self.assertTrue(retry["ok"])
        self.assertEqual(droplet_1.target_corner, tuple(suggestion["target"]))

    def test_update_droplet_targets_suggestion_respects_batch_targets(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (40, 40))
        runtime, advanced_drop = self.make_runtime_with_droplets([droplet_1, droplet_2])

        result = runtime.update_droplet_targets(
            [
                {"id": 1, "target": [30, 30]},
                {"id": 2, "target": [30, 30]},
            ],
        )

        self.assertFalse(result["ok"])
        suggestions = result["target_validation"]["suggested_targets"]
        self.assertTrue(suggestions)

        adjusted_targets = {
            1: tuple(suggestions.get("1", {}).get("target") or (30, 30)),
            2: tuple(suggestions.get("2", {}).get("target") or (30, 30)),
        }
        validation = runtime._validate_droplet_target_layout(
            advanced_drop,
            adjusted_targets,
        )

        self.assertTrue(validation["ok"])

    def test_update_droplet_targets_warns_about_pending_targets_not_in_request(self):
        droplet_1 = make_droplet(1, (10, 10))
        droplet_2 = make_droplet(2, (20, 20))
        droplet_2.target_corner = (30, 30)
        runtime, _ = self.make_runtime_with_droplets([droplet_1, droplet_2])

        result = runtime.update_droplet_targets(
            [{"id": 1, "target": [10, 30]}],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["target_validation"]["pending_target_ids_not_in_request"],
            [2],
        )
        warning_types = {
            warning["type"]
            for warning in result["target_validation"]["warnings"]
        }
        self.assertIn("pending_targets_not_in_request", warning_types)

    def test_failed_plan_merge_returns_blocker_parking_diagnostics(self):
        droplets = [
            make_droplet(3, (46, 12)),
            make_droplet(4, (42, 18)),
            make_droplet(5, (40, 24)),
            make_droplet(6, (40, 9), shape={(0, 0), (0, 1)}),
            make_droplet(7, (40, 16), shape={(0, 0), (0, 1)}),
        ]
        runtime, advanced_drop = self.make_runtime_with_droplets(droplets)

        def failed_merge(**_kwargs):
            return None

        advanced_drop.merge = failed_merge

        result = runtime.plan_merge(
            droplet_ids=[3, 4],
            target=[48, 18],
            event_id="merge_blocks_3_4_to_product",
        )

        self.assertFalse(result["ok"])
        validation = result["primitive_validation"]["merge_target_validation"]
        self.assertFalse(validation["ok"])
        issue_types = {
            issue["type"]
            for issue in validation["blocking_issues"]
        }
        self.assertIn("merge_joiner_starts_in_blocker_vital_space", issue_types)
        self.assertIn("7", validation["blocker_parking_suggestions"])
        self.assertIn("recommended_action", result["primitive_validation"])


class DeleteDropletRegressionTests(unittest.TestCase):
    def make_delete_case(self):
        class Logger:
            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

        class Parent:
            pass

        parent = Parent()
        parent.plan = make_plan(
            [
                make_droplet(1, (10, 10)),
                make_droplet(2, (20, 20)),
            ],
            active_ids=[1, 2],
        )

        from droplogic.utils.advanced_drop.common import DropletList

        droplets = DropletList(SimpleNamespace(logger=Logger()), parent)
        droplets.extend(
            [
                make_droplet(1, (10, 10)),
                make_droplet(2, (20, 20)),
            ]
        )
        return droplets, parent

    def test_delete_droplet_clears_electrodes_when_not_persisting(self):
        droplets, parent = self.make_delete_case()

        self.assertTrue(droplets.delete_droplet(1, persist_electrodes=False))

        self.assertEqual([2], parent.plan.active_droplets_per_frame[-1])
        for row, col in get_droplet_positions(make_droplet(1, (10, 10)), (10, 10)):
            self.assertEqual(parent.plan.frames[-1][row, col], 0)
        for row, col in get_droplet_positions(make_droplet(2, (20, 20)), (20, 20)):
            self.assertEqual(parent.plan.frames[-1][row, col], 1)

    def test_delete_droplet_can_persist_electrodes_explicitly(self):
        droplets, parent = self.make_delete_case()

        self.assertTrue(droplets.delete_droplet(1, persist_electrodes=True))

        self.assertEqual([2], parent.plan.active_droplets_per_frame[-1])
        for row, col in get_droplet_positions(make_droplet(1, (10, 10)), (10, 10)):
            self.assertEqual(parent.plan.frames[-1][row, col], 1)


class AdvancedDropPlanEditingRegressionTests(unittest.TestCase):
    class FakeExecutor:
        def __init__(self, plan, current_frame=0, last_applied_frame_index=None):
            self.execution_lock = threading.RLock()
            self.current_plan = plan
            self.state = SimpleNamespace(
                is_executing=False,
                current_frame=current_frame,
                total_frames=len(plan.frames),
                frames_executed=current_frame,
            )
            self.breakpoints = {2, 4}
            self.last_applied_frame_index = last_applied_frame_index

        def status(self):
            return {
                "is_executing": self.state.is_executing,
                "current_frame": self.state.current_frame,
                "total_frames": self.state.total_frames,
                "frames_executed": self.state.frames_executed,
                "breakpoints": sorted(self.breakpoints),
                "last_applied_frame": {
                    "index": self.last_applied_frame_index,
                    "plan_frame_count": len(self.current_plan.frames),
                    "active_droplet_ids": [1],
                },
            }

    def make_editing_case(self):
        droplet = make_droplet(1, (10, 10))
        plan = make_plan([droplet], active_ids=[1])
        for offset in range(1, 5):
            position = (10 + offset, 10)
            frame = np.zeros_like(MATRIX)
            for row, col in get_droplet_positions(droplet, position):
                frame[row, col] = 1
            plan.frames.append(frame)
            plan.active_droplets_per_frame.append([1])
            plan.event_id_per_frame.append(7 if offset < 4 else 8)
            plan.droplet_trajectories[1].append(position)
        plan.frame_count = len(plan.frames)
        plan.events = [
            (1, "move", {"event_id": 7, "frame_span": (1, 4)}),
            (4, "future", {"event_id": 8, "frame_span": (4, 4)}),
        ]
        plan.conflicts_resolved = [{"frame": 2}, {"frame": 4}]

        advanced_drop = AdvancedDrop.__new__(AdvancedDrop)
        advanced_drop.plan = plan
        advanced_drop.droplets = [droplet]
        advanced_drop.executor = self.FakeExecutor(
            plan,
            current_frame=2,
            last_applied_frame_index=1,
        )
        return advanced_drop, droplet

    def test_trim_plan_tail_lives_on_advanced_drop_and_syncs_executor(self):
        advanced_drop, droplet = self.make_editing_case()

        result = advanced_drop.trim_plan_tail(3)

        self.assertTrue(result["trimmed"])
        self.assertEqual(result["removed_frames"], 2)
        self.assertEqual(advanced_drop.plan.frame_count, 3)
        self.assertEqual(len(advanced_drop.plan.frames), 3)
        self.assertEqual(advanced_drop.plan.droplet_trajectories[1][-1], (12, 10))
        self.assertEqual(droplet.origin_corner, (12, 10))
        self.assertEqual(droplet.target_corner, (12, 10))
        self.assertEqual(advanced_drop.plan.events, [(1, "move", {"event_id": 7, "frame_span": (1, 2)})])
        self.assertEqual(advanced_drop.plan.conflicts_resolved, [{"frame": 2}])
        self.assertEqual(advanced_drop.executor.current_plan, advanced_drop.plan)
        self.assertEqual(advanced_drop.executor.state.total_frames, 3)
        self.assertEqual(advanced_drop.executor.breakpoints, {2})

    def test_trim_plan_tail_refuses_to_delete_applied_frames(self):
        advanced_drop, _ = self.make_editing_case()

        with self.assertRaisesRegex(RuntimeError, "already executed/applied"):
            advanced_drop.trim_plan_tail(1)


class ExecutionSceneFrameSnapshotRegressionTests(unittest.TestCase):
    class FakeExecutor:
        def __init__(self, plan, frame_matrix, droplets_snapshot):
            self.current_plan = plan
            self.last_applied_frame_plan = plan
            self.last_applied_frame_matrix = frame_matrix
            self.last_applied_frame_droplets = droplets_snapshot

        def status(self):
            return {
                "is_executing": True,
                "current_frame": 1,
                "total_frames": 2,
                "frames_executed": 1,
                "frame_delay": 1.0,
                "breakpoints": [],
                "breakpoint_reached": False,
                "last_applied_frame": {
                    "index": 0,
                    "plan_id": id(self.current_plan),
                    "plan_frame_count": len(self.current_plan.frames),
                    "active_droplet_ids": [1],
                },
            }

    def test_execution_scene_keeps_last_applied_droplet_snapshot_until_next_frame(self):
        droplet = make_droplet(1, (10, 10))
        plan = make_plan([droplet], active_ids=[1])
        next_frame = np.zeros_like(plan.frames[0])
        plan.frames.append(next_frame)
        plan.active_droplets_per_frame.append([])
        plan.event_id_per_frame.append(2)
        plan.droplet_trajectories[1].append((10, 10))
        plan.events = [
            (0, "init", {"event_id": 1, "frame_span": (0, 0)}),
            (1, "delete", {"event_id": 2, "frame_span": (1, 1), "droplet_id": 1}),
        ]
        plan.frame_count = len(plan.frames)

        runtime = DropLogicMCPRuntime()
        runtime.system = SimpleNamespace(
            advanced_drop=SimpleNamespace(
                plan=plan,
                droplets=[],
                executor=self.FakeExecutor(
                    plan=plan,
                    frame_matrix=plan.frames[0].copy(),
                    droplets_snapshot=[copy.deepcopy(droplet)],
                ),
            ),
            state={
                "electrode_matrix": {
                    "rows": 128,
                    "columns": 128,
                    "matrix": next_frame.copy(),
                }
            },
        )

        scene = runtime.execution_scene(include_paths=False)

        self.assertTrue(scene["available"])
        self.assertEqual(scene["frame"]["source"], "executor_last_applied_frame")
        self.assertEqual(scene["frame"]["index"], 0)
        self.assertEqual([droplet["id"] for droplet in scene["droplets"]], [1])
        self.assertEqual(scene["droplets"][0]["position"], [10, 10])
        self.assertEqual(scene["droplets"][0]["bbox"]["row_min"], 10)
        self.assertEqual(scene["droplets"][0]["bbox"]["col_min"], 10)


class MeltingCurveCaptureRuntimeTests(unittest.TestCase):
    def test_temperature_hold_fails_if_target_rolls_back_before_waiting(self):
        runtime = DropLogicMCPRuntime()

        class FakeTemperatureSystem:
            def __init__(self):
                self.state = {"temperature": {"target": 32.0}}

            def update_state(self, path, value):
                self.state["temperature"]["target"] = value
                return {"success": True, "key": path, "actual_value": value}

        system = FakeTemperatureSystem()
        runtime.system = system

        def fake_queue_wait(**_kwargs):
            system.state["temperature"]["target"] = 32.0
            return {"ok": True, "pending_commands": 0}

        runtime._wait_for_hardware_queue_empty = fake_queue_wait

        result = runtime._temperature_hold_impl(
            target_c=33.0,
            hold_seconds=0,
            tolerance_c=0.5,
            settle_timeout_seconds=0,
            sample_interval_seconds=0.1,
            require_settle=False,
            max_samples=5,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "temperature target reverted before hold")
        self.assertEqual(result["confirmed_target_c"], 32.0)
        self.assertEqual(result["samples"], [])

    def test_temperature_hold_fails_if_target_changes_during_wait(self):
        runtime = DropLogicMCPRuntime()

        class FakeTemperatureSystem:
            def __init__(self):
                self.state = {"temperature": {"target": 32.0}}

            def update_state(self, path, value):
                self.state["temperature"]["target"] = value
                return {"success": True, "key": path, "actual_value": value}

        system = FakeTemperatureSystem()
        runtime.system = system
        runtime._wait_for_hardware_queue_empty = lambda **_kwargs: {
            "ok": True,
            "pending_commands": 0,
        }

        def fake_temperature_read():
            system.state["temperature"]["target"] = 32.0
            return 32.1

        runtime._read_temperature_value = fake_temperature_read

        result = runtime._temperature_hold_impl(
            target_c=33.0,
            hold_seconds=1,
            tolerance_c=0.5,
            settle_timeout_seconds=60,
            sample_interval_seconds=0.1,
            require_settle=True,
            max_samples=5,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "temperature target changed during hold")
        self.assertEqual(result["confirmed_target_c"], 32.0)
        self.assertEqual(result["samples"][-1]["temperature_c"], 32.1)

    def test_temperature_reads_use_system_temperature_lock(self):
        runtime = DropLogicMCPRuntime()

        class RecordingLock:
            def __init__(self):
                self.entered = False
                self.used = False

            def __enter__(self):
                self.entered = True
                self.used = True

            def __exit__(self, exc_type, exc, tb):
                self.entered = False

        class LockedTemperature:
            def __init__(self, lock):
                self.lock = lock

            def get_temperature(self):
                if not self.lock.entered:
                    raise AssertionError("temperature lock was not held")
                return 31.5

        lock = RecordingLock()
        runtime.system = SimpleNamespace(
            temperature=LockedTemperature(lock),
            _temperature_lock=lock,
        )

        self.assertEqual(runtime._read_temperature_value(), 31.5)
        self.assertTrue(lock.used)

    def test_melting_curve_capture_takes_image_after_every_temperature_step(self):
        runtime = DropLogicMCPRuntime()
        runtime.system = SimpleNamespace(
            advanced_drop=SimpleNamespace(
                droplets=[SimpleNamespace(id=11), SimpleNamespace(id=12)]
            )
        )
        runtime._normalize_imaging_channels = lambda channels: [
            {"channel": str(channel), "exposure_time": 1}
            for channel in channels
        ]

        hold_targets = []
        hold_tolerances = []
        capture_calls = []

        def fake_hold(**kwargs):
            target = float(kwargs["target_c"])
            hold_targets.append(target)
            hold_tolerances.append(float(kwargs["tolerance_c"]))
            status_callback = kwargs.get("status_callback")
            if status_callback:
                status_callback(
                    {
                        "elapsed_seconds": 0.0,
                        "temperature_c": target,
                        "within_tolerance": True,
                    }
                )
            return {
                "ok": True,
                "target_c": target,
                "hold_seconds": kwargs["hold_seconds"],
                "settled": True,
                "tolerance_c": kwargs["tolerance_c"],
                "final_temperature_c": target,
                "samples": [
                    {
                        "elapsed_seconds": 0.0,
                        "temperature_c": target,
                        "within_tolerance": True,
                    }
                ],
            }

        def fake_capture(**kwargs):
            capture_calls.append(dict(kwargs))
            label = kwargs["temperature_label"]
            output_dir = kwargs["output_dir"]
            return {
                "ok": True,
                "output_dir": output_dir,
                "metadata_path": os.path.join(output_dir, "metadata.json"),
                "temperature_label": label,
                "capture_source": kwargs["capture_source"],
                "captures": [
                    {
                        "droplet_id": droplet_id,
                        "captures": [
                            {
                                "channel": "FAM",
                                "path": os.path.join(output_dir, f"d{droplet_id}_{label}.png"),
                            }
                        ],
                    }
                    for droplet_id in kwargs["droplet_ids"]
                ],
                "errors": [],
            }

        runtime._temperature_hold_impl = fake_hold
        runtime.capture_droplet_images = fake_capture

        with tempfile.TemporaryDirectory() as output_dir:
            start_status = runtime.start_melting_curve_capture(
                start_c=30,
                end_c=31,
                step_c=0.5,
                hold_seconds=10,
                output_dir=output_dir,
                channels=["FAM"],
            )
            self.assertTrue(start_status["running"])
            runtime._melting_curve_thread.join(timeout=2.0)

            status = runtime.melting_curve_capture_status()

        self.assertFalse(status["thread_alive"])
        self.assertTrue(status["completed"])
        self.assertTrue(status["ok"])
        self.assertEqual(hold_targets, [30.0, 30.5, 31.0])
        self.assertEqual(hold_tolerances, [0.2, 0.2, 0.2])
        self.assertEqual(
            [call["temperature_label"] for call in capture_calls],
            ["30C", "30.5C", "31C"],
        )
        self.assertEqual(len(capture_calls), 3)
        self.assertEqual(status["completed_steps"], 3)
        self.assertEqual(status["results"][-1]["capture"]["image_count"], 2)
        self.assertIn("31C", status["path"])


if __name__ == "__main__":
    unittest.main()
