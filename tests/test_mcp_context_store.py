from __future__ import annotations

import unittest

from droplogic.mcp.context_store import DropLogicMCPContextStore


class GuideContextSelectionTests(unittest.TestCase):
    def test_selection_returns_portable_next_turn_context_update(self) -> None:
        store = DropLogicMCPContextStore("boxmini")

        result = store.select_guide_context(
            [
                "agent-guide/10-imaging-light-vision.md",
                "agent-guide/11-temperature.md",
            ],
            "Prepare the next reasoning turn for melting capture.",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["selected_paths"], result["context_update"]["paths"])
        self.assertTrue(result["context_update"]["apply_before_next_model_turn"])
        self.assertEqual(
            [file["path"] for file in result["context_update"]["files"]],
            result["selected_paths"],
        )
        self.assertIn("Temperature", result["context_update"]["files"][1]["content"])
        self.assertEqual(store.status()["guide_context"]["selected_paths"], result["selected_paths"])

    def test_selection_rejects_non_guide_context_file(self) -> None:
        store = DropLogicMCPContextStore("boxmini")

        with self.assertRaisesRegex(ValueError, "Unknown detailed guide file"):
            store.select_guide_context(["cartridge.default.json"], "Not a guide shard.")

    def test_pinned_entrypoint_is_rejected_without_replacing_prior_selection(self) -> None:
        store = DropLogicMCPContextStore("boxmini")
        original = store.select_guide_context(
            ["agent-guide/11-temperature.md"],
            "Prepare a thermal reasoning turn.",
        )

        with self.assertRaisesRegex(
            ValueError,
            "pinned operating-guide entrypoint.*loaded automatically.*agent-guide/11-temperature.md",
        ):
            store.select_guide_context(
                ["agent-guide.md", "agent-guide/11-temperature.md"],
                "Incorrectly treating the pinned entrypoint as a detailed shard.",
            )

        status = store.status()["guide_context"]
        self.assertEqual(status["selected_paths"], original["selected_paths"])
        self.assertEqual(status["revision"], original["revision"])

    def test_valid_replacement_is_atomic_and_contains_only_detailed_shards(self) -> None:
        store = DropLogicMCPContextStore("boxmini")
        store.select_guide_context(["agent-guide/11-temperature.md"], "Initial turn.")

        replacement = store.select_guide_context(
            [
                "agent-guide/10-imaging-light-vision.md",
                "agent-guide/11-temperature.md",
            ],
            "Prepare a melting-capture turn.",
        )

        self.assertEqual(replacement["revision"], 2)
        self.assertEqual(
            replacement["previous_paths"],
            ["agent-guide/11-temperature.md"],
        )
        self.assertTrue(
            all(path.startswith("agent-guide/") for path in replacement["selected_paths"])
        )
        self.assertEqual(
            store.status()["guide_context"]["selected_paths"],
            replacement["selected_paths"],
        )

    def test_temperature_guide_requires_real_melting_capture_for_per_step_images(self) -> None:
        store = DropLogicMCPContextStore("boxmini")

        temperature_guide = store.read_text("agent-guide/11-temperature.md")["content"]

        self.assertIn("Use `start_melting_curve_capture` instead.", temperature_guide)
        self.assertNotIn("dry", temperature_guide.lower())
        self.assertNotIn("simulat", temperature_guide.lower())

    def test_reservoir_guides_require_full_campaign_budget_before_creation(self) -> None:
        store = DropLogicMCPContextStore("boxmini")

        injection_guide = store.read_text("agent-guide/07-droplets-reservoirs-injection.md")["content"]
        extraction_guide = store.read_text("agent-guide/08-reservoir-extraction.md")["content"]

        self.assertIn("max(2 * product_area, product_area + 20)", injection_guide)
        self.assertIn("20 products of `2 x 2`", injection_guide)
        self.assertIn("before `create_droplet`", injection_guide)
        self.assertIn("This is a preflight decision", extraction_guide)


if __name__ == "__main__":
    unittest.main()
