"""Exercise confirmed firmware writes and HA registry edits together."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from test_room_area_sync import DOMAIN, IDENTITY, FakeRuntime, build_manager, device_event


class LiveRuntime(FakeRuntime):
    name = property(lambda self: self.record["name"])
    capabilities = property(lambda self: self.record["capabilities"])


class SatelliteIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager, self.devices, self.areas = build_manager()
        self.areas.add("office", "Office")
        self.areas.add("kitchen", "Kitchen")
        self.device = self.devices.add("sat-1", "reg-1", "office")
        self.device.name = "Office Echo"
        self.device.name_by_user = None
        self.runtime = LiveRuntime(device_id="sat-1", record={"name": "Office Echo", "room": "Office", "token_hash": "pairing-kept", "capabilities": {"identity_update": True}}, connected=True, identity_lock=asyncio.Lock(), notify=Mock(), add_log=Mock(), last_error="")
        self.runtime.public_snapshot = lambda: dict(self.runtime.record)
        self.manager.runtimes["sat-1"] = self.runtime
        self.runtime.async_request = AsyncMock(return_value={"ok": True, "device_name": "Kitchen Echo", "room": "Kitchen"})
        self.tasks = []
        def create_task(coro):
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task
        self.manager.hass.async_create_task = create_task

    async def test_bridge_save_waits_for_firmware_then_updates_ha(self):
        observed = []
        async def confirm(*args, **kwargs):
            observed.append((self.runtime.name, self.runtime.room, self.device.area_id))
            return {"ok": True, "device_name": "Kitchen Echo", "room": "Kitchen"}
        self.runtime.async_request.side_effect = confirm
        await self.manager.async_set_device_identity("sat-1", {"device_name": "Kitchen Echo", "room": "Kitchen"})
        self.assertEqual(observed, [("Office Echo", "Office", "office")])
        self.assertEqual((self.runtime.name, self.runtime.room, self.device.name, self.device.area_id), ("Kitchen Echo", "Kitchen", "Kitchen Echo", "kitchen"))
        self.assertEqual(self.runtime.record["token_hash"], "pairing-kept")
        self.assertEqual(self.runtime.device_id, "sat-1")

    async def test_native_ha_device_name_and_area_edits_save_on_satellite(self):
        self.device.name_by_user = "Kitchen Echo"
        self.device.area_id = "kitchen"
        self.manager._async_device_registry_updated(device_event("update", "reg-1", {"name_by_user": None, "area_id": "office"}))
        await asyncio.gather(*self.tasks)
        self.runtime.async_request.assert_awaited_once_with("identity.set", {"device_name": "Kitchen Echo", "room": "Kitchen"}, timeout=10.0)
        self.assertEqual((self.runtime.name, self.runtime.room), ("Kitchen Echo", "Kitchen"))
        self.tasks.clear()
        self.manager._async_device_registry_updated(device_event("update", "reg-1", {"name_by_user": "Office Echo", "area_id": "office"}))
        self.assertEqual(self.tasks, [])  # Our confirmed registry updates cannot loop.

    async def test_failed_ha_edit_restores_confirmed_identity(self):
        self.device.name_by_user, self.device.area_id = "Kitchen Echo", "kitchen"
        self.runtime.async_request.return_value = {"ok": False, "error": "disk full"}
        self.manager._async_device_registry_updated(device_event("update", "reg-1", {"name_by_user": None, "area_id": "office"}))
        await asyncio.gather(*self.tasks)
        self.assertEqual((self.runtime.name, self.runtime.room, self.device.name_by_user, self.device.area_id), ("Office Echo", "Office", "Office Echo", "office"))
        self.manager.async_save.assert_not_awaited()

    async def test_timeout_offline_and_old_firmware_cannot_report_success(self):
        values = {"device_name": "Kitchen Echo", "room": "Kitchen"}
        self.runtime.async_request.side_effect = TimeoutError()
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            await self.manager.async_set_device_identity("sat-1", values)
        self.runtime.connected = False
        with self.assertRaisesRegex(RuntimeError, "Connect"):
            await self.manager.async_set_device_identity("sat-1", values)
        self.runtime.record["capabilities"] = {}
        with self.assertRaisesRegex(ValueError, "firmware"):
            await self.manager.async_set_device_identity("sat-1", values)
        self.assertEqual(self.runtime.name, "Office Echo")

    async def test_clearing_room_is_persisted_and_unassigns_area(self):
        self.runtime.async_request.return_value = {"ok": True, "device_name": "Office Echo", "room": ""}
        await self.manager.async_set_device_identity("sat-1", {"device_name": "Office Echo", "room": ""})
        self.assertEqual(self.runtime.room, "")
        self.assertIsNone(self.device.area_id)

    async def test_renaming_ha_area_updates_firmware_room(self):
        self.areas.areas["office"].name = "Studio"
        self.runtime.async_request.return_value = {"ok": True, "device_name": "Office Echo", "room": "Studio"}
        self.manager._async_area_registry_updated(SimpleNamespace(data={"action": "update", "area_id": "office"}))
        await asyncio.gather(*self.tasks)
        self.assertEqual(self.runtime.room, "Studio")
        self.runtime.async_request.assert_awaited_once_with("identity.set", {"device_name": "Office Echo", "room": "Studio"}, timeout=10.0)

    async def test_validation_uses_bytes_and_rejects_control_characters(self):
        for bad in (None, 42, "", "   ", "a\nname", "é" * 32):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                IDENTITY.identity_text(bad, required=True)
        self.assertEqual(IDENTITY.identity_text(" Écho ", required=True), "Écho")

    async def test_reconnecting_after_another_controller_rename_refreshes_ha(self):
        self.device.name_by_user = "Office Echo"
        await self.manager._update_record_from_hello(self.runtime, {"device_name": "Kitchen Echo", "room": "Kitchen"})
        self.assertEqual((self.device.name, self.device.name_by_user, self.device.area_id), ("Kitchen Echo", "Kitchen Echo", "kitchen"))

    async def test_quick_separate_ha_edits_keep_both_new_values(self):
        async def confirm(kind, values, **kwargs):
            await asyncio.sleep(0)
            return {"ok": True, **values}
        self.runtime.async_request.side_effect = confirm
        self.device.name_by_user = "Kitchen Echo"
        self.manager._async_device_registry_updated(device_event("update", "reg-1", {"name_by_user": None}))
        self.device.area_id = "kitchen"
        self.manager._async_device_registry_updated(device_event("update", "reg-1", {"area_id": "office"}))
        await asyncio.gather(*self.tasks)
        self.assertEqual((self.runtime.name, self.runtime.room), ("Kitchen Echo", "Kitchen"))

    async def test_case_insensitive_area_matching_does_not_send_an_identity_edit(self):
        self.runtime.record["room"] = "office"
        self.manager._async_device_registry_updated(device_event("update", "reg-1", {"area_id": None}))
        self.assertEqual(self.tasks, [])

    async def test_late_confirmation_reconciles_identity_and_clears_failed_edit(self):
        self.runtime.resolve_request = Mock(return_value=False)
        self.runtime.last_error = "Name and room were not confirmed: timeout"
        await self.manager._handle_text_message(self.runtime, {"type": "identity.result", "payload": {"reply_to": "expired", "ok": True, "device_name": "Kitchen Echo", "room": "Kitchen"}})
        self.assertEqual((self.runtime.name, self.runtime.room, self.device.name, self.device.area_id), ("Kitchen Echo", "Kitchen", "Kitchen Echo", "kitchen"))
        self.assertEqual(self.runtime.last_error, "")

    async def test_malformed_confirmation_cannot_mutate_confirmed_identity(self):
        self.runtime.resolve_request = Mock(return_value=True)
        await self.manager._handle_text_message(self.runtime, {"type": "identity.result", "payload": {"reply_to": "req-1", "ok": True, "device_name": 42, "room": "Kitchen"}})
        self.assertEqual((self.runtime.name, self.runtime.room), ("Office Echo", "Office"))
        self.manager.async_save.assert_not_awaited()

    async def test_new_entity_defaults_do_not_duplicate_the_room_prefix(self):
        self.runtime.record["name"] = "Living Room Echo"
        self.runtime.created_platforms = set()
        entity = SimpleNamespace(unique_id="sat-1_media_player", entity_id=None)
        existing = SimpleNamespace(unique_id="sat-1_existing", entity_id="media_player.my_custom_name")
        added = Mock()
        self.manager._platforms = {"media_player": (lambda runtime: [entity, existing], added)}
        self.manager._add_runtime_platform(self.runtime, "media_player")
        self.assertEqual(entity.entity_id, "media_player.living_room_echo_media_player")
        self.assertEqual(entity.unique_id, "sat-1_media_player")
        self.assertEqual(existing.entity_id, "media_player.my_custom_name")
        added.assert_called_once_with([entity, existing])
