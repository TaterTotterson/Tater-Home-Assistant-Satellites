from copy import deepcopy
import importlib
import unittest

from test_dashboard_studio import studio, config, INVENTORY

design = importlib.import_module(studio.__package__ + ".dashboard_design")


class CompositionTests(unittest.TestCase):
    def test_prompt_inventory_is_small_but_covers_rooms_and_targeted_devices(self):
        inventory = [
            {
                "entity_id": f"light.room_{room}_{index}",
                "domain": "light",
                "area": f"Room {room}",
                "name": f"Room {room} light {index}",
            }
            for room in range(8)
            for index in range(20)
        ]
        selected = design.prompt_inventory(inventory, {"light.room_7_19"}, limit=32, text="Room 7")
        self.assertEqual(len(selected), 32)
        self.assertEqual(len({item["entity_id"] for item in selected}), 32)
        self.assertEqual({item["area"] for item in selected}, {f"Room {room}" for room in range(8)})
        self.assertIn("light.room_7_19", {item["entity_id"] for item in selected})
        self.assertEqual(design.prompt_inventory(INVENTORY), INVENTORY)

    def test_examples_are_valid_use_real_entities_and_allow_original_compositions(self):
        ids = {item["entity_id"] for item in INVENTORY}
        for layout in design.LAYOUTS:
            for item in design.layout_examples(INVENTORY, layout):
                with self.subTest(layout=layout, example=item["layout"]):
                    self.assertEqual(studio.validate_config(item["example"], ids), [])
        self.assertEqual(design.layout_examples(INVENTORY, "original"), [])
        self.assertEqual(design.layout_examples([], "bento"), [])
        self.assertEqual(len(design.layout_examples(INVENTORY, "auto")), 3)

    def test_resource_discovery_only_enables_documented_installed_components(self):
        resources = [
            {"type": "module", "url": "/hacsfiles/Bubble-Card/bubble-card.js?v=3"},
            {"type": "module", "url": "/local/bubble-card.js"},
            {"type": "module", "url": "/hacsfiles/lovelace-mushroom/mushroom.js"},
            {"type": "module", "url": "/hacsfiles/lovelace-card-mod/card-mod.js"},
            {"type": "module", "url": "/hacsfiles/fake/mushroom-strategy.js"},
            {"type": "css", "url": "/fake/button-card.js"},
            {"type": "module", "url": "javascript:button-card.js"},
            {"type": "module", "url": "button-card.js"},
            {"type": "module", "url": "https://[invalid/button-card.js"},
        ]
        found = design.installed_components(resources)
        self.assertEqual([item["id"] for item in found], ["bubble", "mushroom", "card_mod"])
        self.assertEqual(found[0]["resource_url"], resources[0]["url"])
        self.assertEqual(design.installed_components(None), [])

    def test_focused_section_merge_preserves_everything_else(self):
        original = config()
        original["background"] = "original background"
        original["views"][0]["header"] = {"card": {"type": "markdown", "content": "Keep"}}
        original["views"][0]["sections"].append(
            {"type": "grid", "cards": [{"type": "markdown", "content": "Unchanged section"}]}
        )
        original["views"].append({**deepcopy(original["views"][0]), "path": "other"})
        before = deepcopy(original)
        focus = {"view_index": 0, "section_index": 1}
        scoped = design.scoped_config(original, focus)
        self.assertEqual(len(scoped["views"]), 1)
        self.assertEqual(len(scoped["views"][0]["sections"]), 1)
        self.assertNotIn("header", scoped["views"][0])
        proposal = config("Changed view title should be ignored")
        proposal["background"] = "unwanted global change"
        result = design.merge_scope(original, proposal, focus)
        expected = deepcopy(original)
        expected["views"][0]["sections"][1] = proposal["views"][0]["sections"][0]
        self.assertEqual(result, expected)
        self.assertEqual(original, before)

    def test_bad_scopes_and_overbroad_responses_are_rejected(self):
        for focus in (
            [],
            {"view_index": True},
            {"view_index": -1},
            {"view_index": 9},
            {"view_index": 0, "section_index": True},
            {"view_index": 0, "section_index": 8},
            {"view_index": 0, "unexpected": 1},
        ):
            with self.subTest(focus=focus), self.assertRaises(ValueError):
                design.scoped_config(config(), focus)
        for proposal in (
            {},
            {"views": None},
            {"views": [None]},
            {"views": [{"sections": None}]},
            {"views": [config()["views"][0]] * 2},
        ):
            with self.subTest(proposal=proposal):
                self.assertTrue(
                    design.scope_errors(proposal, {"view_index": 0, "section_index": 0})
                )

    def test_palette_changes_do_not_count_as_different_concepts(self):
        first = studio.apply_visual_direction(config(), "neon", "")
        second = studio.apply_visual_direction(config(), "natural", "")
        self.assertEqual(design.composition_signature(first), design.composition_signature(second))
        second["views"][0]["header"] = {"card": {"type": "markdown", "content": "An opening"}}
        self.assertNotEqual(
            design.composition_signature(first), design.composition_signature(second)
        )

    def test_only_installed_custom_types_and_static_styles_are_accepted(self):
        proposal = config()
        card = proposal["views"][0]["sections"][0]["cards"][0]
        card["type"] = "custom:mushroom-entity-card"
        ids = {"light.office"}
        self.assertTrue(studio.validate_config(proposal, ids))
        self.assertEqual(studio.validate_config(proposal, ids, available_cards={card["type"]}), [])
        card["card_mod"] = {"style": "ha-card { border-radius: 24px; }"}
        self.assertTrue(studio.validate_config(proposal, ids, available_cards={card["type"]}))
        self.assertEqual(
            studio.validate_config(proposal, ids, available_cards={card["type"]}, card_mod=True), []
        )
        card["card_mod"]["style"] = "${window.alert('bad')}"
        self.assertTrue(
            studio.validate_config(proposal, ids, available_cards={card["type"]}, card_mod=True)
        )
        # Existing custom behavior remains preservable, rather than being erased.
        self.assertEqual(studio.validate_config(proposal, ids, original=proposal), [])


if __name__ == "__main__":
    unittest.main()
