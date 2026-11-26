from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from test_tater_assistant import tater, _Manager

studio = importlib.import_module(tater.__package__ + ".dashboard_studio")
USER = SimpleNamespace(id="admin-one", is_admin=True)
OTHER = SimpleNamespace(id="admin-two", is_admin=True)
INVENTORY = [
    {
        "entity_id": "light.office",
        "name": "Office lights",
        "domain": "light",
        "area": "Office",
        "state": "off",
    },
    {
        "entity_id": "sensor.office_temperature",
        "name": "Temperature",
        "domain": "sensor",
        "area": "Office",
        "state": "21",
    },
]


def config(name="Office", entity="light.office"):
    return {
        "views": [
            {
                "title": name,
                "path": "office",
                "type": "sections",
                "max_columns": 2,
                "sections": [{"type": "grid", "cards": [{"type": "tile", "entity": entity}]}],
            }
        ]
    }


class Gateway:
    def __init__(self):
        self.configs = {"dashboard-office": config("Before")}
        self.calls = []
        self.fail_save = False
        self.manager = None

    async def dashboards(self, user):
        return [
            {"url_path": path, "title": "Office", "mode": "storage", "id": path}
            for path in self.configs
        ]

    async def load(self, user, path):
        return deepcopy(self.configs.get(path))

    async def theme_names(self, user):
        return ["default", "Midnight"]

    async def components(self, user):
        return []

    async def call(self, user, command, **fields):
        self.calls.append((command, deepcopy(fields)))
        if command.endswith("/create"):
            path = fields["url_path"]
            self.configs[path] = None
            return {"id": path, "url_path": path}
        if command == "lovelace/config/save":
            # The backup is durable before the first save is attempted.
            assert self.manager.saved
            if self.fail_save:
                raise RuntimeError("HA save failed")
            self.configs[fields["url_path"]] = deepcopy(fields["config"])
        elif command.endswith("/delete"):
            self.configs.pop(fields.get("dashboard_id") or fields.get("url_path"), None)


class StudioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = _Manager()
        self.manager.tater_assistant = tater.MiniTaterRuntime(self.manager)
        self.studio = studio.DashboardStudio(self.manager)
        self.manager.data[studio.STORE_KEY] = {
            "workspaces": {},
            "settings": {
                "base_url": "http://dashboard-model:8000/v1",
                "model": "designer",
                "api_key": "studio-secret",
            },
        }
        self.designer = self.studio.provider
        self.studio.inventory = lambda: deepcopy(INVENTORY)
        self.gateway = Gateway()
        self.gateway.manager = self.manager
        self.studio.gateway = self.gateway
        self.designer.design = AsyncMock(
            return_value={
                "message": "I grouped your Office lights and comfort controls.",
                "title": "Office",
                "config": config(),
                "suggestions": ["Make it simpler", "Optimize it for a tablet"],
            }
        )

    async def design(self, existing=False):
        row = await self.studio.open(USER, url_path="dashboard-office" if existing else None)
        return await self.studio.chat(USER, row["id"], row["revision"], "Design my office")

    async def test_new_design_is_only_a_draft_until_apply(self):
        row = await self.design()
        self.assertTrue(row["is_new"])
        self.assertTrue(row["has_changes"])
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(row["config"], config())
        self.assertEqual(row["suggestions"], ["Make it simpler", "Optimize it for a tablet"])
        self.assertNotIn("tater_conversations", self.manager.data)
        arguments = self.designer.design.call_args
        self.assertEqual(arguments.args[1]["model"], "designer")
        self.assertEqual(arguments.args[2], studio.DESIGN_SCHEMA)
        payload = json.loads(arguments.args[0][-1]["content"])
        self.assertEqual(payload["available_entities"], INVENTORY)
        self.assertNotIn("secret", json.dumps(arguments.args[0]))

    async def test_admin_ownership_and_missing_revision_are_enforced_in_both_modes(self):
        with self.assertRaises(PermissionError):
            await self.studio.open(SimpleNamespace(id="reader", is_admin=False))
        row = await self.design()
        with self.assertRaises(ValueError):
            await self.studio.open(OTHER, workspace_id=row["id"])
        for revision in (None, True, -1, str(row["revision"])):
            with self.assertRaises(studio.StudioConflict):
                await self.studio.apply(USER, row["id"], revision)
        self.manager.data["tater_settings"]["assistant_mode"] = "home_assistant"
        row = await self.studio.chat(USER, row["id"], row["revision"], "Change it")
        self.assertEqual(row["messages"][-2]["content"], "Change it")
        self.assertTrue((await self.studio.snapshot(USER))["model_ready"])
        self.assertEqual(self.gateway.calls, [])

    async def test_studio_connection_is_independent_and_secrets_stay_on_server(self):
        mini_settings = deepcopy(self.manager.data["tater_settings"])
        await self.studio.save_settings(USER, {"api_key": "", "model": "another-designer"})
        self.assertEqual(self.studio.settings()["api_key"], "studio-secret")
        public = await self.studio.snapshot(USER)
        self.assertTrue(public["settings"]["api_key_set"])
        self.assertNotIn("studio-secret", json.dumps(public))
        self.assertNotIn("api_key", public["settings"])
        await self.studio.save_settings(USER, {"clear_api_key": True})
        self.assertFalse(self.studio.public_settings()["api_key_set"])
        self.assertTrue(self.studio.model_ready(self.studio.settings()))  # Local keys optional.
        await self.studio.save_settings(USER, {"base_url": "https://api.openai.com/v1"})
        self.assertFalse((await self.studio.snapshot(USER))["model_ready"])
        self.assertEqual(self.manager.data["tater_settings"], mini_settings)

    async def test_bad_connection_and_failed_storage_preserve_existing_settings(self):
        before = self.studio.settings()
        for url in (
            "ftp://localhost",
            "http://",
            "http://user:key@host",
            "https://host?api_key=secret",
            "https://host/#key",
            "http://host:bad",
        ):
            with self.assertRaises(ValueError):
                await self.studio.save_settings(USER, {"base_url": url})
            self.assertEqual(self.studio.settings(), before)
        with self.assertRaises(PermissionError):
            await self.studio.save_settings(SimpleNamespace(is_admin=False), {"model": "x"})
        self.manager.async_save = AsyncMock(side_effect=RuntimeError("disk full"))
        with self.assertRaisesRegex(RuntimeError, "disk full"):
            await self.studio.save_settings(USER, {"model": "lost"})
        self.assertEqual(self.studio.settings(), before)

    async def test_changing_connection_during_design_does_not_mix_providers(self):
        seen = []

        async def design(messages, settings, schema):
            seen.append(deepcopy(settings))
            if len(seen) == 1:
                await self.studio.save_settings(USER, {"model": "new-model", "api_key": "new-key"})
                return {"message": "Invalid draft", "config": config(entity="light.missing")}
            return {"message": "Repaired", "config": config()}

        self.designer.design.side_effect = design
        await self.design()
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[1]["model"], "designer")
        self.assertEqual(self.studio.settings()["model"], "new-model")

    async def test_saved_design_can_be_resumed_and_is_private(self):
        row = await self.design()
        resumed = studio.DashboardStudio(self.manager)
        self.assertEqual(
            (await resumed.open(USER, workspace_id=row["id"]))["config"], row["config"]
        )
        self.assertEqual((await self.studio.snapshot(OTHER))["workspaces"], [])

    async def test_invalid_entity_is_repaired_before_the_draft_changes(self):
        self.designer.design.side_effect = [
            {"message": "Draft", "config": config(entity="light.invented")},
            {"message": "Here is the corrected design.", "config": config()},
        ]
        row = await self.design()
        self.assertEqual(row["config"], config())
        self.assertEqual(self.designer.design.await_count, 2)
        repair = self.designer.design.call_args.args[0][-1]["content"]
        self.assertIn("Unknown entities", repair)

    async def test_sections_cards_are_nested_without_losing_views_or_options(self):
        proposal = {"views": []}
        for name in ("Home", "Office", "Comfort"):
            view = config(name)["views"][0]
            view["path"] = name.lower()
            view["cards"] = view.pop("sections")[0]["cards"]
            view["badges"] = [{"type": "entity", "entity": "light.office"}]
            proposal["views"].append(view)
        original = deepcopy(proposal)
        self.designer.design.return_value = {"message": "Three views", "config": proposal}
        row = await self.design()
        self.assertEqual(self.designer.design.await_count, 1)
        self.assertEqual(proposal, original)
        self.assertEqual(len(row["config"]["views"]), 3)
        for view in row["config"]["views"]:
            self.assertNotIn("cards", view)
            self.assertEqual(view["sections"][0]["cards"], original["views"][0]["cards"])
            self.assertEqual(view["badges"], original["views"][0]["badges"])
            self.assertEqual(view["max_columns"], 2)
        self.assertEqual(self.gateway.calls, [])

    async def test_three_missing_sections_views_get_concrete_repairs_before_stopping(self):
        incomplete = {
            "views": [
                {"title": title, "path": title.lower(), "type": "sections"}
                for title in ("Home", "Office", "Comfort")
            ]
        }
        self.designer.design.side_effect = [
            {"message": "Outline", "config": incomplete},
            {"message": "Still an outline", "config": incomplete},
            {
                "repairs": [
                    {"view_index": index, "sections": config()["views"][0]["sections"]}
                    for index in range(3)
                ]
            },
        ]
        row = await self.design()
        self.assertEqual(self.designer.design.await_count, 3)
        self.assertEqual(len(row["config"]["views"]), 3)
        for view in row["config"]["views"]:
            self.assertEqual(view["sections"], config()["views"][0]["sections"])
        messages = self.designer.design.call_args.args[0]
        self.assertEqual(len(messages), 2)
        payload = json.loads(messages[-1]["content"])
        self.assertEqual([row["view_index"] for row in payload["views_to_complete"]], [0, 1, 2])
        self.assertEqual(payload["available_entities"], INVENTORY)
        self.assertEqual(self.designer.design.call_args.args[2]["required"], ["repairs"])
        self.assertEqual(self.gateway.calls, [])

    async def test_native_tater_base_output_uses_detailed_view_schema_and_repair(self):
        del self.designer.design  # Exercise the real OpenAI-compatible tool-response parser.
        self.manager.data[studio.STORE_KEY]["settings"]["model"] = "tater/base"
        incomplete = {"views": [{"title": "Office", "type": "sections"}]}

        def completion(proposal):
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "dashboard_design",
                                        "arguments": json.dumps(
                                            {"message": "Office dashboard", "config": proposal}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

        self.designer._post = AsyncMock(side_effect=[completion(incomplete), completion(config())])
        row = await self.design()
        self.assertEqual(row["config"], config())
        self.assertEqual(self.designer._post.await_count, 2)
        payload = self.designer._post.call_args.args[1]
        self.assertEqual(payload["model"], "tater/base")
        view_schema = payload["tools"][0]["function"]["parameters"]["properties"]["config"][
            "properties"
        ]["views"]["items"]
        sections = view_schema["properties"]["sections"]
        self.assertEqual(sections["minItems"], 1)
        self.assertEqual(sections["items"]["required"], ["type", "cards"])
        self.assertIn("type", sections["items"]["properties"]["cards"]["items"]["required"])
        self.assertEqual(self.gateway.calls, [])

    async def test_visual_direction_and_installed_theme_are_saved_in_the_real_config(self):
        row = await self.studio.open(USER)
        themed = config()
        themed["views"][0]["background"] = "linear-gradient(135deg, #111827, #30204a)"
        themed["views"][0]["sections"][0]["background"] = {"color": "#24556c", "opacity": 30}
        self.designer.design.return_value = {"message": "A neon control room.", "config": themed}
        row = await self.studio.chat(
            USER, row["id"], row["revision"], "Make it bold", visual_style="neon", theme="Midnight"
        )
        payload = json.loads(self.designer.design.call_args.args[0][-1]["content"])
        self.assertEqual(payload["visual_direction"], studio.DESIGN_STYLES["neon"])
        self.assertIn("Midnight", payload["available_themes"])
        self.assertEqual(payload["selected_theme"], "Midnight")
        self.assertEqual(row["visual_style"], "neon")
        self.assertEqual(row["theme"], "Midnight")
        self.assertEqual(row["config"]["views"][0]["theme"], "Midnight")
        self.assertEqual(row["config"]["views"][0]["background"], themed["views"][0]["background"])
        self.assertEqual(self.gateway.calls, [])
        row = await self.studio.apply(USER, row["id"], row["revision"])
        self.assertEqual(self.gateway.configs[row["url_path"]], row["config"])
        self.assertEqual(
            (await self.studio.open(USER, workspace_id=row["id"]))["visual_style"], "neon"
        )

    async def test_invalid_visual_choices_never_call_the_model(self):
        row = await self.studio.open(USER)
        for values in (
            {"visual_style": "invented"},
            {"visual_style": {}},
            {"theme": "not-installed"},
            {"theme": {}},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                await self.studio.chat(USER, row["id"], row["revision"], "Restyle", **values)
        self.designer.design.assert_not_awaited()
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)

    async def test_focused_repair_preserves_complete_views_and_rejects_invented_devices(self):
        row = await self.design()
        outline = config("Keep this view")
        outline["views"].append(
            {"title": "New room", "path": "new", "type": "sections", "theme": "Midnight"}
        )
        before = deepcopy(outline)
        for entity in ("light.invented", "light.office"):
            self.designer.design.side_effect = [
                {"message": "Expanded layout", "config": outline},
                {"message": "Expanded layout", "config": outline},
                {
                    "repairs": [
                        {"view_index": 1, "sections": config(entity=entity)["views"][0]["sections"]}
                    ]
                },
            ]
            if entity == "light.invented":
                with self.assertRaisesRegex(ValueError, "Unknown entities"):
                    await self.studio.chat(USER, row["id"], row["revision"], "Add a room")
                self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)
            else:
                updated = await self.studio.chat(USER, row["id"], row["revision"], "Add a room")
                self.assertEqual(updated["config"]["views"][0], before["views"][0])
                self.assertEqual(updated["config"]["views"][1]["theme"], "Midnight")
        self.assertEqual(outline, before)
        self.assertEqual(self.gateway.calls, [])

    async def test_null_repair_cannot_bypass_validation(self):
        row = await self.design()
        self.designer.design.side_effect = [
            {"message": "Draft", "config": config(entity="light.invented")},
            {"message": "Please provide your devices", "config": None},
            {"message": "Discussion", "config": None},
        ]
        with self.assertRaisesRegex(ValueError, "saved draft is unchanged"):
            await self.studio.chat(USER, row["id"], row["revision"], "Change it")
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)

    async def test_original_layout_is_freeform_and_has_no_forced_recipe(self):
        row = await self.studio.open(USER)
        row = await self.studio.chat(
            USER, row["id"], row["revision"], "Surprise me", layout="original"
        )
        payload = json.loads(self.designer.design.call_args.args[0][-1]["content"])
        self.assertEqual(payload["composition_examples"], [])
        self.assertIn("Invent your own", payload["layout_direction"]["brief"])
        self.assertEqual(row["layout"], "original")
        self.assertEqual(row["config"], config())

    async def test_scoped_chat_cannot_change_other_sections_or_views(self):
        row = await self.design()
        stored = self.studio._store()[row["id"]]
        stored["draft"]["views"][0]["sections"].append(
            {"type": "grid", "cards": [{"type": "markdown", "content": "Keep this"}]}
        )
        stored["draft"]["views"].append({**deepcopy(config("Other")["views"][0]), "path": "other"})
        before = deepcopy(stored["draft"])
        changed = config()
        changed["background"] = "unrequested global change"
        changed["views"][0]["theme"] = "Midnight"
        changed["views"][0]["sections"][0]["cards"][0]["name"] = "Renamed light"
        self.designer.design.return_value = {
            "message": "Updated the selected section.",
            "config": changed,
        }
        updated = await self.studio.chat(
            USER,
            row["id"],
            row["revision"],
            "Make this clearer",
            focus={"view_index": 0, "section_index": 0},
        )
        expected = deepcopy(before)
        expected["views"][0]["sections"][0] = changed["views"][0]["sections"][0]
        self.assertEqual(updated["config"], expected)
        payload = json.loads(self.designer.design.call_args.args[0][-1]["content"])
        self.assertEqual(len(payload["current_draft"]["views"]), 1)
        self.assertEqual(len(payload["current_draft"]["views"][0]["sections"]), 1)
        self.assertEqual(self.gateway.calls, [])

    async def test_bad_scope_fails_before_any_model_request(self):
        row = await self.studio.open(USER)
        with self.assertRaises(ValueError):
            await self.studio.chat(
                USER, row["id"], row["revision"], "Change it", focus={"view_index": 1}
            )
        self.designer.design.assert_not_awaited()

    async def test_design_timeout_has_a_clear_error_and_keeps_the_saved_draft(self):
        row = await self.studio.open(USER)
        self.designer.design.side_effect = TimeoutError()
        with self.assertRaisesRegex(ValueError, "reached its time limit"):
            await self.studio.chat(USER, row["id"], row["revision"], "Invent a layout")
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)

    async def test_cancel_closes_only_the_matching_generation_and_preserves_the_draft(self):
        row = await self.studio.open(USER)
        entered, closed = asyncio.Event(), asyncio.Event()

        async def generate(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                closed.set()

        self.designer.design.side_effect = generate
        task = asyncio.create_task(
            self.studio.run_design(
                USER,
                row["id"],
                "first",
                lambda: self.studio.chat(USER, row["id"], 0, "My best dashboard"),
            )
        )
        await entered.wait()
        with self.assertRaises(ValueError):
            self.studio.cancel_design(OTHER, row["id"], "first")
        self.assertFalse(self.studio.cancel_design(USER, row["id"], "another-tab"))
        self.assertFalse(task.done())
        self.assertTrue(self.studio.cancel_design(USER, row["id"], "first"))
        self.assertEqual(await task, {"cancelled": True})
        self.assertTrue(closed.is_set())
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)
        self.assertEqual(self.studio._design_requests, {})
        self.assertEqual(self.gateway.calls, [])

    async def test_cancel_arriving_before_a_design_prevents_it_starting(self):
        row = await self.studio.open(USER)
        self.assertFalse(self.studio.cancel_design(USER, row["id"], "early"))
        operation = AsyncMock()
        result = await self.studio.run_design(USER, row["id"], "early", operation)
        self.assertEqual(result, {"cancelled": True})
        operation.assert_not_awaited()
        for index in range(200):
            self.studio.cancel_design(USER, row["id"], f"cancel-{index}")
        self.assertLessEqual(len(self.studio._cancelled_requests), 128)

    async def test_design_deadline_closes_the_provider_and_releases_its_workspace(self):
        row = await self.studio.open(USER)
        closed = asyncio.Event()

        async def generate(*args, **kwargs):
            try:
                await asyncio.Future()
            finally:
                closed.set()

        self.designer.design.side_effect = generate
        with patch.object(studio, "DESIGN_TIMEOUT_SECONDS", 0.02):
            with self.assertRaisesRegex(ValueError, "10-minute"):
                await self.studio.run_design(
                    USER,
                    row["id"],
                    "deadline",
                    lambda: self.studio.chat(USER, row["id"], 0, "Design"),
                )
        self.assertTrue(closed.is_set())
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)
        self.assertEqual(self.studio._design_requests, {})

    async def test_closed_browser_connection_cancels_generation(self):
        row = await self.studio.open(USER)
        transport = SimpleNamespace(is_closing=lambda: True)

        async def generate(*args, **kwargs):
            await asyncio.Future()

        self.designer.design.side_effect = generate
        result = await self.studio.run_design(
            USER,
            row["id"],
            "disconnect",
            lambda: self.studio.chat(USER, row["id"], 0, "Design"),
            transport=transport,
        )
        self.assertEqual(result, {"cancelled": True})
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), row)

    async def test_cancel_after_generation_does_not_interrupt_saving_a_completed_draft(self):
        row = await self.studio.open(USER)
        saving, finish = asyncio.Event(), asyncio.Event()

        async def save():
            saving.set()
            await finish.wait()

        self.manager.async_save = save
        task = asyncio.create_task(
            self.studio.run_design(
                USER, row["id"], "finishing", lambda: self.studio.chat(USER, row["id"], 0, "Design")
            )
        )
        await saving.wait()
        self.assertFalse(self.studio.cancel_design(USER, row["id"], "finishing"))
        finish.set()
        result = await task
        self.assertEqual(result["workspace"]["config"], config())
        self.assertEqual(self.studio._committing_designs, set())

    async def test_focused_view_cannot_create_a_conflicting_path_in_another_view(self):
        row = await self.design()
        stored = self.studio._store()[row["id"]]
        stored["draft"]["views"].append({**deepcopy(config("Other")["views"][0]), "path": "other"})
        before = deepcopy(stored["draft"])
        proposal = config()
        proposal["views"][0]["path"] = "other"
        self.designer.design.return_value = {"message": "Changed view", "config": proposal}
        with self.assertRaisesRegex(ValueError, "conflicts with the surrounding dashboard"):
            await self.studio.chat(
                USER, row["id"], row["revision"], "Change this view", focus={"view_index": 0}
            )
        self.assertEqual(stored["draft"], before)

    async def test_concepts_are_distinct_saved_drafts_until_explicitly_chosen_and_applied(self):
        row = await self.studio.open(USER)
        initial = deepcopy(row["config"])
        layouts = [item["example"] for item in studio.layout_examples(INVENTORY, "auto")]
        self.designer.design.side_effect = [
            {
                "message": "A new layout.",
                "design_intent": "A different composition.",
                "config": candidate,
            }
            for candidate in layouts
        ]
        for index in range(3):
            row = await self.studio.concept(
                USER, row["id"], row["revision"], index, "Three different ideas"
            )
            self.assertEqual(row["config"], initial)
            self.assertEqual(len(row["concepts"]), index + 1)
        self.assertEqual(
            len({studio.composition_signature(idea["config"]) for idea in row["concepts"]}), 3
        )
        resumed = await self.studio.open(USER, workspace_id=row["id"])
        self.assertEqual(resumed["concepts"], row["concepts"])
        self.assertEqual(self.gateway.calls, [])
        chosen = await self.studio.choose_concept(
            USER, row["id"], row["revision"], row["concepts"][1]["id"]
        )
        self.assertEqual(chosen["config"], layouts[1])
        self.assertTrue(chosen["can_undo_draft"])
        self.assertEqual(chosen["layout"], "editorial")
        self.assertEqual(self.gateway.calls, [])
        undone = await self.studio.undo(USER, row["id"], chosen["revision"])
        self.assertEqual(undone["config"], initial)

    async def test_a_recolored_duplicate_is_repaired_without_losing_the_first_concept(self):
        row = await self.studio.open(USER)
        row = await self.studio.concept(USER, row["id"], row["revision"], 0)
        before = deepcopy(row)
        self.designer.design.return_value = {
            "message": "Same cards, different colors.",
            "config": studio.apply_visual_direction(config(), "neon", ""),
        }
        with self.assertRaisesRegex(ValueError, "repeats another concept"):
            await self.studio.concept(USER, row["id"], row["revision"], 1)
        self.assertEqual(await self.studio.open(USER, workspace_id=row["id"]), before)
        self.assertEqual(self.designer.design.await_count, 4)
        with self.assertRaises(studio.StudioConflict):
            await self.studio.concept(USER, row["id"], row["revision"], 2)
        with self.assertRaises(ValueError):
            await self.studio.choose_concept(USER, row["id"], row["revision"], "not-an-idea")
        with self.assertRaises(ValueError):
            await self.studio.choose_concept(
                OTHER, row["id"], row["revision"], row["concepts"][0]["id"]
            )
        self.assertEqual(self.gateway.calls, [])

    async def test_only_verified_component_guidance_reaches_the_model_and_custom_draft_applies(
        self,
    ):
        self.gateway.components = AsyncMock(
            return_value=studio.installed_components(
                [
                    {
                        "type": "module",
                        "url": "/hacsfiles/lovelace-mushroom/mushroom.js?private_resource_token=hidden",
                    },
                    {"type": "module", "url": "/hacsfiles/lovelace-card-mod/card-mod.js"},
                ]
            )
        )
        row = await self.studio.open(USER)
        proposal = config()
        card = proposal["views"][0]["sections"][0]["cards"][0]
        card.update(
            type="custom:mushroom-entity-card",
            card_mod={"style": "ha-card { border-radius: 24px; }"},
        )
        self.designer.design.return_value = {
            "message": "Uses your installed cards.",
            "config": proposal,
        }
        row = await self.studio.chat(USER, row["id"], row["revision"], "Use my installed cards")
        payload = json.loads(self.designer.design.call_args.args[0][-1]["content"])
        self.assertEqual(len(payload["available_components"]), 2)
        self.assertNotIn("private_resource_token", json.dumps(payload))
        self.assertEqual(self.gateway.calls, [])
        applied = await self.studio.apply(USER, row["id"], row["revision"])
        self.assertEqual(self.gateway.configs[applied["url_path"]], proposal)

    async def test_failed_design_preserves_the_previous_draft_and_history(self):
        row = await self.design()
        self.designer.design.return_value = {
            "message": "Bad draft",
            "config": config(entity="light.invented"),
        }
        with self.assertRaisesRegex(ValueError, "saved draft is unchanged"):
            await self.studio.chat(USER, row["id"], row["revision"], "Change it")
        self.assertEqual((await self.studio.open(USER, workspace_id=row["id"])), row)
        self.assertEqual(self.designer.design.await_count, 1 + studio.MAX_DESIGN_ATTEMPTS)

    async def test_ambiguous_cards_get_card_specific_model_repair(self):
        incomplete = config()
        incomplete["views"][0]["sections"][0]["cards"] = [{"name": "Office"}]
        self.designer.design.side_effect = [
            {"message": "Draft", "config": incomplete},
            {"message": "Typed cards", "config": config()},
        ]
        row = await self.design()
        self.assertEqual(row["config"], config())
        self.assertEqual(self.designer.design.await_count, 2)
        feedback = self.designer.design.call_args.args[0][-1]["content"]
        self.assertIn("Card 1 needs a card type", feedback)
        self.assertIn("including nested grids/stacks", feedback)
        self.assertEqual(self.gateway.calls, [])

    async def test_discussion_does_not_replace_the_draft(self):
        row = await self.design()
        self.designer.design.return_value = {
            "message": "Would you prefer a room or task layout?",
            "config": None,
        }
        updated = await self.studio.chat(USER, row["id"], row["revision"], "What are my options?")
        self.assertEqual(updated["config"], row["config"])
        self.assertIn("room or task", updated["messages"][-1]["content"])

    async def test_edit_apply_and_restore_use_normal_ha_commands(self):
        row = await self.design(existing=True)
        row = await self.studio.apply(USER, row["id"], row["revision"])
        self.assertFalse(row["has_changes"])
        self.assertTrue(row["can_undo_apply"])
        self.assertEqual(self.gateway.configs["dashboard-office"], config())
        with self.assertRaisesRegex(ValueError, "no draft changes"):
            await self.studio.apply(USER, row["id"], row["revision"])
        restored = await self.studio.undo(USER, row["id"], row["revision"], applied=True)
        self.assertEqual(restored["config"], config("Before"))
        self.assertEqual(self.gateway.configs["dashboard-office"], config("Before"))

    async def test_new_apply_registers_dashboard_and_undo_removes_it(self):
        row = await self.design()
        row = await self.studio.apply(USER, row["id"], row["revision"])
        self.assertEqual(row["url_path"], "dashboard-office-" + row["id"][:6])
        self.assertFalse(row["is_new"])
        self.assertEqual(self.gateway.calls[0][0], "lovelace/dashboards/create")
        row = await self.studio.undo(USER, row["id"], row["revision"], applied=True)
        self.assertTrue(row["is_new"])
        self.assertEqual(row["config"], {"views": []})
        self.assertEqual(list(self.gateway.configs), ["dashboard-office"])

    async def test_external_edits_block_apply_and_restore(self):
        row = await self.design(existing=True)
        self.gateway.configs["dashboard-office"] = config("Changed in HA")
        with self.assertRaises(studio.StudioConflict):
            await self.studio.apply(USER, row["id"], row["revision"])
        self.assertEqual(self.gateway.calls, [])
        self.gateway.configs["dashboard-office"] = config("Before")
        row = await self.studio.apply(USER, row["id"], row["revision"])
        self.gateway.configs["dashboard-office"] = config("Another HA edit")
        with self.assertRaises(studio.StudioConflict):
            await self.studio.undo(USER, row["id"], row["revision"], applied=True)
        self.assertEqual(self.gateway.configs["dashboard-office"], config("Another HA edit"))

    async def test_two_designs_cannot_publish_over_each_other(self):
        first = await self.design(existing=True)
        second = await self.design(existing=True)
        original_load = self.gateway.load

        async def slow_load(*args):
            value = await original_load(*args)
            await asyncio.sleep(0)
            return value

        self.gateway.load = slow_load
        results = await asyncio.gather(
            self.studio.apply(USER, first["id"], first["revision"]),
            self.studio.apply(USER, second["id"], second["revision"]),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(value, studio.StudioConflict) for value in results), 1)
        self.assertEqual(
            sum(command == "lovelace/config/save" for command, _ in self.gateway.calls), 1
        )

    async def test_save_failure_removes_new_empty_dashboard_but_keeps_draft(self):
        row = await self.design()
        self.gateway.fail_save = True
        with self.assertRaisesRegex(RuntimeError, "HA save failed"):
            await self.studio.apply(USER, row["id"], row["revision"])
        updated = await self.studio.open(USER, workspace_id=row["id"])
        self.assertTrue(updated["is_new"])
        self.assertTrue(updated["has_changes"])
        self.assertFalse(updated["can_undo_apply"])
        self.assertEqual(list(self.gateway.configs), ["dashboard-office"])

    async def test_backup_storage_failure_never_writes_to_ha(self):
        row = await self.design(existing=True)
        self.manager.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
        with self.assertRaises(OSError):
            await self.studio.apply(USER, row["id"], row["revision"])
        self.assertEqual(self.gateway.calls, [])
        self.assertFalse((await self.studio.open(USER, workspace_id=row["id"]))["can_undo_apply"])

    async def test_draft_undo_and_chat_races_preserve_revision_order(self):
        row = await self.design()
        outcomes = await asyncio.gather(
            *[self.studio.chat(USER, row["id"], row["revision"], "Simplify it") for _ in range(2)],
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(item, studio.StudioConflict) for item in outcomes), 1)
        row = await self.studio.open(USER, workspace_id=row["id"])
        row = await self.studio.undo(USER, row["id"], row["revision"])
        self.assertEqual(row["config"], {"views": []})
        self.assertEqual(self.gateway.calls, [])

    async def test_removing_studio_work_never_deletes_a_live_dashboard(self):
        row = await self.design(existing=True)
        await self.studio.remove(USER, row["id"], row["revision"])
        self.assertEqual(self.gateway.calls, [])
        self.assertIn("dashboard-office", self.gateway.configs)

    async def test_yaml_dashboard_is_rejected_without_a_write(self):
        self.gateway.dashboards = AsyncMock(
            return_value=[{"url_path": "yaml-home", "title": "YAML", "mode": "yaml"}]
        )
        with self.assertRaisesRegex(ValueError, "YAML"):
            await self.studio.open(USER, url_path="yaml-home")
        self.assertEqual(self.gateway.calls, [])


