from __future__ import annotations

from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from test_dashboard_studio import studio, config, INVENTORY

workflow = importlib.import_module(studio.__package__ + ".dashboard_workflow")
provider_module = importlib.import_module(studio.__package__ + ".dashboard_provider")
SETTINGS = {"model": "small-local", "base_url": "http://model/v1", "api_key": "private-key"}
PLAN = {
    "mode": "design",
    "title": "Office",
    "tasks": [
        {
            "id": "office",
            "tool": "create_view",
            "title": "Office",
            "instruction": "Create a warm, calm office view with a wide focal section.",
        },
        {
            "id": "lighting",
            "tool": "add_section",
            "target": "office",
            "title": "Lighting",
            "instruction": "Show the real office light with a warm accent and useful controls.",
        },
    ],
}
VIEW = {"options": {"max_columns": 2}}
SECTION = {
    "options": {"column_span": 2},
    "cards": [{"type": "tile", "entity": "light.office", "color": "amber"}],
}
EXPLAIN = {
    "message": "A warm office view with a wide section for your light. Preview it before applying.",
    "suggestions": ["Add a temperature graph"],
}


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = SimpleNamespace(
            design=AsyncMock(
                side_effect=[deepcopy(PLAN), deepcopy(VIEW), deepcopy(SECTION), deepcopy(EXPLAIN)]
            )
        )
        self.engine = workflow.DashboardWorkflow(self.provider)
        self.original = {"views": []}
        self.inventory = deepcopy(INVENTORY)
        self.components = []

    async def run_design(self, **kwargs):
        ids = {item["entity_id"] for item in self.inventory}
        kinds = {kind for item in self.components for kind in item["types"]}
        return await self.engine.run(
            config=self.original,
            inventory=self.inventory,
            settings=SETTINGS,
            request="Design my office",
            title="My home",
            history=[],
            direction={"style": "warm", "layout": "original"},
            components=self.components,
            themes=["default", "Midnight"],
            card_types=studio.NATIVE_CARDS | {"weather-forecast"} | kinds,
            validate=lambda proposed: studio.validate_config(
                proposed,
                ids,
                self.original,
                ["default", "Midnight"],
                kinds,
                any(item["id"] == "card_mod" for item in self.components),
            ),
            **kwargs,
        )

    async def test_plan_atomic_tasks_explain_compile_sections_without_full_config_output(self):
        result = await self.run_design()
        self.assertEqual(self.original, {"views": []})
        view = result["config"]["views"][0]
        self.assertEqual(view["title"], "Office")
        self.assertEqual(view["sections"][0]["column_span"], 2)
        self.assertEqual(view["sections"][0]["cards"][-1]["entity"], "light.office")
        self.assertEqual(view["sections"][0]["cards"][0]["heading"], "Lighting")
        self.assertEqual(result["message"], EXPLAIN["message"])
        calls = self.provider.design.await_args_list
        self.assertEqual(
            [call.args[2]["title"] for call in calls],
            [
                "dashboard_plan",
                "dashboard_create_view",
                "dashboard_add_section",
                "dashboard_explain",
            ],
        )
        planner = json.loads(calls[0].args[0][-1]["content"])
        self.assertEqual(planner["home"], {"Office": {"light": 1, "sensor": 1}})
        self.assertNotIn("light.office", json.dumps(planner))
        for call in calls:
            self.assertNotIn("private-key", json.dumps(call.args[0]))
            self.assertNotIn("current_draft", json.dumps(call.args[0]))
        self.assertLess(len(json.dumps(calls[0].args[0]) + json.dumps(calls[0].args[2])), 6000)

    async def test_real_openai_tool_parser_uses_each_small_named_schema(self):
        client = provider_module.DashboardProvider(SimpleNamespace())

        def completion(name, body):
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": name, "arguments": json.dumps(body)}}
                            ]
                        }
                    }
                ]
            }

        client._post = AsyncMock(
            side_effect=[
                completion(name, body)
                for name, body in (
                    ("dashboard_plan", PLAN),
                    ("dashboard_create_view", VIEW),
                    ("dashboard_add_section", SECTION),
                    ("dashboard_explain", EXPLAIN),
                )
            ]
        )
        self.engine = workflow.DashboardWorkflow(client)
        result = await self.run_design()
        self.assertEqual(result["message"], EXPLAIN["message"])
        self.assertEqual(client._post.await_count, 4)
        for call in client._post.await_args_list:
            payload = call.args[1]
            self.assertEqual(payload["model"], "small-local")
            self.assertEqual(len(payload["tools"]), 1)
            self.assertNotIn("views", payload["tools"][0]["function"]["parameters"]["properties"])

    async def test_multi_view_plan_can_create_pending_views_before_filling_sections(self):
        plan = deepcopy(PLAN)
        plan["tasks"].insert(
            1,
            {
                "id": "comfort",
                "tool": "create_view",
                "title": "Comfort",
                "instruction": "Make a calm comfort view.",
            },
        )
        plan["tasks"].append(
            {
                "id": "temperature",
                "tool": "add_section",
                "target": "comfort",
                "title": "Temperature",
                "instruction": "Show the office temperature.",
            }
        )
        second = deepcopy(SECTION)
        second["cards"][0]["entity"] = "sensor.office_temperature"
        self.provider.design.side_effect = [plan, VIEW, VIEW, SECTION, second, EXPLAIN]
        result = await self.run_design()
        self.assertEqual(
            [view["title"] for view in result["config"]["views"]], ["Office", "Comfort"]
        )
        self.assertTrue(
            all(isinstance(view, dict) and view["sections"] for view in result["config"]["views"])
        )

    async def test_small_edit_preserves_unrelated_cards_sections_views_and_options(self):
        self.original = config()
        self.original["views"][0]["sections"].append(
            {"type": "grid", "cards": [{"type": "markdown", "content": "Keep"}]}
        )
        self.original["views"].append({**deepcopy(self.original["views"][0]), "path": "other"})
        self.original["views"][0]["header"] = {
            "card": {"type": "markdown", "content": "Keep header"}
        }
        before = deepcopy(self.original)
        self.provider.design.side_effect = [
            {
                "mode": "design",
                "tasks": [
                    {
                        "id": "rename",
                        "tool": "edit_card",
                        "target": "c1",
                        "instruction": "Rename only this light to Office lamp.",
                    }
                ],
            },
            {"card": {"type": "tile", "name": "Office lamp"}},
            EXPLAIN,
        ]
        result = await self.run_design()
        expected = deepcopy(before)
        expected["views"][0]["sections"][0]["cards"][0]["name"] = "Office lamp"
        self.assertEqual(result["config"], expected)
        self.assertEqual(self.original, before)
        context = json.loads(self.provider.design.await_args_list[1].args[0][-1]["content"])
        self.assertEqual([node["id"] for node in context["node"]], ["c1"])
        self.assertNotIn("Keep header", json.dumps(context))

    async def test_executor_cannot_change_the_locked_removal_target(self):
        self.original = config()
        self.original["views"].append({**deepcopy(config("Other")["views"][0]), "path": "other"})
        self.provider.design.side_effect = [
            {
                "mode": "design",
                "tasks": [
                    {
                        "id": "remove-light",
                        "tool": "remove",
                        "target": "c1",
                        "instruction": "Remove this light card.",
                    }
                ],
            },
            {"target": "v2"},
            {"target": "c1"},
            EXPLAIN,
        ]
        result = await self.run_design()
        self.assertEqual(result["config"]["views"][1], self.original["views"][1])
        self.assertEqual(result["config"]["views"][0]["sections"][0]["cards"], [])
        feedback = json.loads(self.provider.design.await_args_list[2].args[0][-1]["content"])[
            "feedback"
        ]
        self.assertIn("target unchanged", feedback["error"])

    async def test_unknown_entity_retries_only_that_section_and_does_not_save_bad_content(self):
        invalid = deepcopy(SECTION)
        invalid["cards"][0]["entity"] = "light.invented"
        self.provider.design.side_effect = [PLAN, VIEW, invalid, SECTION, EXPLAIN]
        result = await self.run_design()
        self.assertNotIn("invented", json.dumps(result["config"]))
        feedback = json.loads(self.provider.design.await_args_list[3].args[0][-1]["content"])[
            "feedback"
        ]
        self.assertIn("Unknown entities", feedback["error"])
        self.assertEqual(self.original, {"views": []})
        self.assertEqual(
            self.provider.design.await_args_list[2].args[2],
            self.provider.design.await_args_list[3].args[2],
        )

    async def test_outline_or_whole_dashboard_reply_cannot_replace_a_saved_design(self):
        self.original = config()
        before = deepcopy(self.original)
        self.provider.design.side_effect = [
            {
                "mode": "design",
                "tasks": [
                    {
                        "id": "replace",
                        "tool": "replace_section",
                        "target": "s1",
                        "instruction": "Recompose this section.",
                    }
                ],
            },
            {"config": {"views": [{"type": "sections"}, "Not an object"]}},
            {"cards": []},
        ]
        with self.assertRaisesRegex(ValueError, "saved draft is unchanged"):
            await self.run_design()
        self.assertEqual(self.original, before)

    async def test_failed_later_task_preserves_the_original_despite_prior_private_progress(self):
        plan = deepcopy(PLAN)
        plan["tasks"].append(
            {
                "id": "temperature",
                "tool": "add_section",
                "target": "office",
                "title": "Temperature",
                "instruction": "Add the temperature.",
            }
        )
        self.provider.design.side_effect = [plan, VIEW, SECTION, {"cards": []}, {"cards": []}]
        with self.assertRaisesRegex(ValueError, "saved draft is unchanged"):
            await self.run_design()
        self.assertEqual(self.original, {"views": []})
        failed_context = json.loads(self.provider.design.await_args_list[3].args[0][-1]["content"])
        self.assertIn("light.office", json.dumps(failed_context["node"]))

    async def test_relevant_entity_lookup_is_compact_and_includes_targeted_room(self):
        self.inventory += [
            {
                "entity_id": f"light.garage_{i}",
                "name": f"Garage {i}",
                "domain": "light",
                "area": "Garage",
            }
            for i in range(100)
        ]
        await self.run_design()
        context = json.loads(self.provider.design.await_args_list[2].args[0][-1]["content"])
        self.assertLessEqual(len(context["available_entities"]), 48)
        self.assertIn("light.office", [row["entity_id"] for row in context["available_entities"]])
        self.assertNotIn("state", context["available_entities"][0])

    async def test_empty_new_section_cannot_count_as_a_finished_design(self):
        self.provider.design.side_effect = [PLAN, VIEW, {"cards": []}, {"cards": []}]
        with self.assertRaisesRegex(ValueError, "actual card objects"):
            await self.run_design()
        self.assertEqual(self.original, {"views": []})

    async def test_discussion_preserves_the_document_and_uses_only_one_call(self):
        self.original = config()
        self.provider.design.side_effect = [
            {"mode": "discuss", "message": "Would you prefer a wall tablet or phone layout?"}
        ]
        result = await self.run_design()
        self.assertIsNone(result["config"])
        self.assertEqual(self.original, config())
        self.assertEqual(self.provider.design.await_count, 1)

    async def test_explanation_failure_keeps_the_verified_draft(self):
        self.provider.design.side_effect = [PLAN, VIEW, SECTION, RuntimeError("Model disconnected")]
        result = await self.run_design()
        self.assertTrue(result["config"]["views"][0]["sections"])
        self.assertIn("ready to preview", result["message"])

    async def test_focused_plan_cannot_replace_or_add_another_view(self):
        self.original = config()
        self.provider.design.side_effect = [PLAN, PLAN]
        with self.assertRaisesRegex(ValueError, "selected scope"):
            await self.run_design(focus={"view_index": 0})
        self.assertEqual(self.original, config())

    async def test_planner_outline_without_content_tasks_is_retried_before_building(self):
        empty_plan = {"mode": "design", "tasks": [deepcopy(PLAN["tasks"][0])]}
        self.provider.design.side_effect = [empty_plan, PLAN, VIEW, SECTION, EXPLAIN]
        result = await self.run_design()
        self.assertTrue(result["config"]["views"][0]["sections"])
        feedback = json.loads(self.provider.design.await_args_list[1].args[0][-1]["content"])[
            "feedback"
        ]
        self.assertIn("every new view", feedback["error"])

    async def test_large_card_text_is_not_resent_for_an_unrelated_small_edit(self):
        self.original = config()
        self.original["views"][0]["sections"][0]["cards"].append(
            {"type": "markdown", "content": "Private long note. " * 10000}
        )
        self.provider.design.side_effect = [
            {
                "mode": "design",
                "tasks": [
                    {
                        "id": "rename",
                        "tool": "edit_card",
                        "target": "c1",
                        "instruction": "Rename this light.",
                    }
                ],
            },
            {"card": {"type": "tile", "name": "Office light"}},
            EXPLAIN,
        ]
        result = await self.run_design()
        self.assertEqual(
            result["config"]["views"][0]["sections"][0]["cards"][1],
            self.original["views"][0]["sections"][0]["cards"][1],
        )
        for call in self.provider.design.await_args_list:
            self.assertNotIn("Private long note", json.dumps(call.args[0]))

    async def test_installed_cards_static_styles_and_original_composition_survive_compilation(self):
        self.components = [
            {
                "id": "mushroom",
                "label": "Mushroom",
                "types": ["custom:mushroom-entity-card"],
                "guidance": "Needs entity",
            },
            {"id": "card_mod", "label": "card-mod", "types": [], "guidance": "Static CSS only"},
        ]
        section = deepcopy(SECTION)
        section["cards"][0].update(
            type="custom:mushroom-entity-card",
            card_mod={"style": "ha-card { border-radius: 28px; }"},
            grid_options={"columns": 12, "rows": 2},
        )
        self.provider.design.side_effect = [
            PLAN,
            {
                "options": {
                    "theme": "Midnight",
                    "background": "linear-gradient(135deg,#111827,#30204a)",
                    "max_columns": 2,
                }
            },
            section,
            EXPLAIN,
        ]
        result = await self.run_design()
        view = result["config"]["views"][0]
        self.assertEqual(view["theme"], "Midnight")
        self.assertEqual(view["sections"][0]["cards"][-1]["type"], "custom:mushroom-entity-card")
        self.assertIn("28px", view["sections"][0]["cards"][-1]["card_mod"]["style"])


