import unittest
from types import SimpleNamespace
from unittest.mock import patch

from droplogic.base import DropSystem
from droplogic.hardware.box_mini1 import BOXMini
from droplogic.mcp.runtime import DropLogicMCPRuntime


class RuntimeReviewFixTests(unittest.TestCase):
    def test_compact_status_does_not_start_mjpeg_server(self):
        runtime = DropLogicMCPRuntime()
        visualizer = SimpleNamespace(
            window_name=None,
            window_enabled=False,
            _window_mode=None,
            _headless_active=False,
            _display_active=False,
            last_exit_reason=None,
            last_display_error=None,
        )
        runtime.system = SimpleNamespace(
            name="BOXMini",
            host_os="linux",
            host_platform={},
            visualizers=SimpleNamespace(matrix=visualizer, streamer=None),
        )
        runtime.system_name = "boxmini"

        with patch.object(
            runtime,
            "ensure_mjpeg_server",
            side_effect=AssertionError("status started the server"),
        ):
            status = runtime.status(detail="compact")

        self.assertTrue(status["system"]["loaded"])
        self.assertFalse(status["visualizers"]["matrix"]["is_running"])

    def test_failed_boxmini_initialization_releases_base_workers_and_singleton(self):
        created = {}

        class FakeSerial:
            is_open = True

            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True
                self.is_open = False

        serial_port = FakeSerial()

        def fail_after_base_initialization(box, **kwargs):
            created["box"] = box
            DropSystem.__init__(
                box,
                "BOXMini",
                state_file=kwargs.get("config_file", "config.json"),
            )
            box.temperature_serial = serial_port
            raise RuntimeError("XY stage initialization failed")

        BOXMini._instance = None
        try:
            with patch.object(BOXMini, "_initialize", fail_after_base_initialization):
                with self.assertRaisesRegex(RuntimeError, "XY stage initialization failed"):
                    BOXMini(config_file="config.json")

            box = created["box"]
            self.assertIsNone(BOXMini._instance)
            self.assertTrue(serial_port.closed)
            self.assertTrue(box._queue_stop_event.is_set())
            self.assertTrue(
                all(not worker.is_alive() for worker in box._queue_workers.values())
            )
            self.assertFalse(box._state_save_worker.is_alive())
        finally:
            BOXMini._instance = None

    def test_stage_timeout_is_not_reclassified_as_success(self):
        runtime = DropLogicMCPRuntime()

        self.assertFalse(
            runtime._queue_wait_false_but_stage_reached_target(
                {
                    "ok": False,
                    "timed_out": True,
                    "pending_commands": 1,
                }
            )
        )
        self.assertTrue(
            runtime._queue_wait_false_but_stage_reached_target(
                {
                    "ok": False,
                    "timed_out": False,
                    "pending_commands": 0,
                    "hardware_errors": [
                        {"path": "xy_stage.position", "error": "false negative"}
                    ],
                }
            )
        )

    def test_default_plan_move_keeps_bounded_synchronous_path(self):
        runtime = DropLogicMCPRuntime()
        runtime.system = SimpleNamespace(
            advanced_drop=SimpleNamespace(move=lambda **kwargs: kwargs),
        )

        with patch.object(
            runtime,
            "_advanced_drop_active_move_count",
            return_value=1,
        ), patch.object(
            runtime, "_execute_advanced_drop_call", return_value={"ok": True}
        ) as execute:
            result = runtime.plan_move()

        self.assertTrue(result["ok"])
        arguments = execute.call_args.args[1]
        self.assertEqual(
            arguments["planning_timeout"],
            runtime.ADVANCED_DROP_SYNC_MOVE_MAX_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