class ValidationTests(unittest.TestCase):
    def test_native_palette_is_visible_even_when_the_model_ignores_the_style_brief(self):
        source = config()
        appearances = []
        for style in studio.STYLE_PALETTES:
            themed = studio.apply_visual_direction(source, style, "")
            view = themed["views"][0]
            appearances.append(view["background"])
            self.assertIn("var(--primary-background-color)", view["background"])
            self.assertIn("color", view["sections"][0]["cards"][0])
            self.assertIn("background", view["sections"][0])
            self.assertEqual(studio.validate_config(themed, {"light.office"}), [])
        self.assertEqual(len(set(appearances)), len(studio.STYLE_PALETTES))
        self.assertEqual(source, config())
        self.assertEqual(studio.apply_visual_direction(source, "auto", ""), source)

    def test_native_palette_keeps_model_colors_images_and_view_options(self):
        source = config()
        view = source["views"][0]
        view["background"] = {"image": "/local/my-home.jpg", "opacity": 30}
        view["theme"] = "Existing theme"
        view["sections"][0]["background"] = {"color": "#123456", "opacity": 22}
        view["sections"][0]["cards"][0]["color"] = "amber"
        themed = studio.apply_visual_direction(source, "neon", "")
        self.assertEqual(themed, source)

    def test_switching_direction_replaces_the_previous_default_palette(self):
        natural = studio.apply_visual_direction(config(), "natural", "")
        neon = studio.apply_visual_direction(natural, "neon", "", previous_style="natural")
        self.assertNotEqual(natural["views"][0]["background"], neon["views"][0]["background"])
        self.assertEqual(
            neon["views"][0]["sections"][0]["cards"][0]["color"], studio.STYLE_PALETTES["neon"][0]
        )
        self.assertEqual(
            natural["views"][0]["sections"][0]["cards"][0]["color"],
            studio.STYLE_PALETTES["natural"][0],
        )

    def test_focused_repairs_must_cover_exactly_the_missing_views_with_content(self):
        outline = {
            "views": [{"type": "sections", "path": "one"}, {"type": "sections", "path": "two"}]
        }
        section = config()["views"][0]["sections"]
        for repairs in (
            [],
            [{"view_index": 0, "sections": section}],
            [{"view_index": 0, "sections": section}, {"view_index": 0, "sections": section}],
            [{"view_index": 0, "sections": section}, {"view_index": 9, "sections": section}],
            [{"view_index": 0, "sections": section}, {"view_index": True, "sections": section}],
            [
                {"view_index": 0, "sections": section},
                {"view_index": 1, "sections": [{"type": "grid", "cards": []}]},
            ],
        ):
            with self.subTest(repairs=repairs):
                self.assertEqual(
                    studio.merge_section_repairs(outline, {"repairs": repairs}, [0, 1]), outline
                )

    def test_themes_must_be_installed_or_preserved_from_the_original(self):
        themed = config()
        themed["views"][0]["theme"] = "Imagined"
        self.assertTrue(
            studio.validate_config(themed, {"light.office"}, available_themes=["default"])
        )
        self.assertEqual(
            studio.validate_config(
                themed, {"light.office"}, original=themed, available_themes=["default"]
            ),
            [],
        )
        self.assertEqual(
            studio.validate_config(themed, {"light.office"}, available_themes=["Imagined"]), []
        )

    def test_missing_types_in_nested_cards_are_repaired_without_rewriting_entity_rows(self):
        proposed = config()
        rows = [{"entity": "light.office", "name": "Keep this row"}]
        tap = {"action": "more-info"}
        proposed["views"][0]["sections"][0]["cards"] = [
            {
                "cards": [
                    "light.office",
                    {
                        "entity": "sensor.office_temperature",
                        "name": "Temperature",
                        "tap_action": tap,
                    },
                    {"heading": "Office"},
                    {"entities": rows},
                    {"content": "A comfortable room"},
                ]
            }
        ]
        original = deepcopy(proposed)
        fixed = studio.normalize_config(proposed)
        grid = fixed["views"][0]["sections"][0]["cards"][0]
        self.assertEqual(grid["type"], "grid")
        cards = grid["cards"]
        self.assertEqual(
            [card["type"] for card in cards], ["tile", "tile", "heading", "entities", "markdown"]
        )
        self.assertEqual(cards[0]["entity"], "light.office")
        self.assertEqual(cards[1]["tap_action"], tap)
        self.assertEqual(cards[3]["entities"], rows)
        self.assertNotIn("type", cards[3]["entities"][0])
        self.assertEqual(proposed, original)
        self.assertEqual(
            studio.validate_config(fixed, {item["entity_id"] for item in INVENTORY}), []
        )

    def test_ambiguous_missing_card_types_are_not_guessed(self):
        for card in (
            {},
            {"name": "Office"},
            {"entity": "light.office", "content": "text"},
            {"entity": "light.office", "camera_image": "camera.office"},
        ):
            proposed = config()
            proposed["views"][0]["sections"][0]["cards"] = [card]
            fixed = studio.normalize_config(proposed)
            self.assertEqual(fixed, proposed)
            self.assertTrue(
                any(
                    "card type" in error
                    for error in studio.validate_config(fixed, {"light.office"})
                )
            )

    def test_normalization_preserves_section_options_and_all_card_content(self):
        proposal = config()
        view = proposal["views"][0]
        section = view["sections"][0]
        section.pop("type")
        section["visibility"] = [{"condition": "state", "entity": "light.office", "state": "on"}]
        view["sections"] = section  # One section instead of a list.
        view["cards"] = [{"type": "tile", "entity": "sensor.office_temperature"}]
        normalized = studio.normalize_config(proposal)
        self.assertEqual(len(normalized["views"][0]["sections"]), 2)
        self.assertEqual(normalized["views"][0]["sections"][0]["visibility"], section["visibility"])
        self.assertEqual(normalized["views"][0]["sections"][0]["cards"], section["cards"])
        self.assertEqual(normalized["views"][0]["sections"][1]["cards"], view["cards"])
        self.assertEqual(
            studio.validate_config(normalized, {row["entity_id"] for row in INVENTORY}), []
        )

    def test_normalization_does_not_invent_content_or_weaken_entity_validation(self):
        empty = {"views": [{"type": "sections", "sections": []}]}
        self.assertEqual(studio.normalize_config(empty), empty)
        self.assertTrue(studio.validate_config(studio.normalize_config(empty), set()))
        malformed = {
            "views": [
                {
                    "type": "sections",
                    "sections": "bad",
                    "cards": [{"type": "tile", "entity": "light.office"}],
                }
            ]
        }
        self.assertEqual(studio.normalize_config(malformed), malformed)
        self.assertTrue(
            studio.validate_config(studio.normalize_config(malformed), {"light.office"})
        )
        unknown = {
            "views": [{"type": "sections", "cards": [{"type": "tile", "entity": "light.invented"}]}]
        }
        self.assertTrue(
            any(
                "Unknown entities" in error
                for error in studio.validate_config(studio.normalize_config(unknown), set())
            )
        )

    def test_native_sections_unknown_entities_and_custom_cards(self):
        ids = {"light.office"}
        self.assertEqual(studio.validate_config(config(), ids), [])
        self.assertIn(
            "Unknown entities", studio.validate_config(config(entity="light.missing"), ids)[0]
        )
        bad = config()
        bad["views"][0]["sections"][0]["cards"][0]["type"] = "custom:invented"
        self.assertIn("unverified", studio.validate_config(bad, ids)[0])
        self.assertEqual(studio.validate_config(bad, ids, bad), [])

    def test_bad_sections_duplicate_paths_non_finite_and_executable_urls(self):
        bad = {"views": [{"type": "sections", "cards": [{"type": "tile"}]}]}
        self.assertTrue(studio.validate_config(bad, set()))
        bad = config()
        bad["views"].append(deepcopy(bad["views"][0]))
        self.assertTrue(
            any("unique" in error for error in studio.validate_config(bad, {"light.office"}))
        )
        self.assertTrue(studio.validate_config({"views": [], "value": float("nan")}, set()))
        bad = config()
        bad["views"][0]["sections"][0]["cards"][0]["url"] = "javascript:alert(1)"
        self.assertTrue(
            any("executable" in error for error in studio.validate_config(bad, {"light.office"}))
        )

    def test_new_card_types_and_wrong_domain_are_rejected(self):
        bad = config()
        card = bad["views"][0]["sections"][0]["cards"][0]
        card["type"] = "thermostat"
        self.assertTrue(
            any(
                "climate entity" in error for error in studio.validate_config(bad, {"light.office"})
            )
        )
        card["type"] = "imaginary-dashboard-card"
        self.assertTrue(
            any(
                "Unsupported new" in error
                for error in studio.validate_config(bad, {"light.office"})
            )
        )


