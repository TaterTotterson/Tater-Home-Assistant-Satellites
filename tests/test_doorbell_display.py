"""Camera popup ownership, expiry, and ordinary camera navigation."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib.util
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/tater_satellite"
spec = importlib.util.spec_from_file_location("doorbell_display_payloads", ROOT / "display_payloads.py")
payloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payloads)
source = ast.parse((ROOT / "display_panels.py").read_text())
nodes = [node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "TaterDisplayPanelCoordinator"]
scope = {"asyncio": asyncio, "contextlib": contextlib, "time": time,
         "supports_display_cameras": payloads.supports_display_cameras,
         "cameras_payload": payloads.cameras_payload,
         "DISPLAY_PANEL_MESSAGES": {"display.cameras.open", "display.camera.select", "display.camera.close"},
         "_text": lambda value: str(value or "").strip()}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])), "<display coordinator>", "exec"), scope)
Coordinator = scope["TaterDisplayPanelCoordinator"]


class DoorbellDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = SimpleNamespace(hass=SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: SimpleNamespace(state="idle"))),
            entry=SimpleNamespace(async_create_background_task=lambda hass, coro, name: asyncio.create_task(coro, name=name)))
        self.coordinator = Coordinator(self.manager)
        self.runtime = SimpleNamespace(device_id="rook", connected=True, capabilities={"screen_cameras": True, "screen_camera_popup_version": 1}, async_send=AsyncMock(return_value=True))
        self.coordinator._camera_rows = Mock(return_value=[{"id": "camera.front", "name": "Front", "available": True}])
        async def stream(*args):
            await asyncio.Event().wait()
        self.coordinator._async_stream_camera = stream
        self.addAsyncCleanup(self.coordinator.async_shutdown)

    async def show(self, key="ring-1"):
        await self.coordinator.async_show_doorbell(self.runtime, "camera.front", key, 60)

    async def test_popup_payload_opens_selected_camera_and_expiry_closes_it(self):
        await self.show()
        sent = self.runtime.async_send.await_args.args[1]
        self.assertEqual(sent["selected_id"], "camera.front")
        self.assertEqual(sent["popup_id"], "ring-1")
        self.assertGreater(sent["popup_expires_at"], time.time())
        self.coordinator._popup_tasks["rook"].cancel()
        await asyncio.gather(self.coordinator._popup_tasks["rook"], return_exceptions=True)
        lease = ("ring-1", "camera.front", time.time() - 1)
        self.coordinator._camera_popups["rook"] = lease
        await self.coordinator._async_expire_popup(self.runtime, lease)
        self.assertNotIn("rook", self.coordinator._camera_tasks)
        self.assertNotIn("popup_id", self.runtime.async_send.await_args.args[1])
        self.assertNotIn("selected_id", self.runtime.async_send.await_args.args[1])

    async def test_replacing_popup_does_not_let_old_expiry_close_new_camera(self):
        await self.show()
        old = self.coordinator._camera_popups["rook"]
        old_stream = self.coordinator._camera_tasks["rook"]
        await self.show("ring-2")
        self.assertTrue(old_stream.cancelled())
        self.runtime.async_send.reset_mock()
        expired_old = (old[0], old[1], time.time() - 1)
        await self.coordinator._async_expire_popup(self.runtime, expired_old)
        self.assertEqual(self.coordinator._camera_popups["rook"][0], "ring-2")
        self.runtime.async_send.assert_not_awaited()

    async def test_manual_selection_takes_over_without_future_popup_expiry(self):
        await self.show()
        await self.coordinator._async_select_camera(self.runtime, "camera.front")
        self.assertNotIn("rook", self.coordinator._camera_popups)
        self.assertNotIn("rook", self.coordinator._popup_tasks)
        self.assertNotIn("popup_id", self.runtime.async_send.await_args.args[1])

    async def test_screen_dismissal_stops_stream_and_clears_selected_camera(self):
        await self.show()
        await self.coordinator.async_handle_message(self.runtime, "display.camera.close", {})
        self.assertNotIn("rook", self.coordinator._camera_tasks)
        self.assertNotIn("rook", self.coordinator._camera_popups)
        self.assertNotIn("selected_id", self.runtime.async_send.await_args.args[1])

    async def test_offline_old_firmware_and_failed_send_do_not_start_streams(self):
        self.runtime.connected = False
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await self.show()
        self.runtime.connected = True
        self.runtime.capabilities.pop("screen_camera_popup_version")
        with self.assertRaisesRegex(RuntimeError, "firmware"):
            await self.show()
        self.runtime.capabilities["screen_camera_popup_version"] = 1
        self.runtime.async_send.return_value = False
        with self.assertRaisesRegex(RuntimeError, "connection closed"):
            await self.show()
        self.assertFalse(self.coordinator._camera_popups)
        self.assertFalse(self.coordinator._camera_tasks)


if __name__ == "__main__":
    unittest.main()
