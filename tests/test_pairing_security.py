"""Pairing attempt limits and HA login-ban reporting using production methods."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from aiohttp import ClientSession, WSMsgType, web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/tater_satellite"
PAIRING_SPEC = importlib.util.spec_from_file_location("security_pairing", COMPONENT / "pairing.py")
pairing = importlib.util.module_from_spec(PAIRING_SPEC)
PAIRING_SPEC.loader.exec_module(pairing)


def load_manager():
    tree = ast.parse((COMPONENT / "manager.py").read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TaterSatelliteManager"
    )
    names = {
        "start_pairing",
        "pairing_snapshot",
        "_pairing_matches",
        "_auth_token",
        "_reject_authentication",
        "_authenticate",
        "async_handle_websocket",
    }
    methods = [
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_token_hash", "_safe_device_id"}
    ]
    constants = [
        node
        for node in ast.parse((COMPONENT / "const.py").read_text()).body
        if isinstance(node, ast.AnnAssign)
        and node.target.id
        in {"PAIRING_CODE_TTL_SECONDS", "PAIRING_MAX_FAILED_ATTEMPTS", "MAX_TEXT_MESSAGE_BYTES"}
    ]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    scope = {
        "asyncio": asyncio,
        "contextlib": contextlib,
        "hashlib": hashlib,
        "hmac": hmac,
        "json": json,
        "secrets": secrets,
        "time": time,
        "web": web,
        "WSMsgType": WSMsgType,
        "_LOGGER": Mock(),
        "text": lambda value: str(value or "").strip(),
        "message_payload": lambda message: message.get("payload", {}),
        "message_type": lambda message: message.get("type"),
        "parse_text_message": json.loads,
        "envelope": lambda kind, payload: {"type": kind, "payload": payload},
        "MAX_SAT_CHAT_FRAME_BYTES": 1024,
        "normalize_pairing_code": pairing.normalize_pairing_code,
        "normalize_hardware_id": pairing.normalize_hardware_id,
        "pairing_retry_token": pairing.pairing_retry_token,
        "PAIRING_RETRY_GRACE_SECONDS": pairing.PAIRING_RETRY_GRACE_SECONDS,
        "process_wrong_login": AsyncMock(),
        "SatelliteRuntime": lambda manager, device_id, record: SimpleNamespace(room=record["room"]),
    }
    module = ast.fix_missing_locations(
        ast.Module(body=[future, *constants, *functions, *methods], type_ignores=[])
    )
    exec(compile(module, str(COMPONENT / "manager.py"), "exec"), scope)
    manager = type("TestManager", (), {name: scope[name] for name in names})()
    manager.data = {"devices": {}}
    manager.runtimes = {}
    manager._pairing_code = ""
    manager._pairing_expires = 0
    manager._pairing_failed_attempts = 0
    manager._pairing_claimed_device = ""
    manager._pairing_claimed_hardware = ""
    manager._pairing_retry_device_token = ""
    manager._pairing_retry_expires = 0
    manager.async_save = AsyncMock()
    manager._sync_firmware_room = Mock()
    manager._add_runtime_entities = Mock()
    return manager, scope


class PairingSecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager, self.scope = load_manager()
        self.ban = self.scope["process_wrong_login"]
        self.maximum = self.scope["PAIRING_MAX_FAILED_ATTEMPTS"]
        self.hello = {
            "payload": {"device_name": "Sat1", "hardware_id": "ab:cd:ef:12:34:56", "room": "Office"}
        }

    def request(self, credential="", ip="192.0.2.10"):
        return SimpleNamespace(headers={"X-Tater-Token": credential}, remote=ip)

    async def authenticate(self, credential, device="sat1", ip="192.0.2.10"):
        return await self.manager._authenticate(self.request(credential, ip), device, self.hello)

    async def exhaust(self):
        for index in range(self.maximum):
            self.assertEqual(
                await self.authenticate("wrong", f"guess-{index}", f"192.0.2.{index+1}"),
                (False, ""),
            )

    async def test_guesses_across_device_ids_and_ips_invalidate_the_entire_code(self):
        code = self.manager.start_pairing()["code"]
        await self.exhaust()
        self.assertEqual(self.manager._pairing_code, "")
        self.assertEqual(self.manager._pairing_expires, 0)
        self.assertFalse(self.manager.pairing_snapshot()["active"])
        self.assertEqual(await self.authenticate(code), (False, ""))
        self.assertFalse(self.manager.data["devices"])
        self.manager.async_save.assert_not_awaited()
        self.assertEqual(self.ban.await_count, self.maximum + 1)

    async def test_success_before_limit_keeps_normal_setup_and_same_device_retry(self):
        code = self.manager.start_pairing()["code"]
        for _ in range(self.maximum - 1):
            await self.authenticate("wrong")
        authorized, token = await self.authenticate(code)
        self.assertTrue(authorized)
        self.assertTrue(token)
        self.assertEqual(await self.authenticate(code), (True, token))
        self.assertEqual(self.ban.await_count, self.maximum - 1)
        self.manager.async_save.assert_awaited_once()
        self.assertFalse(self.manager.pairing_snapshot()["active"])

    async def test_retry_handoff_has_the_same_attempt_limit_and_cannot_be_used_by_another_device(
        self,
    ):
        code = self.manager.start_pairing()["code"]
        authorized, token = await self.authenticate(code)
        self.assertTrue(authorized)
        self.assertEqual(await self.authenticate(code, "different-device"), (False, ""))
        for _ in range(self.maximum - 1):
            self.assertEqual(await self.authenticate("wrong"), (False, ""))
        self.assertEqual(self.manager._pairing_retry_device_token, "")
        self.assertEqual(self.manager._pairing_retry_expires, 0)
        self.assertEqual(await self.authenticate(code), (False, ""))
        self.assertEqual(
            await self.authenticate(token),
            (True, ""),
            "revoking a setup code must not revoke the paired device",
        )

    async def test_valid_device_tokens_work_after_lockout_and_do_not_consume_a_new_pairing_budget(
        self,
    ):
        code = self.manager.start_pairing()["code"]
        _, token = await self.authenticate(code)
        self.manager.start_pairing()
        for _ in range(self.maximum + 1):
            self.assertEqual(await self.authenticate(token), (True, ""))
        self.assertEqual(self.manager._pairing_failed_attempts, 0)
        self.assertTrue(self.manager.pairing_snapshot()["active"])
        self.ban.assert_not_awaited()

    async def test_only_a_new_admin_pairing_session_resets_the_budget(self):
        self.manager.start_pairing()
        await self.exhaust()
        code = self.manager.start_pairing()["code"]
        self.assertEqual(self.manager._pairing_failed_attempts, 0)
        authorized, token = await self.authenticate(code)
        self.assertTrue(authorized)
        self.assertTrue(token)

    async def test_expired_and_missing_codes_and_invalid_existing_tokens_report_to_ha(self):
        code = self.manager.start_pairing()["code"]
        self.manager._pairing_expires = time.time() - 1
        self.assertEqual(await self.authenticate(code), (False, ""))
        self.manager._pairing_code = ""
        self.assertEqual(await self.authenticate(""), (False, ""))
        self.manager.data["devices"]["sat1"] = {
            "token_hash": self.scope["_token_hash"]("valid-device-token")
        }
        request = self.request("wrong")
        self.assertEqual(await self.manager._authenticate(request, "sat1", self.hello), (False, ""))
        self.ban.assert_awaited_with(request)
        self.assertEqual(self.ban.await_count, 3)

    async def test_invalidation_happens_before_login_reporting_yields_to_other_requests(self):
        code = self.manager.start_pairing()["code"]
        for _ in range(self.maximum - 1):
            await self.authenticate("wrong")
        started, finish = asyncio.Event(), asyncio.Event()

        async def delayed_report(request):
            started.set()
            await finish.wait()

        self.ban.side_effect = delayed_report
        rejection = asyncio.create_task(self.authenticate("wrong"))
        await started.wait()
        self.assertEqual(self.manager._pairing_code, "")
        next_request = asyncio.create_task(self.authenticate(code, "parallel"))
        await asyncio.sleep(0)
        self.assertFalse(self.manager.data["devices"])
        finish.set()
        self.assertEqual(await rejection, (False, ""))
        self.assertEqual(await next_request, (False, ""))

    async def test_unicode_input_is_rejected_and_counted_without_crashing_constant_time_comparison(
        self,
    ):
        self.manager.start_pairing()
        self.assertEqual(await self.authenticate("１２３٤٥٦"), (False, ""))
        self.ban.assert_awaited_once()
        self.assertEqual(self.manager._pairing_failed_attempts, 1)

    async def test_websocket_failures_close_and_report_each_connection_to_ha(self):
        code = self.manager.start_pairing()["code"]
        app = web.Application()
        app.router.add_get("/ws", self.manager.async_handle_websocket)
        async with TestServer(app) as server, ClientSession() as session:
            for index in range(self.maximum + 1):
                supplied = code if index == self.maximum else "wrong"
                async with session.ws_connect(
                    server.make_url("/ws"), headers={"X-Tater-Token": supplied}
                ) as websocket:
                    await websocket.send_json(
                        {"type": "hello", "payload": {"device_id": f"sat-{index}"}}
                    )
                    response = await websocket.receive_json()
                    self.assertEqual(response["type"], "error")
                    self.assertFalse(response["payload"]["ok"])
                    closed = await websocket.receive()
                    self.assertEqual(closed.type, WSMsgType.CLOSE)
                    self.assertEqual(closed.data, 1008)
        self.assertEqual(self.ban.await_count, self.maximum + 1)
        self.assertTrue(
            all(call.args[0].remote == "127.0.0.1" for call in self.ban.await_args_list)
        )
        self.assertFalse(self.manager.data["devices"])


if __name__ == "__main__":
    unittest.main()
