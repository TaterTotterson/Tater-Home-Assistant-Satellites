"""Forgetting a satellite removes its HA device without importing Home Assistant."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/tater_satellite"
DOMAIN = "tater_satellite"


def _compile(path: Path, node: ast.AST, name: str, scope: dict) -> object:
    """Compile one extracted function into ``scope`` and return it."""
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[future, node], type_ignores=[])
    )
    exec(compile(module, str(path), "exec"), scope)
    return scope[name]


def load_method(filename: str, class_name: str, method_name: str, **scope):
    """Load one class method from a component module."""
    path = COMPONENT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    return _compile(path, method, method_name, scope)


def load_function(filename: str, function_name: str, **scope):
    """Load one module-level function from a component module."""
    path = COMPONENT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    return _compile(path, function, function_name, scope)


class FakeDeviceRegistry:
    """Minimal device registry keyed by registry id."""

    def __init__(self) -> None:
        self.devices: dict[str, SimpleNamespace] = {}
        self.removed: list[str] = []

    def add(self, registry_id: str, *identifiers: tuple[str, str]) -> SimpleNamespace:
        device = SimpleNamespace(id=registry_id, identifiers=set(identifiers))
        self.devices[registry_id] = device
        return device

    def async_get_device(self, *, identifiers):
        for device in self.devices.values():
            if device.identifiers & set(identifiers):
                return device
        return None

    def async_remove_device(self, device_id: str) -> None:
        self.removed.append(device_id)
        del self.devices[device_id]


REGISTRY_BOX: dict[str, FakeDeviceRegistry] = {}
FAKE_DR = SimpleNamespace(async_get=lambda _hass: REGISTRY_BOX["registry"])

forget = load_method(
    "manager.py", "TaterSatelliteManager", "async_forget",
    dr=FAKE_DR, DOMAIN=DOMAIN,
)
registry_device = load_method(
    "manager.py", "TaterSatelliteManager", "_registry_device",
    dr=FAKE_DR, DOMAIN=DOMAIN,
)


class PerEntryDeviceRegistry(FakeDeviceRegistry):
    """HA 2026.11 shape: per-entry lookup, deprecated async_get_device."""

    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[tuple[tuple[str, str], str]] = []

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        self.lookups.append((identifier, config_entry_id))
        return super().async_get_device(identifiers={identifier})

    def async_get_device(self, *, identifiers):
        raise AssertionError("deprecated async_get_device was called")


class TaterSatelliteManager:
    """isinstance-compatible stand-in that runs the production async_forget."""

    async_forget = forget
    _registry_device = registry_device

    def __init__(self, registry: FakeDeviceRegistry) -> None:
        self.hass = SimpleNamespace()
        self.entry = SimpleNamespace(entry_id="entry-1")
        self.runtimes: dict[str, SimpleNamespace] = {}
        self.data: dict = {"devices": {}, "stereo_pairs": {}}
        self.async_save = AsyncMock()
        REGISTRY_BOX["registry"] = registry

    def add_satellite(self, device_id: str, *, connected: bool = False) -> None:
        self.runtimes[device_id] = SimpleNamespace(connected=connected)
        self.data["devices"][device_id] = {"token": f"credential-{device_id}"}


remove_device = load_function(
    "__init__.py", "async_remove_config_entry_device",
    DOMAIN=DOMAIN, TaterSatelliteManager=TaterSatelliteManager,
)


class ForgetRemovesRegistryDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeDeviceRegistry()
        self.manager = TaterSatelliteManager(self.registry)
        self.manager.add_satellite("kitchen")
        self.manager.add_satellite("sat-1")
        self.manager.data["stereo_pairs"]["living"] = {
            "id": "living",
            "target": "stereo:living",
        }
        self.registry.add("reg-kitchen", (DOMAIN, "kitchen"))
        self.registry.add("reg-sat-1", (DOMAIN, "sat-1"))
        self.registry.add("reg-pair", (DOMAIN, "stereo:living"))
        self.registry.add("reg-bt", ("bluetooth", "AA:BB:CC:DD:EE:FF"))

    def test_forget_removes_matching_registry_device(self) -> None:
        asyncio.run(forget(self.manager, "kitchen"))
        self.assertEqual(self.registry.removed, ["reg-kitchen"])
        self.assertNotIn("kitchen", self.manager.runtimes)
        self.assertNotIn("kitchen", self.manager.data["devices"])
        self.manager.async_save.assert_awaited_once()

    def test_forget_leaves_other_devices_alone(self) -> None:
        asyncio.run(forget(self.manager, "kitchen"))
        self.assertEqual(
            set(self.registry.devices), {"reg-sat-1", "reg-pair", "reg-bt"}
        )
        self.assertIn("sat-1", self.manager.runtimes)
        self.assertIn("living", self.manager.data["stereo_pairs"])

    def test_forget_without_registry_device_still_forgets(self) -> None:
        del self.registry.devices["reg-kitchen"]
        asyncio.run(forget(self.manager, "kitchen"))
        self.assertEqual(self.registry.removed, [])
        self.assertNotIn("kitchen", self.manager.runtimes)
        self.assertNotIn("kitchen", self.manager.data["devices"])
        self.manager.async_save.assert_awaited_once()

    def test_connected_satellite_raises_and_removes_nothing(self) -> None:
        self.manager.runtimes["kitchen"].connected = True
        with self.assertRaises(RuntimeError):
            asyncio.run(forget(self.manager, "kitchen"))
        self.assertEqual(self.registry.removed, [])
        self.assertIn("kitchen", self.manager.runtimes)
        self.assertIn("kitchen", self.manager.data["devices"])
        self.manager.async_save.assert_not_awaited()

    def test_unknown_satellite_raises_key_error(self) -> None:
        with self.assertRaises(KeyError) as caught:
            asyncio.run(forget(self.manager, "garage"))
        self.assertIn("Satellite not found", str(caught.exception))
        self.assertEqual(self.registry.removed, [])
        self.manager.async_save.assert_not_awaited()


class RegistryLookupCompatibilityTests(unittest.TestCase):
    def test_per_entry_lookup_is_used_when_available(self) -> None:
        registry = PerEntryDeviceRegistry()
        manager = TaterSatelliteManager(registry)
        manager.add_satellite("kitchen")
        registry.add("reg-kitchen", (DOMAIN, "kitchen"))
        registry.add("reg-sat-1", (DOMAIN, "sat-1"))
        asyncio.run(forget(manager, "kitchen"))
        self.assertEqual(registry.removed, ["reg-kitchen"])
        self.assertEqual(registry.lookups, [((DOMAIN, "kitchen"), "entry-1")])

    def test_older_registry_falls_back_to_async_get_device(self) -> None:
        registry = FakeDeviceRegistry()
        self.assertFalse(hasattr(registry, "async_get_device_by_identifier"))
        manager = TaterSatelliteManager(registry)
        manager.add_satellite("kitchen")
        registry.add("reg-kitchen", (DOMAIN, "kitchen"))
        asyncio.run(forget(manager, "kitchen"))
        self.assertEqual(registry.removed, ["reg-kitchen"])


class RemoveConfigEntryDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeDeviceRegistry()
        self.manager = TaterSatelliteManager(self.registry)
        self.manager.add_satellite("kitchen")
        self.manager.data["stereo_pairs"]["living"] = {
            "id": "living",
            "target": "stereo:living",
        }
        self.entry = SimpleNamespace(runtime_data=self.manager)
        self.hass = SimpleNamespace()

    def _remove(self, device: SimpleNamespace, entry=None) -> bool:
        return asyncio.run(
            remove_device(self.hass, entry or self.entry, device)
        )

    def test_connected_satellite_is_rejected_without_forgetting(self) -> None:
        self.manager.runtimes["kitchen"].connected = True
        device = self.registry.add("reg-kitchen", (DOMAIN, "kitchen"))
        self.assertFalse(self._remove(device))
        self.assertIn("kitchen", self.manager.runtimes)
        self.assertIn("kitchen", self.manager.data["devices"])
        self.assertEqual(self.registry.removed, [])
        self.manager.async_save.assert_not_awaited()

    def test_offline_satellite_is_forgotten_and_allowed(self) -> None:
        device = self.registry.add("reg-kitchen", (DOMAIN, "kitchen"))
        self.assertTrue(self._remove(device))
        self.assertNotIn("kitchen", self.manager.runtimes)
        self.assertNotIn("kitchen", self.manager.data["devices"])
        self.manager.async_save.assert_awaited_once()
        self.assertEqual(self.registry.removed, ["reg-kitchen"])

    def test_unknown_tater_device_is_allowed(self) -> None:
        device = self.registry.add("reg-stale", (DOMAIN, "sat-1"))
        self.assertTrue(self._remove(device))
        self.assertIn("kitchen", self.manager.runtimes)
        self.manager.async_save.assert_not_awaited()
        self.assertEqual(self.registry.removed, [])

    def test_saved_stereo_pair_is_rejected(self) -> None:
        device = self.registry.add("reg-pair", (DOMAIN, "stereo:living"))
        self.assertFalse(self._remove(device))
        self.assertIn("living", self.manager.data["stereo_pairs"])
        self.assertIn("kitchen", self.manager.runtimes)
        self.manager.async_save.assert_not_awaited()
        self.assertEqual(self.registry.removed, [])

    def test_device_without_tater_identifier_is_rejected(self) -> None:
        device = self.registry.add(
            "reg-bt",
            ("bluetooth", "AA:BB:CC:DD:EE:FF"),
            ("bluetooth", "kitchen"),
        )
        self.assertFalse(self._remove(device))
        self.assertIn("kitchen", self.manager.runtimes)
        self.assertIn("kitchen", self.manager.data["devices"])
        self.manager.async_save.assert_not_awaited()
        self.assertEqual(self.registry.removed, [])

    def test_missing_manager_is_rejected(self) -> None:
        device = self.registry.add("reg-kitchen", (DOMAIN, "kitchen"))
        for entry in (SimpleNamespace(), SimpleNamespace(runtime_data=None)):
            with self.subTest(entry=entry):
                self.assertFalse(self._remove(device, entry))
        self.assertIn("kitchen", self.manager.runtimes)
        self.manager.async_save.assert_not_awaited()
        self.assertEqual(self.registry.removed, [])


if __name__ == "__main__":
    unittest.main()