class CachedJsonFragment:
    """Opaque HA response whose data must cross the JSON boundary, not deepcopy."""

    def __init__(self, value):
        self.json = json.dumps(value, ensure_ascii=False)

    def __deepcopy__(self, memo):
        raise TypeError("cannot pickle 'orjson.Fragment' object")


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        def encode(value):
            def default(item):
                if isinstance(item, CachedJsonFragment):
                    return json.loads(item.json)
                raise TypeError("Unsupported JSON value")

            return json.dumps(value, default=default, ensure_ascii=False).encode()

        self.enterContext(
            patch.dict(
                "sys.modules",
                {
                    "homeassistant.core": SimpleNamespace(Context=lambda **kwargs: kwargs),
                    "homeassistant.helpers.json": SimpleNamespace(json_bytes=encode),
                },
            )
        )

    async def test_registered_schema_and_requesting_admin_are_used(self):
        seen = []

        def schema(message):
            self.assertEqual(message["type"], "lovelace/dashboards/create")
            return {**message, "mode": "storage"}

        def handler(hass, connection, message):
            seen.append((connection.user, message))
            connection.send_result(message["id"], {"id": "dashboard-office"})

        gateway = studio.LovelaceGateway(
            SimpleNamespace(
                data={
                    "websocket_api": {
                        "lovelace/dashboards/create": (handler, schema),
                    }
                }
            )
        )
        result = await gateway.call(
            USER, "lovelace/dashboards/create", title="Office", url_path="dashboard-office"
        )
        self.assertEqual(result["id"], "dashboard-office")
        self.assertIs(seen[0][0], USER)
        self.assertEqual(seen[0][1]["mode"], "storage")
        with self.assertRaises(ValueError):
            await gateway.call(USER, "call_service", domain="light")
        with self.assertRaises(PermissionError):
            await gateway.call(SimpleNamespace(is_admin=False), "lovelace/config")

    async def test_installed_themes_are_read_without_global_theme_changes(self):
        def handler(hass, connection, message):
            self.assertIs(connection.user, USER)
            self.assertEqual(message["type"], "frontend/get_themes")
            connection.send_result(
                message["id"],
                {
                    "themes": {"Midnight": {"primary-color": "#123456"}, "Warm": {}},
                    "default_theme": "Warm",
                },
            )

        gateway = studio.LovelaceGateway(
            SimpleNamespace(data={"websocket_api": {"frontend/get_themes": (handler, False)}})
        )
        self.assertEqual(await gateway.theme_names(USER), ["Midnight", "Warm", "default"])
        gateway.hass.data.clear()
        self.assertEqual(await gateway.theme_names(USER), ["default"])

    async def test_ha_errors_and_async_commands_reach_the_caller(self):
        async def handler(hass, connection, message):
            connection.send_error(message["id"], "config_not_found", "No config found")

        gateway = studio.LovelaceGateway(
            SimpleNamespace(
                data={
                    "websocket_api": {
                        "lovelace/config": (handler, False),
                    }
                }
            )
        )
        self.assertIsNone(await gateway.load(USER, "missing"))

    async def test_existing_overview_opens_with_cached_and_nested_json_fragments(self):
        original = config("Caf\u00e9")
        original["views"][0]["theme"] = "My theme"
        strategy = {"strategy": {"type": "original-states", "hide_entities_without_area": True}}
        for response, expected in (
            (CachedJsonFragment(original), original),
            ({"views": [CachedJsonFragment(original["views"][0])]}, original),
            (original, original),
            (CachedJsonFragment(strategy), strategy),
        ):
            with self.subTest(response=type(response).__name__, strategy="strategy" in expected):
                manager = _Manager()
                designer = studio.DashboardStudio(manager)

                def list_dashboards(hass, connection, message):
                    connection.send_result(
                        message["id"],
                        [
                            {
                                "url_path": "lovelace",
                                "title": "Overview",
                                "mode": "storage",
                                "id": "lovelace",
                            }
                        ],
                    )

                async def load(hass, connection, message):
                    self.assertEqual(message["url_path"], "lovelace")
                    connection.send_result(message["id"], response)

                designer.gateway = studio.LovelaceGateway(
                    SimpleNamespace(
                        data={
                            "websocket_api": {
                                "lovelace/dashboards/list": (list_dashboards, False),
                                "lovelace/config": (load, False),
                            }
                        }
                    )
                )
                opened = await designer.open(USER, url_path="lovelace")
                self.assertEqual(opened["config"], expected)
                self.assertFalse(opened["has_changes"])
                stored = designer._store()[opened["id"]]
                self.assertEqual(stored["base"], expected)
                self.assertEqual(stored["base_hash"], studio.config_hash(expected))
                self.assertEqual(json.loads(json.dumps(opened))["config"], expected)
                opened["config"]["extra"] = "draft edit"
                self.assertNotIn("extra", stored["base"])
                self.assertNotIn("extra", expected)

    async def test_save_acknowledgements_and_plain_results_are_independent_json(self):
        source = {"views": [{"title": "Original"}]}

        def handler(hass, connection, message):
            connection.send_result(
                message["id"], source if message["type"] == "lovelace/config" else None
            )

        gateway = studio.LovelaceGateway(
            SimpleNamespace(
                data={
                    "websocket_api": {
                        "lovelace/config": (handler, False),
                        "lovelace/config/save": (handler, False),
                    }
                }
            )
        )
        result = await gateway.load(USER, "lovelace")
        result["views"][0]["title"] = "Edited"
        self.assertEqual(source["views"][0]["title"], "Original")
        self.assertIsNone(await gateway.call(USER, "lovelace/config/save", config=source))

    async def test_invalid_json_response_fails_without_waiting_for_a_timeout(self):
        def handler(hass, connection, message):
            connection.send_result(message["id"], object())

        gateway = studio.LovelaceGateway(
            SimpleNamespace(
                data={
                    "websocket_api": {
                        "lovelace/config": (handler, False),
                    }
                }
            )
        )
        with self.assertRaisesRegex(RuntimeError, "invalid dashboard response"):
            await asyncio.wait_for(gateway.load(USER, "lovelace"), timeout=0.1)


if __name__ == "__main__":
    unittest.main()
