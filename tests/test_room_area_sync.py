"""Satellite room and Home Assistant area sync without a running HA instance."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import hmac
import importlib.util
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "custom_components/tater_satellite/manager.py"
MANAGER_TREE = ast.parse(MANAGER_PATH.read_text(encoding="utf-8"))
IDENTITY_SPEC = importlib.util.spec_from_file_location("satellite_identity", ROOT / "custom_components/tater_satellite/identity.py")
IDENTITY = importlib.util.module_from_spec(IDENTITY_SPEC)
IDENTITY_SPEC.loader.exec_module(IDENTITY)
DOMAIN = "tater_satellite"
ENTRY_ID = "entry-1"

MANAGER_METHODS = (
    "_add_runtime_platform",
    "_registry_device",
    "_async_device_registry_updated",
    "_async_area_registry_updated",
    "_apply_firmware_room",
    "_sync_firmware_room",
    "_sync_confirmed_name",
    "_async_registry_identity_change",
    "async_set_device_identity",
    "_handle_text_message",
    "_update_record_from_hello",
    "_authenticate",
)


def text(value: Any) -> str:
    """Mirror protocol.text."""
    return str(value or "").strip()


def load_methods(class_name: str, names: tuple[str, ...], scope: dict) -> dict:
    """Compile production methods (properties without decorators) by name."""
    cls = next(
        node
        for node in MANAGER_TREE.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    found = {
        node.name: node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    }
    missing = set(names) - set(found)
    if missing:
        raise AssertionError(f"{class_name} is missing {sorted(missing)}")
    body = []
    for name in names:
        node = found[name]
        if any(
            isinstance(item, ast.Name) and item.id == "property"
            for item in node.decorator_list
        ):
            node.decorator_list = []
        body.append(node)
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[future, *body], type_ignores=[])
    )
    exec(compile(module, str(MANAGER_PATH), "exec"), scope)
    return {name: scope[name] for name in names}


class FakeDeviceRegistry:
    """Device registry keyed by (domain, identifier)."""

    def __init__(self) -> None:
        self.by_identifier: dict[tuple[str, str], SimpleNamespace] = {}
        self.lookups: list[set[tuple[str, str]]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def add(self, device_id: str, registry_id: str, area_id: str | None = None):
        entry = SimpleNamespace(id=registry_id, area_id=area_id)
        self.by_identifier[(DOMAIN, device_id)] = entry
        return entry

    def async_get_device(self, identifiers=None, connections=None):
        self.lookups.append(set(identifiers or ()))
        for identifier in identifiers or ():
            if identifier in self.by_identifier:
                return self.by_identifier[identifier]
        return None

    def async_update_device(self, device_id: str, **changes: Any) -> None:
        self.updates.append((device_id, changes))
        for entry in self.by_identifier.values():
            if entry.id == device_id:
                for key, value in changes.items():
                    setattr(entry, key, value)


class FakeEntryDeviceRegistry(FakeDeviceRegistry):
    """HA 2026.11 registry: per-config-entry lookup, async_get_device deprecated."""

    def __init__(self) -> None:
        super().__init__()
        self.entry_lookups: list[tuple[tuple[str, str], str]] = []

    def async_get_device(self, identifiers=None, connections=None):
        raise AssertionError("deprecated async_get_device was called")

    def async_get_device_by_identifier(
        self, identifier: tuple[str, str], config_entry_id: str
    ):
        self.entry_lookups.append((identifier, config_entry_id))
        if config_entry_id != ENTRY_ID:
            return None
        return self.by_identifier.get(identifier)


class FakeAreaRegistry:
    """Area registry with HA's case-insensitive get-or-create by name."""

    def __init__(self) -> None:
        self.areas: dict[str, SimpleNamespace] = {}
        self.created: list[str] = []
        self.requested: list[str] = []

    def add(self, area_id: str, name: str) -> SimpleNamespace:
        area = SimpleNamespace(id=area_id, name=name)
        self.areas[area_id] = area
        return area

    def async_get_area(self, area_id: str):
        return self.areas.get(area_id)

    def async_get_or_create(self, name: str) -> SimpleNamespace:
        self.requested.append(name)
        for area in self.areas.values():
            if area.name.casefold() == name.casefold():
                return area
        self.created.append(name)
        base_id = name.lower().replace(" ", "_")
        area_id = base_id
        suffix = 2
        while area_id in self.areas:
            area_id = f"{base_id}_{suffix}"
            suffix += 1
        return self.add(area_id, name)