class DraftTests(unittest.TestCase):
    def test_grid_entity_list_is_compiled_into_real_child_cards(self):
        draft = workflow.Draft(config(), studio.NATIVE_CARDS)
        result = draft.apply(
            {
                "op": "add_card",
                "parent": "s1",
                "ref": "lights",
                "options": {
                    "type": "grid",
                    "columns": 2,
                    "entities": [
                        "light.office",
                        {"entity": "sensor.office_temperature", "name": "Temperature"},
                    ],
                },
            },
            "v1",
        )
        card = draft.nodes[result["id"]]["value"]
        self.assertNotIn("entities", card)
        self.assertEqual(
            card["cards"],
            [
                {"type": "tile", "entity": "light.office"},
                {"type": "tile", "entity": "sensor.office_temperature", "name": "Temperature"},
            ],
        )
        self.assertEqual(draft.content_errors(), [])
        self.assertTrue(any(node["parent"] == "lights" for node in draft.nodes.values()))

    def test_section_structure_stays_in_code_when_card_type_hint_is_sent(self):
        draft = workflow.Draft(config(), studio.NATIVE_CARDS)
        draft.apply(
            {"op": "update", "target": "s1", "type": "heading", "options": {"title": "Lights"}},
            "v1",
        )
        self.assertEqual(draft.nodes["s1"]["value"]["type"], "grid")
        self.assertEqual(
            draft.nodes["s1"]["value"]["cards"], config()["views"][0]["sections"][0]["cards"]
        )

    def test_property_update_preserves_other_nested_options(self):
        source = config()
        source["views"][0]["sections"][0]["cards"][0]["grid_options"] = {"columns": 6, "rows": 2}
        draft = workflow.Draft(source, studio.NATIVE_CARDS)
        draft.apply(
            {"op": "update", "target": "c1", "options": {"grid_options": {"columns": 12}}}, "c1"
        )
        self.assertEqual(draft.nodes["c1"]["value"]["grid_options"], {"columns": 12, "rows": 2})

    def test_reordering_keeps_stable_handles_and_removing_a_moved_card_removes_only_it(self):
        source = config()
        source["views"][0]["sections"][0]["cards"].append({"type": "markdown", "content": "First"})
        draft = workflow.Draft(source, studio.NATIVE_CARDS)
        draft.apply({"op": "move", "target": "c2", "parent": "s1", "index": 0}, "v1")
        self.assertEqual(draft.config["views"][0]["sections"][0]["cards"][0]["content"], "First")
        self.assertEqual(draft.nodes["c1"]["value"]["entity"], "light.office")
        draft.apply({"op": "remove", "target": "c2"}, "v1")
        self.assertEqual(draft.config, config())

    def test_nested_stacks_conditional_cards_and_removal_keep_handles_consistent(self):
        draft = workflow.Draft(config(), studio.NATIVE_CARDS)
        draft.apply(
            {"op": "add_card", "parent": "s1", "type": "vertical-stack", "ref": "stack"}, "v1"
        )
        draft.apply(
            {
                "op": "add_card",
                "parent": "stack",
                "type": "conditional",
                "ref": "condition",
                "options": {"conditions": []},
            },
            "v1",
        )
        draft.apply(
            {
                "op": "add_card",
                "parent": "condition",
                "type": "markdown",
                "ref": "note",
                "options": {"content": "Hello"},
            },
            "v1",
        )
        self.assertEqual(draft.content_errors(), [])
        draft.apply({"op": "remove", "target": "stack"}, "v1")
        self.assertTrue(all(ref not in draft.nodes for ref in ("stack", "condition", "note")))
        self.assertEqual(draft.config, config())

    def test_structural_json_cannot_be_smuggled_in_options_or_unset(self):
        draft = workflow.Draft(config(), studio.NATIVE_CARDS)
        for operation in (
            {"op": "update", "target": "v1", "options": {"sections": []}},
            {"op": "update", "target": "v1", "unset": ["sections"]},
            {"op": "add_card", "parent": "s1", "type": ["tile"]},
        ):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                draft.apply(operation, "v1")
        self.assertEqual(draft.config, config())

    def test_paths_are_unique_and_existing_custom_options_are_retained(self):
        source = config()
        source["views"][0]["custom_view_option"] = {"keep": True}
        draft = workflow.Draft(source, studio.NATIVE_CARDS)
        draft.create_view("Office")
        self.assertEqual(draft.config["views"][1]["path"], "office-2")
        self.assertEqual(draft.config["views"][0], source["views"][0])
