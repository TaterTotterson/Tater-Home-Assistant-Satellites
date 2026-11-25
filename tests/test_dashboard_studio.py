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

    async def test_failed_design_preserves_the_previous_draft_and_history(self):
        row = await self.design()
        self.designer.design.return_value = {
            "message": "Bad draft",
            "config": config(entity="light.invented"),
        }
        with self.assertRaisesRegex(ValueError, "another revision"):
            await self.studio.chat(USER, row["id"], row["revision"], "Change it")
        self.assertEqual((await self.studio.open(USER, workspace_id=row["id"])), row)

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


class GatewayTests(unittest.IsolatedAsyncioTestCase):
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
        with patch.dict(
            "sys.modules", {"homeassistant.core": SimpleNamespace(Context=lambda **kwargs: kwargs)}
        ):
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
        with patch.dict(
            "sys.modules", {"homeassistant.core": SimpleNamespace(Context=lambda **kwargs: kwargs)}
        ):
            self.assertIsNone(await gateway.load(USER, "missing"))


if __name__ == "__main__":
    unittest.main()
