import unittest
from unittest.mock import patch
from types import SimpleNamespace

from droplogic.mcp.runtime import DropLogicMCPRuntime


class _FakeFrontPanel:
    def __init__(self):
        self.parent = None
        self.owner = "mcp"
        self.calls = []
        self.front_panel = SimpleNamespace(default_expression="sleep", _expression="sleep")

    def claim_control(self, owner, **kwargs):
        self.owner = owner
        self.calls.append(("claim", owner, kwargs))
        expression = kwargs.get("expression")
        if expression is not None:
            self.front_panel._expression = expression
        return True

    def release_control(self, owner, **kwargs):
        self.owner = kwargs.get("fallback_owner", "unclaimed")
        self.calls.append(("release", owner, kwargs))
        expression = kwargs.get("expression")
        if expression is not None:
            self.front_panel._expression = expression
        return True

    def set_expression(self, expression, **kwargs):
        self.calls.append(("expression", expression, kwargs))
        self.front_panel._expression = expression
        return True

    def start_animation(self, expression=None, **kwargs):
        self.calls.append(("start_animation", expression, kwargs))
        return True

    def blackout(self):
        self.calls.append(("blackout", None))
        return True


class _FakeBoxMini:
    def __init__(self, config_file="config.json", log_level="INFO", reset_matrix=False, front_panel_service=None):
        self.name = "BOXMini"
        self.host_os = "Windows"
        self.host_platform = {}
        self.visualizers = None
        self.advanced_drop = None
        self.front_panel = front_panel_service
        if self.front_panel is not None:
            self.front_panel.claim_control(
                "boxmini",
                expression="idle",
                immediate=True,
                start_animation=True,
            )

    def close(self):
        if self.front_panel is not None:
            self.front_panel.release_control(
                "boxmini",
                fallback_owner="mcp",
                expression="sleep",
                immediate=True,
                start_animation=True,
            )


class MCPFrontPanelRuntimeTests(unittest.TestCase):
    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_runtime_hands_front_panel_between_mcp_and_boxmini_and_blacks_out_on_shutdown(self, build_service):
        fake_panel = _FakeFrontPanel()
        build_service.return_value = fake_panel
        runtime = DropLogicMCPRuntime(allow_real_hardware=True)

        with patch("droplogic.hardware.box_mini1.BOXMini", _FakeBoxMini), \
             patch.object(DropLogicMCPRuntime, "_acquire_real_hardware_lock", return_value=None), \
             patch.object(DropLogicMCPRuntime, "_release_real_hardware_lock", return_value=None):
            status = runtime.load_system("boxmini")
            self.assertTrue(status["system"]["loaded"])
            self.assertEqual(runtime.front_panel.owner, "boxmini")

            status = runtime.close_system()
            self.assertFalse(status["system"]["loaded"])
            self.assertEqual(runtime.front_panel.owner, "mcp")

            runtime.shutdown()
            self.assertIn(("blackout", None), fake_panel.calls)

    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_error_recovery_blocks_normal_tool_face_updates_until_hold_expires(self, build_service):
        fake_panel = _FakeFrontPanel()
        build_service.return_value = fake_panel
        runtime = DropLogicMCPRuntime()

        runtime._front_panel_error_recovery(error_duration=60.0, fallback_expression="sleep")
        calls_after_error = len(fake_panel.calls)

        runtime.on_tool_start("runtime_status")
        runtime.on_tool_success("runtime_status")
        runtime.on_tool_start("load_system")
        runtime.on_tool_success("load_system")

        self.assertEqual(len(fake_panel.calls), calls_after_error)
        self.assertEqual(fake_panel.front_panel._expression, "sad")

        runtime._front_panel_error_hold_until = 0.0
        runtime.on_tool_success("load_system")

        self.assertEqual(fake_panel.front_panel._expression, "sleep")

    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_repeated_error_recovery_does_not_restart_sad_animation_loop(self, build_service):
        fake_panel = _FakeFrontPanel()
        build_service.return_value = fake_panel
        runtime = DropLogicMCPRuntime()

        runtime._front_panel_error_recovery(error_duration=60.0, fallback_expression="sleep")
        first_call_count = len(fake_panel.calls)

        runtime._front_panel_error_recovery(error_duration=60.0, fallback_expression="sleep")

        self.assertEqual(len(fake_panel.calls), first_call_count)
        self.assertEqual(fake_panel.front_panel._expression, "sad")

    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_visualizer_frame_without_available_frame_returns_benign_result(self, build_service):
        build_service.return_value = None
        runtime = DropLogicMCPRuntime()

        class _FakeVisualizer:
            def get_snapshot_frame(self):
                return None

        class _FakeVisualizers:
            matrix = _FakeVisualizer()
            streamer = None

        class _FakeSystem:
            visualizers = _FakeVisualizers()

        runtime.system = _FakeSystem()
        runtime.system_name = "boxmini"

        result = runtime.visualizer_frame(visualizer="matrix", frame_source="snapshot")

        self.assertFalse(result["ok"])
        self.assertFalse(result["frame_available"])
        self.assertEqual(result["visualizer"], "matrix")
        self.assertEqual(result["frame_source"], "snapshot")

    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_visualizer_frame_without_loaded_system_returns_benign_result(self, build_service):
        build_service.return_value = None
        runtime = DropLogicMCPRuntime()

        result = runtime.visualizer_frame(visualizer="matrix", frame_source="snapshot")

        self.assertFalse(result["ok"])
        self.assertFalse(result["frame_available"])
        self.assertEqual(result["reason"], "No system loaded.")

    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_passive_idle_updates_are_throttled_when_expression_is_already_idle(self, build_service):
        fake_panel = _FakeFrontPanel()
        build_service.return_value = fake_panel
        runtime = DropLogicMCPRuntime()
        runtime.system = object()
        runtime.system_name = "simulator"
        fake_panel.front_panel._expression = "idle"
        runtime._front_panel_last_requested_expression = "idle"
        runtime._front_panel_last_requested_at = 100.0

        with patch("droplogic.mcp.runtime.time.monotonic", return_value=100.5):
            runtime.on_tool_success("status")

        self.assertFalse(any(call[0] == "expression" and call[1] == "idle" for call in fake_panel.calls))


if __name__ == "__main__":
    unittest.main()
