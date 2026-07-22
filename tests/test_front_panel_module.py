import json
import tempfile
import unittest
from pathlib import Path

from droplogic.hardware.modules.front_panel import FrontPanelModule
from droplogic.hardware.modules.front_panel.front_panel_types import FrontPanelResponse
from droplogic.hardware.modules.front_panel.versions.droptibot_v1 import DroptiBotV1


class FrontPanelModuleTests(unittest.TestCase):
    def test_builds_eq2013_text_packet_for_detected_panel(self):
        panel = FrontPanelModule(
            port="COM16",
            baudrate=57600,
            address=1,
            width=48,
            height=16,
            require_ack=True,
            animations_enabled=False,
            bitmap_enabled=False,
        )

        packet = panel.build_text_packet("DL48")

        self.assertEqual(
            packet,
            "!#001%ZD00%ZI01%ZC0000000000480016%ZA01%ZS03%ZH6000"
            "%F16%C1%AH2%AV2DL48$$",
        )

    def test_accepts_observed_front_panel_ack(self):
        self.assertTrue(FrontPanelModule.is_ack("##FOK$$$"))
        self.assertTrue(FrontPanelModule.is_ack("##KOK$$$"))

    def test_builds_clear_packet(self):
        panel = FrontPanelModule(address="001", animations_enabled=False, bitmap_enabled=False)

        self.assertEqual(panel.build_clear_packet(), "!#001%ZD00$$")

    def test_factory_creates_droptibot_v1(self):
        panel = FrontPanelModule.from_config(
            {
                "version": "DroptiBot v1.0",
                "Port": "COM16",
                "width": 48,
                "height": 16,
                "animations_enabled": False,
                "bitmap_enabled": False,
            }
        )

        self.assertIsInstance(panel.front_panel, DroptiBotV1)

    def test_action_paths_choose_expected_expression(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
            text_fallback_enabled=True,
        )
        panel.front_panel.set_text = lambda *_args, **_kwargs: None

        panel.notify_action("xy_stage.position.X", 1000)
        self.assertEqual(panel.front_panel._expression, "moving")

        panel.notify_action("electrode_matrix.matrix", [])
        self.assertEqual(panel.front_panel._expression, "working")

        panel.notify_action("camera_settings.exposure_time", 12000)
        self.assertEqual(panel.front_panel._expression, "looking")

    def test_expression_aliases_match_personality_states(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
            text_fallback_enabled=True,
        )
        panel.front_panel.set_text = lambda *_args, **_kwargs: FrontPanelResponse(
            ok=True,
            response="ok",
            packet="<text>",
        )

        panel.set_expression("happy", immediate=True)
        self.assertEqual(panel.front_panel._expression, "done")

        panel.set_expression("sleeping", immediate=True)
        self.assertEqual(panel.front_panel._expression, "sleep")

        panel.set_expression("focused", immediate=True)
        self.assertEqual(panel.front_panel._expression, "working")

    def test_renders_bitmap_face_at_panel_size(self):
        panel = FrontPanelModule(animations_enabled=False, bitmap_enabled=False)
        frame = panel.front_panel._frames_for_expression("idle")[0]

        image = panel.front_panel._render_face(frame)

        self.assertEqual(image.size, (48, 16))
        self.assertNotEqual(image.getbbox(), None)

    def test_expression_does_not_use_unconfirmed_bitmap_or_ascii_by_default(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=True,
            bitmap_transport="eq_dll_realtime",
            bitmap_visual_confirmed=False,
            text_fallback_enabled=False,
        )
        panel.front_panel.send_image = lambda *_args, **_kwargs: self.fail("bitmap should not be sent")
        panel.front_panel.set_text = lambda *_args, **_kwargs: self.fail("ASCII fallback should not be sent")

        response = panel.set_expression("idle", immediate=True)

        self.assertFalse(response.ok)
        self.assertIn("no confirmed pixel transport", panel.front_panel.last_response)

    def test_expression_can_opt_into_text_fallback_for_bench_testing(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
            text_fallback_enabled=True,
        )
        sent = []
        panel.front_panel.set_text = lambda text, **_kwargs: sent.append(text) or FrontPanelResponse(
            ok=True,
            response="ok",
            packet="<text>",
        )

        response = panel.set_expression("idle", immediate=True)

        self.assertTrue(response.ok)
        self.assertEqual(sent, ["0.0"])

    def test_sleep_expression_carries_graphic_symbol_frames(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
        )

        sleep_frames = panel.front_panel._frames_for_expression("sleep")

        self.assertTrue(all(frame.get("symbol") == "sleep_zz" for frame in sleep_frames))
        self.assertGreater(len({frame.get("symbol_phase") for frame in sleep_frames}), 1)

    def test_idle_expression_can_fall_asleep_after_inactivity(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
            text_fallback_enabled=True,
            sleep_after_seconds=0.1,
        )

        panel.front_panel._expression = "idle"
        panel.front_panel._expression_expires_at = None
        panel.front_panel._frame_index = 0
        panel.front_panel._last_frame = None
        panel.front_panel._last_activity_at = 0.0

        import time

        real_monotonic = time.monotonic
        try:
            time.monotonic = lambda: 1.0
            panel.front_panel._rng.seed(0)
            frame, expression, text_frame, frame_delay = panel.front_panel._next_animation_frame()
        finally:
            time.monotonic = real_monotonic

        self.assertEqual(expression, "sleep")
        self.assertIsNone(text_frame)
        self.assertEqual(frame.get("symbol"), "sleep_zz")
        self.assertGreaterEqual(frame_delay, 0.1)

    def test_idle_text_fallback_uses_multiple_microexpressions(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
            text_fallback_enabled=True,
        )

        panel.front_panel._rng.seed(0)
        seen = set()
        for index in range(24):
            text_frame, _delay = panel.front_panel._next_text_fallback_frame("idle", index)
            seen.add(text_frame)

        self.assertIn("0.0", seen)
        self.assertTrue(any(frame.strip() != frame or frame in {" 0.o", "o.0 ", "-.-"} for frame in seen))
        self.assertGreater(len(seen), 3)

    def test_personality_frames_include_roboeyes_style_gaze_changes(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
        )

        frames = panel.front_panel._frames_for_expression("looking")

        pupil_positions = {(frame.get("pupil_x"), frame.get("pupil_y")) for frame in frames}
        self.assertGreater(len(pupil_positions), 2)
        self.assertTrue(any(frame.get("curiosity") for frame in frames))

    def test_personality_delay_uses_scene_dwell_when_no_ascii_override_exists(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
            frame_interval=0.5,
            frame_interval_jitter=0.0,
        )

        delay = panel.front_panel._frame_delay_for_expression("sad", 0)

        self.assertGreater(delay, 0.5)

    def test_rendered_sleep_frame_draws_pixels_in_upper_right_for_zetas(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
        )
        image = panel.front_panel._render_face(panel.front_panel._frames_for_expression("sleep")[-1])

        self.assertIsNotNone(image.getbbox())
        self.assertIsNotNone(image.crop((34, 0, 48, 8)).getbbox())

    def test_module_can_handoff_control_and_blackout(self):
        panel = FrontPanelModule(
            animations_enabled=False,
            bitmap_enabled=False,
        )

        calls = []
        panel.front_panel.start_animation = lambda expression=None, **kwargs: calls.append(("start", expression, kwargs)) or True
        panel.front_panel.stop_animation = lambda **kwargs: calls.append(("stop", None, kwargs)) or True
        panel.front_panel.set_expression = (
            lambda expression, **kwargs: calls.append(("expr", expression, kwargs.get("immediate"))) or True
        )
        panel.front_panel.blackout = lambda: calls.append(("blackout", None)) or True

        panel.claim_control("mcp", expression="sleep", immediate=True, start_animation=True)
        panel.claim_control("boxmini", expression="idle", immediate=True, start_animation=False)
        panel.release_control("boxmini", fallback_owner="mcp", expression="sleep", immediate=True, start_animation=True)
        panel.blackout()

        self.assertEqual(panel.owner, "mcp")
        self.assertTrue(any(call[0] == "start" and call[1] == "sleep" for call in calls))
        self.assertTrue(any(call[0] == "stop" for call in calls))
        self.assertIn(("expr", "idle", True), calls)
        self.assertIn(("blackout", None), calls)

    def test_asset_library_can_drive_bitmap_frame_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_root = Path(temp_dir) / "front_panel_state_library"
            state_root = asset_root / "idle"
            state_root.mkdir(parents=True)
            (asset_root / "manifest.json").write_text(
                json.dumps({"idle": {"manifest": "manifest.json"}}),
                encoding="utf-8",
            )
            (state_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "entry_frame": "idle.bmp",
                        "frames": {"idle.bmp": {"next": ["idle.bmp"]}},
                    }
                ),
                encoding="utf-8",
            )
            (state_root / "idle.bmp").write_bytes(b"BM")

            panel = FrontPanelModule(
                animations_enabled=False,
                bitmap_enabled=True,
                bitmap_transport="eq_dll_realtime",
                bitmap_visual_confirmed=True,
                asset_library_path=str(asset_root),
                asset_mode_enabled=True,
            )

            panel.front_panel._expression = "idle"
            panel.front_panel._asset_state = "idle"
            panel.front_panel._asset_frame_name = panel.front_panel._asset_entry_frame("idle")
            frame, expression, _text_frame, _delay = panel.front_panel._next_animation_frame()

            self.assertEqual(expression, "idle")
            self.assertIsInstance(frame, Path)
            self.assertEqual(frame.suffix.lower(), ".bmp")
            self.assertIn("front_panel_state_library", str(frame))


if __name__ == "__main__":
    unittest.main()
