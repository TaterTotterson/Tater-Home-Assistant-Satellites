"""Exercise discovery and bond ownership without requiring a running HA instance."""
import ast
import asyncio
import contextlib
import logging
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import UUID

PATH = Path(__file__).resolve().parents[1] / "custom_components/tater_satellite/bluetooth_proxy.py"
tree = ast.parse(PATH.read_text())
nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {
    "TaterBluetoothProxyManager", "TaterBluetoothScanner", "normalize_address"}]
namespace = dict(asyncio=asyncio, contextlib=contextlib, secrets=secrets, time=time,
                 scanner_source=lambda runtime: runtime.device_id, BaseHaRemoteScanner=object,
                 UUID=UUID, _LOGGER=logging.getLogger(__name__),
                 _ADVERTISEMENT_MAX_AGE=45, _CONNECT_TIMEOUT=42)
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])), str(PATH), "exec"), namespace)
Proxy = namespace["TaterBluetoothProxyManager"]
Scanner = namespace["TaterBluetoothScanner"]


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = SimpleNamespace(device_id="sat1", name="Kitchen", connected=True,
            capabilities={"ble_gatt": True, "ble_on_demand": True}, async_request=AsyncMock(return_value={"ok": True}))
        self.manager = SimpleNamespace(runtimes={"sat1": self.runtime}, data={}, async_save=AsyncMock())
        self.proxy = Proxy(self.manager)

    async def test_reading_workspace_never_requests_discovery(self):
        for _ in range(3): self.proxy.snapshot()
        self.runtime.async_request.assert_not_awaited()

    async def test_only_explicit_discovery_accepts_advertisements(self):
        scanner = SimpleNamespace(feed=lambda payload: received.append(payload))
        self.proxy._scanners["sat1"] = scanner
        received = []
        payload = {"adverts": [{"address": "AA:BB:CC:DD:EE:FF"}]}
        self.proxy.handle_message(self.runtime, "ble.advertisements", payload)
        self.assertEqual(received, [])
        # Avoid scanner presentation details while exercising the real lease logic.
        self.proxy.snapshot = lambda: {}
        await self.proxy.async_scan("sat1", 15)
        self.proxy.handle_message(self.runtime, "ble.advertisements", payload)
        self.assertEqual(received, [payload])
        self.proxy._scan_until["sat1"] = time.time() - 1
        self.proxy.handle_message(self.runtime, "ble.advertisements", payload)
        self.assertEqual(received, [payload])
        self.assertEqual(self.runtime.async_request.await_args.args[1]["t"], "scan")

    async def test_stop_does_not_disconnect_active_devices(self):
        await self.proxy.async_scan("sat1")
        self.runtime.async_request.reset_mock()
        await self.proxy.async_scan("sat1", stop=True)
        self.assertEqual(self.runtime.async_request.await_count, 1)
        self.assertEqual(self.runtime.async_request.await_args.args[1]["t"], "stop_scan")
        self.assertNotIn("sat1", self.proxy._scan_until)

    async def test_invalid_offline_and_old_firmware_do_not_start_scan(self):
        for duration in (0, 61, True, "15", 5.5):
            with self.assertRaises(ValueError): await self.proxy.async_scan(duration_s=duration)
        self.runtime.capabilities.pop("ble_on_demand")
        with self.assertRaises(ValueError): await self.proxy.async_scan()
        self.runtime.capabilities["ble_on_demand"] = True
        self.runtime.connected = False
        with self.assertRaises(ValueError): await self.proxy.async_scan()
        self.runtime.async_request.assert_not_awaited()

    async def test_failed_scan_drops_lease_but_failed_stop_retains_expiry(self):
        self.runtime.async_request.side_effect = TimeoutError("offline")
        with self.assertRaises(RuntimeError): await self.proxy.async_scan()
        self.assertFalse(self.proxy._scan_until)
        self.proxy._scan_until["sat1"] = time.time() + 15
        with self.assertRaises(RuntimeError): await self.proxy.async_scan(stop=True)
        self.assertIn("sat1", self.proxy._scan_until)

    async def test_pair_preserves_connection_opened_by_another_consumer(self):
        self.proxy._choose_runtime = lambda address, selected: (self.runtime, 1)
        self.runtime.async_request.side_effect = [
            {"ok": False, "error": "already_connected"},
            {"ok": True, "bonded": True, "encrypted": True, "authenticated": True}]
        record = await self.proxy.async_pair("AA:BB:CC:DD:EE:FF", "012345", "sat1")
        self.assertEqual(self.runtime.async_request.await_count, 2)
        self.assertNotIn("pin", record)
        self.assertNotIn("012345", str(self.manager.data))

    async def test_pin_requires_six_ascii_digits_without_silent_rewriting(self):
        for pin in ("abc012345", "１２３４５６", "12345", "1234567"):
            with self.assertRaises(ValueError): await self.proxy.async_pair("AA:BB:CC:DD:EE:FF", pin)
        self.runtime.async_request.assert_not_awaited()

    async def test_linux_decoded_advertisement_keeps_manufacturer_and_service_data(self):
        scanner = object.__new__(Scanner)
        scanner.runtime = self.runtime
        scanner.proxy = SimpleNamespace(bonded_satellite=lambda address: "", note_advertisement=lambda *args: None)
        scanner._previous_service_info = {}
        packets = []
        scanner._async_on_raw_advertisement = lambda *args: packets.append(args[2])
        scanner.feed({"adverts": [{"address": "AA:BB:CC:DD:EE:FF", "rssi": -40,
            "name": "Radio", "service_uuids": ["6ba1b218-15a8-461f-9fa8-5dcae273eafd"],
            "manufacturer_data": {"76": "0102"},
            "service_data": {"0000180f-0000-1000-8000-00805f9b34fb": "64"}}]})
        self.assertEqual(len(packets), 1)
        self.assertIn(b"\x05\xff\x4c\x00\x01\x02", packets[0])
        self.assertIn(b"\x12\x21" + UUID("0000180f-0000-1000-8000-00805f9b34fb").bytes[::-1] + b"\x64", packets[0])
        scanner.feed({"adverts": 2})
        self.assertEqual(len(packets), 1)


if __name__ == "__main__": unittest.main()