def fake_runtime(manager: Any, device_id: str, record: dict) -> SimpleNamespace:
    """Stand in for SatelliteRuntime in _authenticate."""
    return FakeRuntime(
        manager=manager, device_id=device_id, name=record["name"], record=record
    )


def build_manager(devices: FakeDeviceRegistry | None = None):
    """Return a fake manager running the production registry methods."""
    devices = devices or FakeDeviceRegistry()
    areas = FakeAreaRegistry()
    hass = SimpleNamespace(async_create_task=asyncio.create_task)

    def registry_for(registry):
        def async_get(target):
            assert target is hass
            return registry

        return async_get

    scope = {
        "identity_text": IDENTITY.identity_text,
        "slugify": lambda value: value.lower().replace(" ", "_"),
        "ir": SimpleNamespace(async_create_issue=Mock(), async_delete_issue=Mock(), IssueSeverity=SimpleNamespace(WARNING="warning")),
        "dr": SimpleNamespace(async_get=registry_for(devices)),
        "ar": SimpleNamespace(async_get=registry_for(areas)),
        "DOMAIN": DOMAIN,
        "text": text,
        "callback": lambda func: func,
        "_LOGGER": Mock(),
        "hmac": hmac,
        "secrets": secrets,
        "time": time,
        "_token_hash": lambda value: f"hash:{value}",
        "message_payload": lambda message: message.get("payload") or {},
        "message_type": lambda message: message.get("type") or "",
        "normalize_hardware_id": text,
        "pairing_retry_token": Mock(return_value=""),
        "process_success_login": Mock(),
        "PAIRING_RETRY_GRACE_SECONDS": 60,
        "SatelliteRuntime": fake_runtime,
    }
    methods = load_methods("TaterSatelliteManager", MANAGER_METHODS, scope)
    manager_cls = type("FakeManager", (), methods)
    manager = manager_cls()
    manager.hass = hass
    manager.entry = SimpleNamespace(entry_id=ENTRY_ID)
    manager.runtimes = {}
    manager.async_save = AsyncMock()
    manager.logger = scope["_LOGGER"]
    return manager, devices, areas


ROOM = load_methods(
    "SatelliteRuntime",
    ("room",),
    {"contextlib": contextlib, "text": text},
)["room"]


class FakeRuntime(SimpleNamespace):
    room = property(ROOM)


def make_runtime(device_id: str, room: str = "") -> FakeRuntime:
    return FakeRuntime(
        device_id=device_id,
        name=device_id,
        record={"room": room, "name": device_id},
        notify=Mock(),
    )


def device_event(action: str, device_id: str, changes: dict | None = None):
    data = {"action": action, "device_id": device_id}
    if changes is not None:
        data["changes"] = changes
    return SimpleNamespace(data=data)


class RuntimeRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager, self.devices, self.areas = build_manager()

    def runtime_room(self, manager: Any, record_room: str = "Kitchen") -> str:
        return ROOM(SimpleNamespace(
            manager=manager, device_id="sat-1", record={"room": record_room}
        ))

    def test_firmware_room_wins_over_a_different_ha_area(self) -> None:
        self.areas.add("bedroom", "Bedroom")
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.assertEqual(self.runtime_room(self.manager), "Kitchen")
        self.assertEqual(self.devices.lookups, [])

    def test_room_uses_firmware_without_an_area(self) -> None:
        self.devices.add("sat-1", "reg-1", None)
        self.assertEqual(self.runtime_room(self.manager), "Kitchen")

    def test_room_uses_firmware_without_a_registry_device(self) -> None:
        self.assertEqual(self.runtime_room(self.manager), "Kitchen")

    def test_ha_area_rename_cannot_change_the_firmware_room(self) -> None:
        area = self.areas.add("kitchen", "Kitchen")
        self.devices.add("sat-1", "reg-1", "kitchen")
        area.name = "Bedroom"
        self.assertEqual(self.runtime_room(self.manager), "Kitchen")

    def test_room_is_independent_of_the_ha_registry(self) -> None:
        self.devices.async_get_device = Mock(side_effect=RuntimeError("unavailable"))
        self.assertEqual(self.runtime_room(self.manager), "Kitchen")
        self.devices.async_get_device.assert_not_called()

    def test_room_works_without_a_manager(self) -> None:
        self.assertEqual(ROOM(SimpleNamespace(record={"room": "Kitchen"})), "Kitchen")

    def test_room_trims_firmware_metadata(self) -> None:
        self.assertEqual(self.runtime_room(self.manager, " Office "), "Office")

    def test_unknown_firmware_room_does_not_fall_back_to_ha(self) -> None:
        self.areas.add("bedroom", "Bedroom")
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.assertEqual(self.runtime_room(self.manager, ""), "")


class FirmwareAreaMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager, self.devices, self.areas = build_manager()

    def test_existing_area_matches_firmware_case_insensitively(self) -> None:
        self.areas.add("office", "Office")
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.manager._apply_firmware_room("sat-1", "office")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "office"})])
        self.assertEqual(self.areas.created, [])

    def test_matching_area_never_writes_or_loops(self) -> None:
        self.areas.add("office", "Office")
        self.devices.add("sat-1", "reg-1", "office")
        for _ in range(3):
            self.manager._apply_firmware_room("sat-1", "Office")
        self.assertEqual(self.devices.updates, [])

    def test_unknown_firmware_room_unassigns_the_satellite_only(self) -> None:
        self.devices.add("sat-1", "reg-1", "office")
        other = self.devices.add("sat-2", "reg-2", "office")
        self.manager._apply_firmware_room("sat-1", "")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": None})])
        self.assertEqual(other.area_id, "office")
        self.assertEqual(self.areas.requested, [])

    def test_unknown_room_without_an_assignment_makes_no_change(self) -> None:
        self.devices.add("sat-1", "reg-1", None)
        self.manager._apply_firmware_room("sat-1", "")
        self.assertEqual(self.devices.updates, [])
        self.assertEqual(self.areas.created, [])

    def test_missing_device_does_not_create_an_area(self) -> None:
        self.manager._apply_firmware_room("sat-1", "Kitchen")
        self.assertEqual(self.areas.requested, [])


class RegistryDeviceLookupTests(unittest.TestCase):
    def test_new_ha_uses_the_config_entry_lookup(self) -> None:
        devices = FakeEntryDeviceRegistry()
        manager, _, areas = build_manager(devices)
        areas.add("bedroom", "Bedroom")
        devices.add("sat-1", "reg-1", "bedroom")
        manager._apply_firmware_room("sat-1", "Bedroom")
        self.assertEqual(devices.entry_lookups, [((DOMAIN, "sat-1"), ENTRY_ID)])
        self.assertEqual(devices.lookups, [])

    def test_new_ha_hello_moves_the_device_without_the_deprecated_call(self) -> None:
        devices = FakeEntryDeviceRegistry()
        manager, _, _ = build_manager(devices)
        devices.add("sat-1", "reg-1", None)
        runtime = make_runtime("sat-1", room="Kitchen")
        asyncio.run(manager._update_record_from_hello(runtime, {"room": "Bedroom"}))
        self.assertEqual(devices.updates, [("reg-1", {"area_id": "bedroom"})])
        manager.logger.warning.assert_not_called()

    def test_older_ha_falls_back_to_async_get_device(self) -> None:
        self.assertFalse(hasattr(FakeDeviceRegistry, "async_get_device_by_identifier"))
        manager, devices, _ = build_manager()
        devices.add("sat-1", "reg-1", None)
        self.assertIs(
            manager._registry_device("sat-1"), devices.by_identifier[(DOMAIN, "sat-1")]
        )
        self.assertEqual(devices.lookups, [{(DOMAIN, "sat-1")}])


class DeviceRegistryEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager, self.devices, self.areas = build_manager()
        self.sat1 = make_runtime("sat-1", "Kitchen")
        self.sat2 = make_runtime("sat-2", "Bedroom")
        self.areas.add("kitchen", "Kitchen")
        self.areas.add("bedroom", "Bedroom")
        self.manager.runtimes = {"sat-1": self.sat1, "sat-2": self.sat2}
        self.devices.add("sat-1", "reg-1", "kitchen")
        self.devices.add("sat-2", "reg-2", "bedroom")

    def test_area_change_is_repaired_without_overriding_the_room(self) -> None:
        self.devices.by_identifier[(DOMAIN, "sat-2")].area_id = "kitchen"
        self.manager._async_device_registry_updated(
            device_event("update", "reg-2", {"area_id": "kitchen"})
        )
        self.sat2.notify.assert_called_once_with()
        self.sat1.notify.assert_not_called()
        self.assertEqual(self.sat2.room, "Bedroom")
        self.assertEqual(self.devices.updates, [("reg-2", {"area_id": "bedroom"})])
        # The resulting HA event is idempotent, so it cannot create a loop.
        self.manager._async_device_registry_updated(
            device_event("update", "reg-2", {"area_id": "kitchen"})
        )
        self.assertEqual(len(self.devices.updates), 1)

    def test_area_cleared_notifies(self) -> None:
        self.devices.by_identifier[(DOMAIN, "sat-1")].area_id = None
        self.manager._async_device_registry_updated(
            device_event("update", "reg-1", {"area_id": None})
        )
        self.sat1.notify.assert_called_once_with()
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "kitchen"})])

    def test_other_devices_are_ignored(self) -> None:
        self.manager._async_device_registry_updated(
            device_event("update", "reg-other", {"area_id": "kitchen"})
        )
        self.sat1.notify.assert_not_called()
        self.sat2.notify.assert_not_called()

    def test_non_area_changes_are_ignored(self) -> None:
        self.manager._async_device_registry_updated(
            device_event("update", "reg-1", {"name_by_user": "Old"})
        )
        self.manager._async_device_registry_updated(device_event("update", "reg-1"))
        self.sat1.notify.assert_not_called()
        self.assertEqual(len(self.devices.lookups), 1)

    def test_remove_is_ignored(self) -> None:
        self.manager._async_device_registry_updated(device_event("remove", "reg-1"))
        self.sat1.notify.assert_not_called()
        self.assertEqual(self.devices.lookups, [])

    def test_new_registry_device_is_matched_after_entity_creation(self) -> None:
        self.devices.by_identifier[(DOMAIN, "sat-1")].area_id = "bedroom"
        self.manager._async_device_registry_updated(device_event("create", "reg-1"))
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "kitchen"})])
        self.sat1.notify.assert_called_once_with()

    def test_registry_failures_never_raise(self) -> None:
        self.devices.async_get_device = Mock(side_effect=RuntimeError("boom"))
        self.manager._async_device_registry_updated(
            device_event("update", "reg-1", {"area_id": "kitchen"})
        )
        self.sat1.notify.assert_not_called()


class AreaRegistryEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager, self.devices, self.areas = build_manager()
        self.kitchen_a = make_runtime("sat-1", "Kitchen")
        self.kitchen_b = make_runtime("sat-2", "Kitchen")
        self.bedroom = make_runtime("sat-3", "Bedroom")
        self.areas.add("kitchen", "Kitchen")
        self.areas.add("bedroom", "Bedroom")
        self.unregistered = make_runtime("sat-4")
        self.manager.runtimes = {
            runtime.device_id: runtime
            for runtime in (
                self.kitchen_a,
                self.kitchen_b,
                self.bedroom,
                self.unregistered,
            )
        }
        self.devices.add("sat-1", "reg-1", "kitchen")
        self.devices.add("sat-2", "reg-2", "kitchen")
        self.devices.add("sat-3", "reg-3", "bedroom")

    def area_event(self, action: str, area_id: str | None) -> SimpleNamespace:
        return SimpleNamespace(data={"action": action, "area_id": area_id})

    def test_rename_rematches_only_satellites_and_preserves_firmware(self) -> None:
        self.areas.areas["kitchen"].name = "Lounge"
        other = self.devices.add("unrelated", "reg-other", "kitchen")
        self.manager._async_area_registry_updated(self.area_event("update", "kitchen"))
        self.kitchen_a.notify.assert_called_once_with()
        self.kitchen_b.notify.assert_called_once_with()
        self.bedroom.notify.assert_not_called()
        self.unregistered.notify.assert_not_called()
        self.assertEqual(self.kitchen_a.room, "Kitchen")
        self.assertEqual(self.kitchen_b.room, "Kitchen")
        self.assertEqual(self.areas.created, ["Kitchen"])
        self.assertEqual(self.devices.updates, [
            ("reg-1", {"area_id": "kitchen_2"}),
            ("reg-2", {"area_id": "kitchen_2"}),
        ])
        self.assertEqual(other.area_id, "kitchen")
        self.assertEqual(self.areas.areas["kitchen"].name, "Lounge")

    def test_other_actions_are_ignored(self) -> None:
        for action in ("create", "remove", "reorder"):
            self.manager._async_area_registry_updated(
                self.area_event(action, "kitchen")
            )
        self.manager._async_area_registry_updated(self.area_event("update", None))
        self.kitchen_a.notify.assert_not_called()
        self.assertEqual(self.devices.lookups, [])

    def test_registry_failures_never_raise(self) -> None:
        self.devices.async_get_device = Mock(side_effect=RuntimeError("boom"))
        self.manager._async_area_registry_updated(self.area_event("update", "kitchen"))
        self.kitchen_a.notify.assert_not_called()


class HelloRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager, self.devices, self.areas = build_manager()
        self.runtime = make_runtime("sat-1", room="Kitchen")

    def hello(self, **payload: Any) -> None:
        asyncio.run(self.manager._update_record_from_hello(self.runtime, payload))

    def test_changed_firmware_room_moves_the_device_to_an_existing_area(self) -> None:
        self.areas.add("kitchen", "Kitchen")
        self.areas.add("bedroom", "Bedroom")
        self.devices.add("sat-1", "reg-1", "kitchen")
        self.hello(room="bedroom")
        self.assertEqual(self.runtime.record["room"], "bedroom")
        self.manager.async_save.assert_awaited_once()
        self.assertEqual(self.areas.requested, ["bedroom"])
        self.assertEqual(self.areas.created, [])
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "bedroom"})])

    def test_changed_firmware_room_creates_a_missing_area(self) -> None:
        self.devices.add("sat-1", "reg-1", None)
        self.hello(room="Game Room")
        self.assertEqual(self.areas.created, ["Game Room"])
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "game_room"})])
        self.manager.async_save.assert_awaited_once()

    def test_reconnect_repairs_an_ha_override_even_if_firmware_room_is_unchanged(self) -> None:
        self.areas.add("bedroom", "Bedroom")
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.hello(room="Kitchen")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "kitchen"})])
        self.assertEqual(self.runtime.room, "Kitchen")
        self.manager.async_save.assert_not_awaited()

    def test_explicit_empty_firmware_room_clears_context_and_area(self) -> None:
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.hello(room="  ")
        self.assertEqual(self.runtime.room, "")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": None})])
        self.assertEqual(self.areas.requested, [])
        self.manager.async_save.assert_awaited_once()

    def test_missing_room_uses_last_firmware_metadata_and_repairs_area(self) -> None:
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.hello()
        self.assertEqual(self.runtime.room, "Kitchen")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "kitchen"})])
        self.manager.async_save.assert_not_awaited()

    def test_no_device_means_no_area_registry_call(self) -> None:
        self.hello(room="Bedroom")
        self.assertEqual(self.runtime.record["room"], "Bedroom")
        self.manager.async_save.assert_awaited_once()
        self.assertEqual(self.devices.lookups, [{(DOMAIN, "sat-1")}])
        self.assertEqual(self.areas.requested, [])
        self.assertEqual(self.devices.updates, [])

    def test_device_already_in_the_area_is_not_updated(self) -> None:
        self.areas.add("bedroom", "Bedroom")
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.hello(room="Bedroom")
        self.assertEqual(self.areas.requested, ["Bedroom"])
        self.assertEqual(self.devices.updates, [])
        self.manager.async_save.assert_awaited_once()

    def test_first_room_after_an_empty_record_moves_the_device(self) -> None:
        self.runtime.record["room"] = ""
        self.devices.add("sat-1", "reg-1", None)
        self.hello(room="Office")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "office"})])

    def test_name_changes_still_match_the_firmware_room(self) -> None:
        self.devices.add("sat-1", "reg-1", "bedroom")
        self.hello(device_name="Kitchen Echo", room="Kitchen")
        self.assertEqual(self.runtime.record["name"], "Kitchen Echo")
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "kitchen"})])
        self.manager.async_save.assert_awaited_once()

    def test_registry_failure_does_not_break_the_hello(self) -> None:
        self.devices.add("sat-1", "reg-1", None)
        self.areas.async_get_or_create = Mock(side_effect=ValueError("bad name"))
        self.hello(room="Bedroom")
        self.assertEqual(self.runtime.record["room"], "Bedroom")
        self.manager.async_save.assert_awaited_once()
        self.manager.logger.warning.assert_called_once()


class PairingRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager, self.devices, self.areas = build_manager()
        self.manager.data = {"devices": {}}
        self.manager._auth_token = Mock(return_value="123456")
        self.manager._pairing_matches = Mock(return_value=True)
        self.manager._add_runtime_entities = Mock()

    def pair(self, room: str) -> tuple[bool, str]:
        hello = {"payload": {"device_name": "Satellite", "room": room}}
        return asyncio.run(self.manager._authenticate(Mock(), "sat-1", hello))

    def test_first_pairing_moves_nothing(self) -> None:
        ok, token = self.pair("Kitchen")
        self.assertTrue(ok)
        self.assertTrue(token)
        self.assertEqual(self.manager.data["devices"]["sat-1"]["room"], "Kitchen")
        self.assertEqual(self.areas.requested, [])
        self.assertEqual(self.devices.updates, [])
        self.manager._add_runtime_entities.assert_called_once()

    def test_repairing_matches_the_device_to_its_firmware_room(self) -> None:
        self.areas.add("kitchen", "Kitchen")
        self.devices.add("sat-1", "reg-1", "kitchen")
        ok, _ = self.pair("Bedroom")
        self.assertTrue(ok)
        self.assertEqual(self.areas.requested, ["Bedroom"])
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": "bedroom"})])

    def test_pairing_without_a_room_leaves_the_satellite_unassigned(self) -> None:
        self.devices.add("sat-1", "reg-1", "kitchen")
        self.pair("")
        self.assertEqual(self.areas.requested, [])
        self.assertEqual(self.devices.updates, [("reg-1", {"area_id": None})])


class ManagerImportTests(unittest.TestCase):
    """The method tests inject these names, so check manager.py binds them."""

    def imported(self) -> dict[str, tuple[str, str]]:
        bound: dict[str, tuple[str, str]] = {}
        for node in MANAGER_TREE.body:
            if isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                for alias in node.names:
                    bound[alias.asname or alias.name] = (module, alias.name)
        return bound

    def test_registry_and_core_names_are_imported(self) -> None:
        bound = self.imported()
        self.assertEqual(bound["ar"], ("homeassistant.helpers", "area_registry"))
        self.assertEqual(bound["dr"], ("homeassistant.helpers", "device_registry"))
        self.assertEqual(bound["callback"], ("homeassistant.core", "callback"))
        self.assertEqual(bound["Event"], ("homeassistant.core", "Event"))
        self.assertEqual(bound["DOMAIN"], (".const", "DOMAIN"))

    def test_domain_leads_the_const_import(self) -> None:
        const = next(
            node
            for node in MANAGER_TREE.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "const"
            and node.level == 1
        )
        self.assertEqual(const.names[0].name, "DOMAIN")


class SetupSubscriptionTests(unittest.TestCase):
    def test_setup_repairs_stored_ha_overrides_before_a_satellite_reconnects(self) -> None:
        cls = next(node for node in MANAGER_TREE.body if isinstance(node, ast.ClassDef)
                   and node.name == "TaterSatelliteManager")
        setup = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "async_setup")
        restore = next(node for node in setup.body if isinstance(node, ast.For)
                       and "SatelliteRuntime" in ast.unparse(node))
        function = ast.parse("def restore(self):\n    pass").body[0]
        function.body = [restore]
        scope = {"SatelliteRuntime": fake_runtime, "text": text,
                 "_safe_device_id": lambda value: value}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     "<restore satellites>", "exec"), scope)
        manager, devices, areas = build_manager()
        areas.add("bedroom", "Bedroom")
        devices.add("sat-1", "reg-1", "bedroom")
        manager.data = {"devices": {"sat-1": {"name": "Office sat", "room": "Office"}}}
        scope["restore"](manager)
        self.assertEqual(manager.runtimes["sat-1"].room, "Office")
        self.assertEqual(devices.updates, [("reg-1", {"area_id": "office"})])
        manager.async_save.assert_not_awaited()

    def test_setup_listens_for_device_and_area_updates(self) -> None:
        cls = next(
            node
            for node in MANAGER_TREE.body
            if isinstance(node, ast.ClassDef) and node.name == "TaterSatelliteManager"
        )
        setup = next(
            node
            for node in cls.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup"
        )
        listened = set()
        for node in ast.walk(setup):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "async_on_unload"
                and node.args
                and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Attribute)
                and node.args[0].func.attr == "async_listen"
            ):
                event, handler = node.args[0].args[:2]
                listened.add((ast.unparse(event), ast.unparse(handler)))
        self.assertEqual(
            listened,
            {
                (
                    "dr.EVENT_DEVICE_REGISTRY_UPDATED",
                    "self._async_device_registry_updated",
                ),
                (
                    "ar.EVENT_AREA_REGISTRY_UPDATED",
                    "self._async_area_registry_updated",
                ),
            },
        )
        handlers = {
            node.name: node
            for node in cls.body
            if isinstance(node, ast.FunctionDef)
            and node.name
            in {"_async_device_registry_updated", "_async_area_registry_updated"}
        }
        self.assertEqual(len(handlers), 2)
        for node in handlers.values():
            self.assertIn("callback", [ast.unparse(item) for item in node.decorator_list])


if __name__ == "__main__":
    unittest.main()
