import copy
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


class LinearExtractionRegressionTests(unittest.TestCase):
    def make_reservoir_case(self):
        reservoir_shape = {(row, col) for row in range(6) for col in range(8)}
        reservoir = make_droplet(100, (43, 30), reservoir_shape, 1)
        droplets = [reservoir]
        return droplets, make_plan(droplets, active_ids=[100])

    def test_linear_extraction_rejects_droplets_outside_reservoir_footprint(self):
        droplets, plan = self.make_reservoir_case()

        with self.assertRaisesRegex(ValueError, "outside the reservoir footprint"):
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
                linear_space_per_col=2,
                linear_space_per_row=2,
                linear_vital_space=2,
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
            linear_space_per_col=2,
            linear_space_per_row=2,
            linear_vital_space=2,
        )

        self.assertEqual({droplet.id for droplet in updated}, {100, 101, 102, 103, 104})
        self.assertTrue({100, 101, 102, 103, 104}.issubset(new_plan.active_droplets_per_frame[-1]))


class RuntimeRollbackRegressionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
