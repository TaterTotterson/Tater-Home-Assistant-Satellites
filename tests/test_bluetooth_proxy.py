from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "tater_satellite"
PROXY_PATH = COMPONENT / "bluetooth_proxy.py"
MANAGER_PATH = COMPONENT / "manager.py"
HTTP_PATH = COMPONENT / "http.py"
PANEL_PATH = COMPONENT / "frontend" / "tater-satellite-panel.js"


def _address_normalizer():
    module = ast.parse(PROXY_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_address"
    )
    namespace = {"Any": Any}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(PROXY_PATH), "exec"),
        namespace,
    )
    return namespace["normalize_address"]


class BluetoothProxyTests(unittest.TestCase):
    def test_addresses_are_canonicalized_before_routing(self) -> None:
        normalize = _address_normalizer()

        self.assertEqual(normalize("99:cd:6a:12:34:56"), "99:CD:6A:12:34:56")
        self.assertEqual(normalize("99-CD-6A-12-34-56"), "99:CD:6A:12:34:56")
        self.assertEqual(normalize("not-an-address"), "")

    def test_each_capable_echo_registers_a_connectable_ha_scanner(self) -> None:
        proxy = PROXY_PATH.read_text(encoding="utf-8")
        manager = MANAGER_PATH.read_text(encoding="utf-8")
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

        self.assertIn("bluetooth", manifest["dependencies"])
        self.assertIn("class TaterBluetoothScanner(BaseHaRemoteScanner):", proxy)
        self.assertIn("connectable=True", proxy)
        self.assertIn("bluetooth.async_register_scanner(", proxy)
        self.assertIn('runtime.capabilities.get("ble_gatt")', proxy)
        self.assertIn("self.bluetooth.async_connect_runtime(runtime)", manager)
        self.assertIn("self.bluetooth.disconnect_runtime(runtime)", manager)

    def test_gatt_and_pairing_share_the_authenticated_satellite_link(self) -> None:
        proxy = PROXY_PATH.read_text(encoding="utf-8")
        manager = MANAGER_PATH.read_text(encoding="utf-8")
        http = HTTP_PATH.read_text(encoding="utf-8")
        panel = PANEL_PATH.read_text(encoding="utf-8")

        for operation in (
            '"connect"',
            '"disconnect"',
            '"pair"',
            '"forget"',
            '"services"',
            '"read"',
            '"write"',
        ):
            self.assertIn(operation, proxy)
        self.assertIn('"ble.gatt"', proxy)
        self.assertIn('kind == "ble.advertisements"', proxy)
        self.assertIn('kind != "ble.gatt.event"', proxy)
        self.assertIn("self.bluetooth.handle_message(runtime, kind, payload)", manager)
        self.assertIn("class BluetoothPairView", http)
        self.assertIn("class BluetoothUnpairView", http)
        self.assertIn('this.tabButton("bluetooth", "Bluetooth")', panel)
        self.assertIn('data-action="bluetooth-pair"', panel)
        self.assertIn('data-action="bluetooth-unpair"', panel)

    def test_pin_is_validated_but_not_saved_with_bond_metadata(self) -> None:
        proxy = PROXY_PATH.read_text(encoding="utf-8")
        pair_method = proxy.split("async def async_pair(", 1)[1].split(
            "\n    async def ", 1
        )[0]
        saved_record = pair_method.split(
            'self.manager.data.setdefault("bluetooth_devices", {})[address] = {', 1
        )[1].split("\n            }", 1)[0]

        self.assertIn("len(pin) != 6", pair_method)
        self.assertIn('"pin": pin', pair_method)
        self.assertNotIn('"pin"', saved_record)


if __name__ == "__main__":
    unittest.main()
