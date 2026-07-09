import json
import os
import tempfile
import unittest
from unittest.mock import patch

from droplogic.mcp import server
from droplogic.mcp.runtime import DropLogicMCPRuntime


class MCPDashboardSceneRefreshTests(unittest.TestCase):
    def test_runtime_tools_do_not_drive_dashboard_scene_refresh(self):
        class RuntimeStub:
            def __init__(self):
                self.hooks = []

            def on_tool_start(self, tool_name):
                self.hooks.append(("start", tool_name))

            def on_tool_success(self, tool_name):
                self.hooks.append(("success", tool_name))

            def refresh_dashboard_scene_after_tool(self, tool_name):
                raise AssertionError("tools must not trigger dashboard scene refresh")

            def set_matrix_cells(self):
                return {"ok": True}

        runtime = RuntimeStub()

        result = server._runtime_call(runtime.set_matrix_cells)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            runtime.hooks,
            [("start", "set_matrix_cells"), ("success", "set_matrix_cells")],
        )

    def test_dashboard_scene_interval_defaults_and_clamps(self):
        env_key = "DROPLOGIC_DASHBOARD_SCENE_INTERVAL_SECONDS"
        previous = os.environ.pop(env_key, None)
        try:
            self.assertEqual(DropLogicMCPRuntime._dashboard_scene_interval(), 0.1)
            os.environ[env_key] = "0.001"
            self.assertEqual(DropLogicMCPRuntime._dashboard_scene_interval(), 0.05)
            os.environ[env_key] = "10"
            self.assertEqual(DropLogicMCPRuntime._dashboard_scene_interval(), 5.0)
            os.environ[env_key] = "not-a-number"
            self.assertEqual(DropLogicMCPRuntime._dashboard_scene_interval(), 0.1)
        finally:
            if previous is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = previous

    @patch.object(DropLogicMCPRuntime, "_build_front_panel_service")
    def test_dashboard_scene_snapshot_write_does_not_fsync(self, build_service):
        build_service.return_value = None
        runtime = DropLogicMCPRuntime()
        scene = {"available": True, "matrix": {"rows": 1, "columns": 1}}

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime.dashboard_scene_path = os.path.join(temp_dir, "dashboard_scene.json")
            with patch.object(runtime, "dashboard_scene", return_value=scene), patch(
                "droplogic.mcp.runtime.os.fsync"
            ) as fsync:
                runtime.write_dashboard_scene_snapshot()

            fsync.assert_not_called()
            with open(runtime.dashboard_scene_path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), scene)


if __name__ == "__main__":
    unittest.main()
