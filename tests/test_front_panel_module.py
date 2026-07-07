import unittest

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
        self.assertEqual(sent, ["o_o"])


if __name__ == "__main__":
    unittest.main()
