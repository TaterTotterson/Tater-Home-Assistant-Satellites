"""Satellite rename and reconnect behaviour without a running HA instance."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unicodedata
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/tater_satellite"
DOMAIN = "tater_satellite"


def load_function(filename, function_name, **scope):
    """Execute one module-level production function in isolation."""
    path = COMPONENT / filename
    module = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    extracted = ast.fix_missing_locations(
        ast.Module(body=[future, function], type_ignores=[])
    )
    exec(compile(extracted, str(path), "exec"), scope)
    return scope[function_name]


text = load_function("protocol.py", "text")
MANAGER_SOURCE = ast.parse((COMPONENT / "manager.py").read_text(encoding="utf-8"))
MAX_NAME_LENGTH = next(
    ast.literal_eval(node.value)
    for node in MANAGER_SOURCE.body
    if isinstance(node, ast.Assign)
    and any(
        isinstance(target, ast.Name) and target.id == "_MAX_DEVICE_NAME_LENGTH"
        for target in node.targets
    )
)


def load_method(filename, class_name, method_name, **scope):
    """Execute one production method without importing the HA integration."""
    path = COMPONENT / filename
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    extracted = ast.fix_missing_locations(
        ast.Module(body=[future, method], type_ignores=[])
    )
    exec(compile(extracted, str(path), "exec"), scope)
    return scope[method_name]


class FakeDeviceRegistry:
    """Records registry lookups and updates."""

    def __init__(self, devices=None):
        self.devices = devices or {}
        self.lookups = []
        self.async_update_device = Mock()

    def async_get_device(self, *, identifiers):
        self.lookups.append(identifiers)
        for identifier in identifiers:
            if identifier in self.devices:
                return self.devices[identifier]
        return None


class RenameDeviceTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeDeviceRegistry(
            {(DOMAIN, "kitchen"): SimpleNamespace(id="reg-1", name="Kitchen Echo")}
        )
        self.hass = object()
        self.dr = SimpleNamespace(async_get=Mock(return_value=self.registry))
        self.rename = load_method(
            "manager.py", "TaterSatelliteManager", "async_rename_device",
            dr=self.dr,
            DOMAIN=DOMAIN,
            text=text,
            unicodedata=unicodedata,
            _MAX_DEVICE_NAME_LENGTH=MAX_NAME_LENGTH,
        )
        self.runtime = SimpleNamespace(
            record={"name": "Kitchen Echo", "board": "crown"},
            notify=Mock(),
            public_snapshot=Mock(return_value={"device_id": "kitchen"}),
        )
        self.manager = SimpleNamespace(
            hass=self.hass,
            runtimes={"kitchen": self.runtime},
            async_save=AsyncMock(),
        )

    def run_rename(self, name, device_id="kitchen"):
        return asyncio.run(self.rename(self.manager, device_id, name))

    def test_trims_saves_and_marks_name_as_user_chosen(self):
        result = self.run_rename("  Living Room  ")
        self.assertEqual(self.runtime.record["name"], "Living Room")
        self.assertEqual(self.runtime.record["name_source"], "user")
        self.assertEqual(self.runtime.record["board"], "crown")
        self.manager.async_save.assert_awaited_once()
        self.runtime.notify.assert_called_once_with()
        self.assertEqual(result, {"device_id": "kitchen"})

    def test_inner_text_is_kept_as_typed(self):
        self.run_rename("Kid's room  2 · upstairs")
        self.assertEqual(self.runtime.record["name"], "Kid's room  2 · upstairs")

    def test_updates_registry_name_but_never_name_by_user(self):
        self.run_rename("Living Room")
        self.dr.async_get.assert_called_once_with(self.hass)
        self.assertEqual(self.registry.lookups, [{(DOMAIN, "kitchen")}])
        self.registry.async_update_device.assert_called_once_with(
            "reg-1", name="Living Room"
        )
        self.assertNotIn(
            "name_by_user", self.registry.async_update_device.call_args.kwargs
        )

    def test_missing_registry_device_still_renames(self):
        self.registry.devices = {}
        result = self.run_rename("Living Room")
        self.assertEqual(self.runtime.record["name"], "Living Room")
        self.registry.async_update_device.assert_not_called()
        self.manager.async_save.assert_awaited_once()
        self.runtime.notify.assert_called_once_with()
        self.assertEqual(result, {"device_id": "kitchen"})

    def test_registry_already_using_the_name_is_not_updated(self):
        self.run_rename("Kitchen Echo")
        self.assertEqual(self.runtime.record["name_source"], "user")
        self.registry.async_update_device.assert_not_called()

    def test_maximum_length_is_accepted(self):
        name = "x" * MAX_NAME_LENGTH
        self.run_rename(f" {name} ")
        self.assertEqual(self.runtime.record["name"], name)

    def test_invalid_names_are_rejected_without_saving(self):
        self.assertEqual(MAX_NAME_LENGTH, 80)
        for name in (
            "",
            "   ",
            "\t\n",
            None,
            42,
            ["Kitchen"],
            "x" * (MAX_NAME_LENGTH + 1),
            "Kitchen\x00Echo",
            "Kitchen\x1bEcho",
            "Kitchen\nEcho",
            "Kitchen\x7f",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.run_rename(name)
        self.assertEqual(self.runtime.record, {"name": "Kitchen Echo", "board": "crown"})
        self.manager.async_save.assert_not_awaited()
        self.registry.async_update_device.assert_not_called()
        self.runtime.notify.assert_not_called()

    def test_empty_name_explains_what_to_do(self):
        with self.assertRaisesRegex(ValueError, "Enter a satellite name."):
            self.run_rename("  ")

    def test_unknown_satellite_raises_key_error(self):
        with self.assertRaisesRegex(KeyError, "Satellite not found"):
            self.run_rename("Living Room", device_id="sat-1")
        self.manager.async_save.assert_not_awaited()
        self.dr.async_get.assert_not_called()

    def test_offline_satellite_can_be_renamed(self):
        self.runtime.connected = False
        self.run_rename("Garage")
        self.assertEqual(self.runtime.record["name"], "Garage")


class HelloKeepsUserNameTests(unittest.TestCase):
    def setUp(self):
        self.update = load_method(
            "manager.py", "TaterSatelliteManager", "_update_record_from_hello",
            text=text,
        )
        self.manager = SimpleNamespace(async_save=AsyncMock())
        self.hello = {
            "device_name": "Tater Crown",
            "board": "crown",
            "firmware_target": "crown-v2",
            "firmware_version": "2.0.0",
            "room": "Kitchen",
            "capabilities": {"speaker": True},
        }

    def test_user_named_record_keeps_name_while_other_fields_update(self):
        runtime = SimpleNamespace(record={
            "name": "Living Room",
            "name_source": "user",
            "board": "crown",
            "firmware_version": "1.0.0",
        })
        asyncio.run(self.update(self.manager, runtime, self.hello))
        self.assertEqual(runtime.record["name"], "Living Room")
        self.assertEqual(runtime.record["name_source"], "user")
        self.assertEqual(runtime.record["firmware_version"], "2.0.0")
        self.assertEqual(runtime.record["firmware_target"], "crown-v2")
        self.assertEqual(runtime.record["room"], "Kitchen")
        self.assertEqual(runtime.record["capabilities"], {"speaker": True})
        self.manager.async_save.assert_awaited_once()

    def test_user_named_record_with_no_other_changes_is_not_saved(self):
        runtime = SimpleNamespace(record={
            "name": "Living Room",
            "name_source": "user",
            "board": "crown",
            "firmware_target": "crown-v2",
            "firmware_version": "2.0.0",
            "room": "Kitchen",
            "capabilities": {"speaker": True},
        })
        asyncio.run(self.update(self.manager, runtime, self.hello))
        self.assertEqual(runtime.record["name"], "Living Room")
        self.manager.async_save.assert_not_awaited()

    def test_firmware_named_record_still_takes_device_name(self):
        for record in (
            {"name": "Old Name"},
            {"name": "Old Name", "name_source": "firmware"},
        ):
            with self.subTest(record=record):
                self.manager.async_save.reset_mock()
                runtime = SimpleNamespace(record=dict(record))
                asyncio.run(self.update(self.manager, runtime, self.hello))
                self.assertEqual(runtime.record["name"], "Tater Crown")
                self.assertEqual(runtime.record["firmware_version"], "2.0.0")
                self.manager.async_save.assert_awaited_once()


class RenameViewTests(unittest.TestCase):
    class HTTPBadRequest(Exception):
        def __init__(self, *, text):
            super().__init__(text)

    def load_post(self, manager, body):
        async def json_body(request):
            return body

        return load_method(
            "http.py", "DeviceRenameView", "post",
            _manager=lambda request: manager,
            _json_body=json_body,
            web=SimpleNamespace(HTTPBadRequest=self.HTTPBadRequest),
        )

    def test_posts_name_and_returns_device_snapshot(self):
        manager = SimpleNamespace(
            async_rename_device=AsyncMock(return_value={"device_id": "kitchen"})
        )
        post = self.load_post(manager, {"name": "Living Room"})
        view = SimpleNamespace(json=lambda body: body)
        self.assertEqual(
            asyncio.run(post(view, None, "kitchen")),
            {"ok": True, "device": {"device_id": "kitchen"}},
        )
        manager.async_rename_device.assert_awaited_once_with("kitchen", "Living Room")

    def test_rename_errors_become_bad_requests(self):
        for error in (KeyError("Satellite not found"), ValueError("Enter a satellite name.")):
            with self.subTest(error=type(error).__name__):
                manager = SimpleNamespace(async_rename_device=AsyncMock(side_effect=error))
                post = self.load_post(manager, {})
                view = SimpleNamespace(json=Mock())
                with self.assertRaisesRegex(self.HTTPBadRequest, "Satellite not found|Enter a satellite name"):
                    asyncio.run(post(view, None, "kitchen"))
                manager.async_rename_device.assert_awaited_once_with("kitchen", None)
                view.json.assert_not_called()

    def test_view_is_registered_on_its_own_route(self):
        source = ast.parse((COMPONENT / "http.py").read_text(encoding="utf-8"))
        views = next(
            node.value for node in source.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "VIEWS" for t in node.targets)
        )
        names = [element.id for element in views.elts]
        self.assertIn("DeviceRenameView", names)
        cls = next(
            node for node in source.body
            if isinstance(node, ast.ClassDef) and node.name == "DeviceRenameView"
        )
        attrs = {
            target.id: node.value
            for node in cls.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)
        }
        self.assertEqual(ast.literal_eval(attrs["name"]), "api:tater_satellite:device_rename")
        self.assertIs(ast.literal_eval(attrs["requires_auth"]), True)
        self.assertIn("/name", ast.unparse(attrs["url"]))


if __name__ == "__main__":
    unittest.main()
