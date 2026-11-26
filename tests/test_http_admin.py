"""Exercise the production HTTP authorization without a running HA instance."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
HTTP_PATH = ROOT / "custom_components/tater_satellite/http.py"


class Unauthorized(Exception):
    """Stand-in for Home Assistant's authorization exception."""


class ManagerReached(Exception):
    """Stop an authorized request before it invokes a real integration action."""


class Request(dict):
    def __init__(self, **values):
        super().__init__(values)
        self.json = AsyncMock(return_value={"text": "Test"})


def load_views():
    tree = ast.parse(HTTP_PATH.read_text())
    # Keep the actual helpers, handlers and registration, substituting only HA imports.
    definitions = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    scope = {
        "Path": Path,
        "web": web,
        "HomeAssistantView": type(
            "HomeAssistantView", (), {"json": staticmethod(lambda value: value)}
        ),
        "TaterSatelliteManager": type("TaterSatelliteManager", (), {}),
        "Unauthorized": Unauthorized,
        "StudioConflict": type("StudioConflict", (Exception,), {}),
        "API_BASE_PATH": "/api/tater/satellite/v1",
        "SATELLITE_WS_PATH": "/api/tater/satellite/v1/ws",
        "TRAINER_LINK_HEADER": "X-Tater-Trainer-Token",
        "DOMAIN": "tater_satellite",
        "DATA_MANAGER": "manager",
    }
    module = ast.fix_missing_locations(ast.Module(body=[future, *definitions], type_ignores=[]))
    exec(compile(module, str(HTTP_PATH), "exec"), scope)
    return scope


class HttpAdminTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scope = load_views()
        self.manager = Mock(side_effect=ManagerReached)
        self.scope["_manager"] = self.manager

    def management_handlers(self):
        for view_type in self.scope["VIEWS"]:
            if not view_type.requires_auth:
                continue
            view = view_type()
            for name in ("get", "post", "put", "patch", "delete"):
                if name not in view_type.__dict__:
                    continue
                handler = getattr(view, name)
                parameters = list(inspect.signature(handler).parameters)[1:]
                yield view_type.__name__, name, handler, {key: "test" for key in parameters}

    async def test_every_management_handler_rejects_missing_and_non_admin_users_before_work(self):
        users = ({}, {"hass_user": None}, {"hass_user": SimpleNamespace(is_admin=False)})
        checked = 0
        for view, method, handler, arguments in self.management_handlers():
            checked += 1
            for user in users:
                with self.subTest(view=view, method=method, user=user):
                    request = Request(**user)
                    with self.assertRaises(Unauthorized):
                        await handler(request, **arguments)
                    request.json.assert_not_awaited()
                    self.manager.assert_not_called()
        self.assertGreater(checked, 35)

    async def test_every_management_handler_allows_an_admin_to_reach_the_action(self):
        for view, method, handler, arguments in self.management_handlers():
            with self.subTest(view=view, method=method):
                request = Request(hass_user=SimpleNamespace(is_admin=True))
                with self.assertRaises(ManagerReached):
                    await handler(request, **arguments)
                self.manager.assert_called_once_with(request)
                self.manager.reset_mock()

    def test_satellite_and_signed_or_token_routes_keep_their_own_authentication(self):
        public_views = {view.__name__ for view in self.scope["VIEWS"] if not view.requires_auth}
        self.assertEqual(
            public_views,
            {
                "SatelliteWebSocketView",
                "TaterSpeechAudioView",
                "TrainerClaimView",
                "TrainerPublishView",
                "TrainerRemoteUnlinkView",
                "AssetFileView",
                "FirmwareFileView",
                "IntercomClipView",
            },
        )
        for view in self.scope["VIEWS"]:
            if view.__name__ in public_views:
                for handler in view.__dict__.values():
                    if inspect.iscoroutinefunction(handler):
                        self.assertNotIn("_require_admin", handler.__code__.co_names)


if __name__ == "__main__":
    unittest.main()
