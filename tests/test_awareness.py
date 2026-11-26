"""Exercise camera alerts without a running HA server or real notifications."""

from __future__ import annotations

import asyncio
import ast
import base64
from contextvars import ContextVar
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "custom_components/tater_satellite/awareness.py"
SPEC = importlib.util.spec_from_file_location("tater_awareness_tests", PATH)
awareness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(awareness)
MONITOR_ID = "a" * 32
IMAGE = b"\xff\xd8camera-at-trigger-time\xff\xd9"


def state(entity_id, value, **attributes):
    return SimpleNamespace(
        entity_id=entity_id,
        state=value,
        attributes=attributes,
        name=attributes.get("friendly_name", entity_id),
    )


def monitor(**changes):
    return {
        "name": "Front door",
        "camera_entity": "camera.front_door",
        "trigger_entity": "binary_sensor.front_motion",
        "trigger_value": "state:on",
        "destinations": ["satellite:kitchen", "mobile_app:mobile_app_phone"],
        "enabled": True,
        "cooldown_seconds": 60,
        "instructions": "",
        **changes,
    }


class TriggerTests(unittest.TestCase):
    def test_real_state_edges_only(self):
        row = monitor()
        off = state(row["trigger_entity"], "off")
        on = state(row["trigger_entity"], "on")
        self.assertTrue(awareness.matches_trigger(row, off, on))
        self.assertFalse(awareness.matches_trigger(row, on, on))
        self.assertFalse(awareness.matches_trigger(row, on, off))
        for old in (
            None,
            state(row["trigger_entity"], "unknown"),
            state(row["trigger_entity"], "unavailable"),
        ):
            self.assertFalse(awareness.matches_trigger(row, old, on))
        self.assertFalse(
            awareness.matches_trigger(
                row, off, state(row["trigger_entity"], "on", restored=True)
            )
        )

    def test_repeated_event_types_are_separate_presses(self):
        row = monitor(trigger_entity="event.doorbell", trigger_value="event:ring")
        first = state("event.doorbell", "2026-11-16T10:00:00+00:00", event_type="ring")
        second = state("event.doorbell", "2026-11-16T10:00:01+00:00", event_type="ring")
        self.assertTrue(awareness.matches_trigger(row, first, second))
        self.assertFalse(awareness.matches_trigger(row, first, first))
        self.assertFalse(
            awareness.matches_trigger(
                row, first, state("event.doorbell", "later", event_type="double_press")
            )
        )

    def test_first_real_event_after_unknown_is_not_lost(self):
        row = monitor(trigger_entity="event.doorbell", trigger_value="event:ring")
        old = state("event.doorbell", "unknown")
        new = state(
            "event.doorbell", datetime.now(timezone.utc).isoformat(), event_type="ring"
        )
        self.assertTrue(awareness.matches_trigger(row, old, new))
        self.assertFalse(
            awareness.matches_trigger(
                row,
                old,
                state("event.doorbell", "2000-01-01T00:00:00+00:00", event_type="ring"),
            )
        )

    def test_invalid_targets_and_limits_are_rejected(self):
        for changes in (
            {"camera_entity": "light.office"},
            {"trigger_entity": "camera.front_door"},
            {"trigger_value": "arbitrary"},
            {"destinations": []},
            {"destinations": ["mobile_app:restart"]},
            {"cooldown_seconds": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                awareness.normalize_monitor(monitor(**changes))
        normalized = awareness.normalize_monitor(
            monitor(destinations=["satellite:kitchen"] * 2)
        )
        self.assertEqual(normalized["destinations"], ["satellite:kitchen"])


class AwarenessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.listeners = []
        self.unsubscribed = []
        self.periodic = []
        self.states = {
            "camera.front_door": state(
                "camera.front_door", "idle", friendly_name="Door camera"
            ),
            "binary_sensor.front_motion": state(
                "binary_sensor.front_motion", "off", device_class="motion"
            ),
            "event.doorbell": state(
                "event.doorbell", "unknown", event_types=["ring", "double_press"]
            ),
        }

        async def executor(func, *args):
            return await asyncio.to_thread(func, *args)

        def listen(hass, entities, callback):
            record = (set(entities), callback)
            self.listeners.append(record)
            return lambda: self.unsubscribed.append(record)

        self.camera = AsyncMock(
            return_value=SimpleNamespace(content=IMAGE, content_type="image/jpeg")
        )
        modules = {}
        for name in (
            "homeassistant",
            "homeassistant.components",
            "homeassistant.components.camera",
            "homeassistant.components.http",
            "homeassistant.components.http.auth",
            "homeassistant.components.http.const",
            "homeassistant.core",
            "homeassistant.helpers",
            "homeassistant.helpers.event",
            "homeassistant.helpers.http",
            "homeassistant.helpers.entity_registry",
        ):
            modules[name] = ModuleType(name)
        modules["homeassistant.core"].callback = lambda func: func
        modules["homeassistant.components.http.const"].KEY_HASS_REFRESH_TOKEN_ID = (
            "hass_refresh_token_id"
        )
        self.current_request = ContextVar("test_ha_request", default=None)
        modules["homeassistant.helpers.http"].current_request = self.current_request
        modules["homeassistant.components.camera"].async_get_image = self.camera
        modules["homeassistant.components.http.auth"].async_sign_path = (
            lambda hass, path, expiration: path + "?authSig=test"
        )
        modules["homeassistant.helpers.event"].async_track_state_change_event = listen
        modules["homeassistant.helpers.event"].async_track_time_interval = (
            lambda hass, callback, interval: self.periodic.append(callback) or (lambda: None)
        )
        modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: SimpleNamespace(
            async_get=lambda entity_id: (
                SimpleNamespace(device_id="front") if "front" in entity_id else None
            )
        )
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        services = SimpleNamespace(
            has_service=lambda domain, service: domain == "notify"
            and service == "mobile_app_phone",
            async_services=lambda: {
                "notify": {"mobile_app_phone": {}, "unrelated_service": {}}
            },
            async_call=AsyncMock(),
        )
        self.hass = SimpleNamespace(
            config=SimpleNamespace(
                media_dirs={"local": self.temp.name},
                path=lambda *parts: str(Path(self.temp.name, *parts)),
            ),
            states=SimpleNamespace(
                get=self.states.get,
                async_all=lambda domain: [
                    row
                    for row in self.states.values()
                    if row.entity_id.startswith(domain + ".")
                ],
            ),
            services=services,
            async_add_executor_job=executor,
        )
        self.screen = SimpleNamespace(
            device_id="kitchen",
            name="Kitchen Show",
            connected=True,
            capabilities={"screen_notifications": True},
            async_send=AsyncMock(return_value=True),
        )
        self.voice = SimpleNamespace(
            _describe_images=AsyncMock(
                return_value="A parcel is beside the front door."
            )
        )
        self.manager = SimpleNamespace(
            hass=self.hass,
            data={"tater_settings": {"assistant_mode": "home_assistant"}},
            entry=SimpleNamespace(
                async_create_background_task=lambda hass, coroutine, name: asyncio.create_task(
                    coroutine, name=name
                )
            ),
            runtimes={"kitchen": self.screen},
            tater_assistant=self.voice,
            effective_settings=lambda device_id: {},
            async_save=AsyncMock(),
        )
        self.coordinator = awareness.AwarenessCoordinator(self.manager)
        await self.coordinator.async_start()
        self.addAsyncCleanup(self.coordinator.async_shutdown)

    async def save(self, **changes):
        return await self.coordinator.async_save_monitor(monitor(**changes))

    def fire(self, entity="binary_sensor.front_motion", before="off", after="on"):
        self.coordinator._handle_event(
            SimpleNamespace(
                data={
                    "entity_id": entity,
                    "old_state": state(entity, before),
                    "new_state": state(entity, after),
                }
            )
        )

    async def finish(self):
        await asyncio.gather(*list(self.coordinator._tasks.values()))
        await asyncio.sleep(0)

    async def test_save_edit_pause_delete_rebuild_only_selected_subscriptions(self):
        saved = await self.save()
        self.assertEqual(self.listeners[-1][0], {"binary_sensor.front_motion"})
        await self.coordinator.async_save_monitor(
            {**saved, "enabled": False}, saved["id"]
        )
        self.assertTrue(self.unsubscribed)
        self.fire()
        self.assertFalse(self.coordinator._tasks)
        await self.coordinator.async_delete_monitor(saved["id"])
        self.assertFalse(self.coordinator.monitors)

    async def test_ha_and_mini_tater_modes_use_same_image_without_hydra_or_speech(self):
        saved = await self.save()
        for mode in ("home_assistant", "tater"):
            with self.subTest(mode=mode):
                self.manager.data["tater_settings"]["assistant_mode"] = mode
                event = await self.coordinator.async_test(saved["id"])
                self.assertEqual(event["status"], "sent")
                self.assertNotIn("image_filename", event)
                self.assertIn("authSig=", event["image_url"])
                command, payload = self.screen.async_send.call_args.args
                self.assertEqual(command, "display.notification")
                self.assertEqual(base64.b64decode(payload["image_data_b64"]), IMAGE)
                self.assertEqual(payload["description"], event["description"])
                prompt, images = self.voice._describe_images.call_args.args
                self.assertIn("Do not assume the trigger proves", prompt)
                self.assertEqual(
                    base64.b64decode(images[0]["data_url"].split(",", 1)[1]), IMAGE
                )
                domain, service, data = self.hass.services.async_call.call_args.args
                self.assertEqual((domain, service), ("notify", "mobile_app_phone"))
                filename = data["data"]["image"].rsplit("/", 1)[1]
                self.assertTrue(
                    data["data"]["image"].startswith("/media/local/tater_awareness/")
                )
                self.assertEqual(
                    (self.coordinator._image_root / filename).read_bytes(), IMAGE
                )
                self.assertNotIn("image_data_b64", str(self.manager.data))
        self.assertEqual(self.voice._describe_images.await_count, 2)

    async def test_duplicate_motion_is_coalesced_and_cooldown_blocks_repeat(self):
        await self.save()
        self.fire()
        self.fire()
        await self.finish()
        self.fire()
        await self.finish()
        self.assertEqual(self.camera.await_count, 1)
        self.assertEqual(len(self.coordinator.history), 1)

    async def test_snapshot_happens_before_waiting_for_a_vision_slot(self):
        saved = await self.save(destinations=["satellite:kitchen"])
        await self.coordinator._slots.acquire()
        await self.coordinator._slots.acquire()
        task = self.coordinator._start(saved, test=False)
        for _ in range(20):
            if self.camera.await_count:
                break
            await asyncio.sleep(0)
        self.camera.assert_awaited_once()
        self.voice._describe_images.assert_not_awaited()
        self.coordinator._slots.release()
        self.coordinator._slots.release()
        self.assertEqual((await task)["status"], "sent")

    async def test_offline_destination_does_not_block_phone_or_repeat_analysis(self):
        saved = await self.save()
        self.screen.connected = False
        result = await self.coordinator.async_test(saved["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            [row["status"] for row in result["deliveries"]], ["failed", "sent"]
        )
        self.assertIn("offline", result["deliveries"][0]["error"])
        self.voice._describe_images.assert_awaited_once()
        self.hass.services.async_call.assert_awaited_once()

    async def test_failed_phone_does_not_block_screen(self):
        saved = await self.save()
        self.hass.services.async_call.side_effect = RuntimeError("Phone unavailable")
        result = await self.coordinator.async_test(saved["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deliveries"][0]["status"], "sent")
        self.assertIn("Phone unavailable", result["deliveries"][1]["error"])

    async def test_stalled_destination_times_out_without_holding_other_delivery(self):
        saved = await self.save()

        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        self.screen.async_send.side_effect = stalled
        with patch.object(awareness, "DELIVERY_TIMEOUT_SECONDS", 0.01):
            result = await self.coordinator.async_test(saved["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deliveries"][0]["error"], "Delivery timed out")
        self.assertEqual(result["deliveries"][1]["status"], "sent")

    async def test_stalled_vision_fails_without_sending_an_unverified_description(self):
        saved = await self.save()

        async def stalled(*args):
            await asyncio.Event().wait()

        self.voice._describe_images.side_effect = stalled
        with patch.object(awareness, "VISION_TIMEOUT_SECONDS", 0.01):
            result = await self.coordinator.async_test(saved["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Camera alert timed out")
        self.screen.async_send.assert_not_awaited()

    async def test_missing_phone_media_storage_does_not_stop_screen_alerts(self):
        saved = await self.save()
        self.coordinator._media_source = ""
        result = await self.coordinator.async_test(saved["id"])
        self.assertEqual(result["status"], "partial")
        self.assertIn("media directory", result["deliveries"][1]["error"])

    async def test_unwritable_history_storage_keeps_direct_screen_delivery_working(
        self,
    ):
        saved = await self.save()
        with patch.object(
            self.coordinator, "_write_image", side_effect=PermissionError("Read only")
        ):
            result = await self.coordinator.async_test(saved["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deliveries"][0]["status"], "sent")
        self.assertIn("Read only", result["image_error"])

    async def test_polling_reuses_signed_thumbnail_urls(self):
        saved = await self.save()
        signer = sys.modules["homeassistant.components.http.auth"]
        with patch.object(
            signer,
            "async_sign_path",
            side_effect=lambda hass, path, expires: path + "?authSig=stable",
        ) as sign:
            result = await self.coordinator.async_test(saved["id"])
            first = self.coordinator.snapshot()
            second = self.coordinator.snapshot()
            self.assertEqual(result["image_url"], first["history"][0]["image_url"])
            self.assertEqual(
                first["history"][0]["image_url"], second["history"][0]["image_url"]
            )
            self.assertEqual(sign.call_count, 1)

    async def test_admin_thumbnails_never_reuse_background_or_other_session_signatures(self):
        saved = await self.save()
        signer = sys.modules["homeassistant.components.http.auth"]

        def sign_for_session(hass, path, expires):
            request = self.current_request.get()
            session = request["hass_refresh_token_id"] if request is not None else "content"
            return path + "?authSig=" + session

        with patch.object(signer, "async_sign_path", side_effect=sign_for_session) as sign:
            background = await self.coordinator.async_test(saved["id"])
            self.assertTrue(background["image_url"].endswith("authSig=content"))
            for session in ("admin-one", "admin-two"):
                context = self.current_request.set({"hass_refresh_token_id": session})
                try:
                    first = self.coordinator.snapshot()["history"][0]["image_url"]
                    self.assertTrue(first.endswith("authSig=" + session))
                    self.assertEqual(self.coordinator.snapshot()["history"][0]["image_url"], first)
                finally:
                    self.current_request.reset(context)
            self.assertEqual(sign.call_count, 3)
        await self.coordinator.async_cleanup()
        self.assertEqual(len(self.coordinator._image_urls), 3)

    async def test_camera_and_vision_failures_are_recorded_without_fake_alerts(self):
        saved = await self.save()
        for stage, stub in (
            ("camera", self.camera),
            ("vision", self.voice._describe_images),
        ):
            with self.subTest(stage=stage):
                stub.side_effect = RuntimeError(f"{stage} unavailable")
                result = await self.coordinator.async_test(saved["id"])
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"], f"{stage} unavailable")
                self.assertFalse(result["deliveries"])
                stub.side_effect = None
        self.screen.async_send.assert_not_awaited()
        self.hass.services.async_call.assert_not_awaited()

    async def test_test_bypasses_pause_and_cooldown_without_enabling_monitor(self):
        saved = await self.save(enabled=False)
        self.fire()
        self.assertFalse(self.coordinator._tasks)
        first = await self.coordinator.async_test(saved["id"])
        second = await self.coordinator.async_test(saved["id"])
        self.assertTrue(first["test"] and second["test"])
        self.assertFalse(self.coordinator.monitors[saved["id"]]["enabled"])

    async def test_deleted_or_paused_monitor_cancels_pending_delivery(self):
        saved = await self.save()
        gate = asyncio.Event()

        async def waiting(*args):
            await gate.wait()
            return "Late response"

        self.voice._describe_images.side_effect = waiting
        self.coordinator._start(saved, test=False)
        while not self.voice._describe_images.await_count:
            await asyncio.sleep(0.001)
        await self.coordinator.async_delete_monitor(saved["id"])
        self.screen.async_send.assert_not_awaited()
        self.assertFalse(self.coordinator._tasks)

    async def test_images_expire_are_removed_and_cannot_traverse_paths(self):
        saved = await self.save()
        result = await self.coordinator.async_test(saved["id"])
        image = await self.coordinator.async_image(result["id"])
        self.assertEqual(image, (IMAGE, "image/jpeg"))
        row = self.coordinator.history[-1]
        row["expires_at"] = time.time() - 1
        self.assertIsNone(await self.coordinator.async_image(result["id"]))
        self.assertIsNone(await self.coordinator.async_image("../../secrets"))
        await self.coordinator.async_cleanup()
        self.assertFalse(list(self.coordinator._image_root.iterdir()))
        self.assertNotIn("image_url", self.coordinator.snapshot()["history"][0])

    async def test_history_and_job_count_are_bounded(self):
        saved = await self.save()
        with patch.object(awareness, "MAX_HISTORY", 2):
            for _ in range(3):
                await self.coordinator.async_test(saved["id"])
            self.assertEqual(len(self.coordinator.history), 2)
            self.assertEqual(len(list(self.coordinator._image_root.iterdir())), 2)
        self.coordinator._tasks = {str(i): Mock() for i in range(awareness.MAX_PENDING)}
        with self.assertRaisesRegex(RuntimeError, "busy"):
            self.coordinator._start(saved, test=False)
        self.coordinator._tasks.clear()

    async def test_catalog_uses_ha_devices_and_capabilities_without_assist_exposure(
        self,
    ):
        catalog = self.coordinator.catalog()
        self.assertEqual(catalog["cameras"][0]["id"], "camera.front_door")
        motion = next(
            row for row in catalog["triggers"] if row["id"].endswith("front_motion")
        )
        self.assertEqual(motion["suggested_for"], ["camera.front_door"])
        self.assertEqual(motion["options"][0]["label"], "Motion detected")
        event = next(
            row for row in catalog["triggers"] if row["id"] == "event.doorbell"
        )
        self.assertEqual(
            [row["value"] for row in event["options"]],
            ["event:ring", "event:double_press", "event:*"],
        )
        self.assertEqual(
            {row["id"] for row in catalog["destinations"]},
            {"satellite:kitchen", "mobile_app:mobile_app_phone"},
        )

    async def test_restart_preserves_monitors_history_and_cooldown(self):
        saved = await self.save()
        await self.coordinator.async_test(saved["id"])
        await self.coordinator.async_shutdown()
        restored = awareness.AwarenessCoordinator(self.manager)
        await restored.async_start()
        self.addAsyncCleanup(restored.async_shutdown)
        self.assertEqual(restored.monitors[saved["id"]], saved)
        self.assertEqual(len(restored.history), 1)
        restored._handle_event(
            SimpleNamespace(
                data={
                    "entity_id": saved["trigger_entity"],
                    "old_state": state(saved["trigger_entity"], "off"),
                    "new_state": state(saved["trigger_entity"], "on"),
                }
            )
        )
        self.assertFalse(restored._tasks)


class AwarenessHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_vision_endpoint_cannot_change_assistant_or_speech_settings(
        self,
    ):
        path = ROOT / "custom_components/tater_satellite/http.py"
        tree = ast.parse(path.read_text())
        node = next(
            row
            for row in tree.body
            if isinstance(row, ast.ClassDef) and row.name == "VisionSettingsView"
        )
        view = type("View", (), {"json": staticmethod(lambda value: value)})
        update = AsyncMock(
            return_value={
                "assistant_mode": "home_assistant",
                "vision_model": "camera-model",
            }
        )
        manager = SimpleNamespace(
            tater_assistant=SimpleNamespace(async_update_settings=update)
        )

        async def body(request):
            return {
                "settings": {
                    "assistant_mode": "tater",
                    "tts_voice": "overwrite",
                    "vision_model": "camera-model",
                }
            }

        scope = {
            "HomeAssistantView": view,
            "API_BASE_PATH": "/api/tater/satellite/v1",
            "_json_body": body,
            "_manager": lambda request: manager,
            "_require_admin": lambda request: None,
        }
        future = ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0
        )
        exec(
            compile(
                ast.fix_missing_locations(
                    ast.Module(body=[future, node], type_ignores=[])
                ),
                str(path),
                "exec",
            ),
            scope,
        )
        result = await scope["VisionSettingsView"]().post(None)
        update.assert_awaited_once_with({"vision_model": "camera-model"})
        self.assertEqual(result["settings"]["assistant_mode"], "home_assistant")

    def test_snapshot_views_and_new_settings_routes_require_authentication(self):
        tree = ast.parse(
            (ROOT / "custom_components/tater_satellite/http.py").read_text()
        )
        names = {
            "VisionSettingsView",
            "AwarenessMonitorsView",
            "AwarenessMonitorView",
            "AwarenessTestView",
            "AwarenessImageView",
            "DoorbellsView",
            "DoorbellView",
            "DoorbellTestView",
        }
        classes = {
            row.name: row
            for row in tree.body
            if isinstance(row, ast.ClassDef) and row.name in names
        }
        self.assertEqual(set(classes), names)
        for name, node in classes.items():
            values = {
                target.id: ast.literal_eval(row.value)
                for row in node.body
                if isinstance(row, ast.Assign)
                for target in row.targets
                if isinstance(target, ast.Name) and target.id == "requires_auth"
            }
            self.assertTrue(values.get("requires_auth"), name)


if __name__ == "__main__":
    unittest.main()
