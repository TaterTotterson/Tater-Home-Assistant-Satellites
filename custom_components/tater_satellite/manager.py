"""Runtime manager for Tater Native satellites."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web
from homeassistant.components.assist_pipeline import (
    async_get_pipeline,
    async_get_pipelines,
)
from homeassistant.components.assist_pipeline.error import PipelineNotFound
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url
from homeassistant.helpers.storage import Store

from .const import (
    MAX_AUDIO_QUEUE_CHUNKS,
    MAX_TEXT_MESSAGE_BYTES,
    PAIRING_CODE_TTL_SECONDS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .firmware import FirmwareCatalog, board_manifest_key, version_tuple
from .protocol import (
    envelope,
    is_wake_verifier_packet,
    message_payload,
    message_type,
    parse_text_message,
    text,
)
from .settings import (
    DEFAULT_SETTINGS,
    SETTINGS_SCHEMA,
    firmware_payload,
    merged_settings,
    normalize_settings,
)
from .trainer import TrainerLinkManager
from .wake_verifier import (
    async_verify_packet,
    normalize_phrase,
    unavailable_result,
)

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)
_MAX_MODEL_BYTES = 512 * 1024
_MAX_SOUND_BYTES = 512 * 1024
_GLOBAL_WAKE_VERIFIER_KEYS = {
    "wake_verifier_mode",
    "wake_verifier_phrase",
    "wake_verifier_phrase_url",
    "wake_verifier_threshold",
    "wake_verifier_window_ms",
    "wake_verifier_timeout_ms",
}
_WAKE_MODEL_SETTING_KEYS = {
    "wake_engine",
    "wake_word",
    "wake_word_url",
    "wake_model_asset_id",
    "wake_sensitivity",
    "wake_environment",
    "wake_threshold",
    "wake_sliding_window",
}
_WAKE_SOUND_SETTING_KEYS = {
    "wake_sound_enabled",
    "wake_sound",
    "wake_sound_url",
    "wake_sound_asset_id",
}
EntityFactory = Callable[["SatelliteRuntime"], list[Any]]


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_device_id(value: Any) -> str:
    token = "".join(
        ch for ch in text(value).lower() if ch.isalnum() or ch in {"-", "_"}
    )
    return token[:80]


def _json_copy(value: Any, default: Any) -> Any:
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return default


def _as_int(value: Any) -> int:
    """Return an integer without trusting device-provided status values."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class SatelliteRuntime:
    """Live and persisted state for one satellite."""

    def __init__(
        self,
        manager: TaterSatelliteManager,
        device_id: str,
        record: dict[str, Any],
    ) -> None:
        self.manager = manager
        self.device_id = device_id
        self.record = record
        self.websocket: web.WebSocketResponse | None = None
        self.send_lock = asyncio.Lock()
        self.connected = False
        self.remote = ""
        self.server_base_url = ""
        self.last_seen = 0.0
        self.last_status: dict[str, Any] = {}
        self.last_error = ""
        self.logs: deque[dict[str, Any]] = deque(maxlen=250)
        self.audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
            maxsize=MAX_AUDIO_QUEUE_CHUNKS
        )
        self.audio_drops = 0
        self.assist_entity: Any = None
        self.pipeline_entity_id = ""
        self.vad_entity_id = ""
        self.created_platforms: set[str] = set()
        self._entities: list[Any] = []
        self.playback_waiters: deque[asyncio.Future[bool]] = deque()
        self.ota_in_progress = False
        self.ota_progress: int | None = None
        self.ota_message = ""
        self.wake_verifier_count = 0
        self.wake_verifier_rejections = 0
        self.wake_verifier_fail_open = 0
        self.wake_verifier_last: dict[str, Any] = {}
        self.settings_sync_state = "never"
        self.settings_sync_message = "Settings have not been sent in this session."
        self.settings_last_push = 0.0
        self.settings_last_confirmed = 0.0
        self.settings_push_baseline = 0
        self.settings_push_count = 0

    @property
    def name(self) -> str:
        """Return the friendly device name."""
        return (
            text(self.record.get("name"))
            or text(self.record.get("device_name"))
            or self.device_id
        )

    @property
    def board(self) -> str:
        """Return the firmware board id."""
        return text(self.record.get("board"))

    @property
    def firmware_version(self) -> str:
        """Return the installed firmware version."""
        return text(self.record.get("firmware_version"))

    @property
    def room(self) -> str:
        """Return the suggested Home Assistant area."""
        return text(self.record.get("room"))

    @property
    def capabilities(self) -> dict[str, bool]:
        """Return declared capabilities."""
        value = self.record.get("capabilities")
        if not isinstance(value, dict):
            return {}
        return {str(key): bool(item) for key, item in value.items()}

    def effective_settings(self) -> dict[str, Any]:
        """Return resolved settings for this satellite."""
        return self.manager.effective_settings(self.device_id)

    async def async_send(
        self, message_type_value: str, payload: dict[str, Any] | None = None
    ) -> bool:
        """Send a JSON command to the device."""
        return await self.async_send_json(envelope(message_type_value, payload or {}))

    async def async_send_json(self, message: dict[str, Any]) -> bool:
        """Send a complete JSON envelope."""
        websocket = self.websocket
        if websocket is None or websocket.closed:
            return False
        try:
            async with self.send_lock:
                if websocket.closed:
                    return False
                await websocket.send_json(message)
            return True
        except (ConnectionError, RuntimeError) as err:
            self.last_error = text(err) or type(err).__name__
            return False

    def add_audio(self, data: bytes) -> None:
        """Queue microphone audio without blocking the WebSocket reader."""
        if not data:
            return
        try:
            self.audio_queue.put_nowait(data)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self.audio_queue.get_nowait()
            self.audio_drops += 1
            with contextlib.suppress(asyncio.QueueFull):
                self.audio_queue.put_nowait(data)

    def finish_audio(self) -> None:
        """End the active microphone stream."""
        try:
            self.audio_queue.put_nowait(None)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self.audio_queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self.audio_queue.put_nowait(None)

    def reset_audio(self) -> None:
        """Clear stale microphone frames."""
        while True:
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def record_wake_verifier_result(self, result: dict[str, Any]) -> None:
        """Record one server-side wake-verifier decision."""
        self.wake_verifier_count += 1
        if not bool(result.get("accepted")):
            self.wake_verifier_rejections += 1
        if not bool(result.get("available", True)):
            self.wake_verifier_fail_open += 1
        self.wake_verifier_last = _json_copy(result, {})
        self.notify()

    def settings_generation(self) -> int:
        """Return the latest settings generation reported by the firmware."""
        status = self.last_status if isinstance(self.last_status, dict) else {}
        live = (
            status.get("live_settings")
            if isinstance(status.get("live_settings"), dict)
            else {}
        )
        return max(
            0,
            _as_int(status.get("settings_generation")),
            _as_int(live.get("wake_settings_generation")),
        )

    def note_settings_status(self) -> None:
        """Confirm a sent settings payload from a newer firmware generation."""
        if (
            self.settings_last_push
            and self.settings_generation() > self.settings_push_baseline
            and self.settings_sync_state in {"sending", "sent", "timeout"}
        ):
            self.settings_sync_state = "confirmed"
            self.settings_sync_message = "Satellite confirmed the live settings."
            self.settings_last_confirmed = time.time()

    def add_log(self, level: str, message: str, *, kind: str = "log") -> None:
        """Append a device log entry."""
        self.logs.append(
            {
                "ts": time.time(),
                "level": level or "info",
                "message": message,
                "type": kind,
            }
        )

    def notify(self) -> None:
        """Notify all entities backed by this runtime."""
        self.manager.notify_runtime(self)

    async def async_play_url(
        self,
        url: str,
        *,
        tts_kind: str = "response",
        state_after: str = "",
        timeout: float = 300.0,
    ) -> bool:
        """Play a URL and wait for the satellite to report completion."""
        if not self.connected:
            raise RuntimeError(f"{self.name} is offline")
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[bool] = loop.create_future()
        self.playback_waiters.append(waiter)
        payload: dict[str, Any] = {"url": url, "tts_kind": tts_kind}
        if state_after:
            payload["state_after"] = state_after
        if not await self.async_send("play.url", payload):
            with contextlib.suppress(ValueError):
                self.playback_waiters.remove(waiter)
            raise RuntimeError(f"Unable to send playback to {self.name}")
        try:
            async with asyncio.timeout(timeout):
                ok = await waiter
                if not ok:
                    raise RuntimeError(f"Playback failed on {self.name}")
                return True
        finally:
            with contextlib.suppress(ValueError):
                self.playback_waiters.remove(waiter)

    def playback_finished(self, ok: bool) -> None:
        """Resolve the oldest pending playback waiter."""
        resolved_waiter = False
        while self.playback_waiters:
            waiter = self.playback_waiters.popleft()
            if not waiter.done():
                waiter.set_result(ok)
                resolved_waiter = True
                break
        # Pipeline TTS is sent without a waiter, and its completion must return
        # the Assist entity to idle. Announcements have their own waiter and the
        # base AssistSatelliteEntity updates state after async_announce returns.
        if not resolved_waiter and self.assist_entity is not None:
            with contextlib.suppress(Exception):
                self.assist_entity.tts_response_finished()
        self.notify()

    def fail_playback_waiters(self) -> None:
        """Fail pending announcements when the satellite disconnects."""
        while self.playback_waiters:
            waiter = self.playback_waiters.popleft()
            if not waiter.done():
                waiter.set_result(False)

    def public_snapshot(self) -> dict[str, Any]:
        """Return panel-safe device state."""
        status = self.last_status if isinstance(self.last_status, dict) else {}
        transport = (
            status.get("transport") if isinstance(status.get("transport"), dict) else {}
        )
        live = (
            status.get("live_settings")
            if isinstance(status.get("live_settings"), dict)
            else {}
        )
        wake_engine = (
            status.get("wake_engine")
            if isinstance(status.get("wake_engine"), dict)
            else {}
        )
        device_verifier = (
            wake_engine.get("verifier")
            if isinstance(wake_engine.get("verifier"), dict)
            else {}
        )
        desired_settings = (
            self.manager.firmware_settings(self.device_id)
            if self.server_base_url
            else firmware_payload(self.effective_settings())
        )
        desired_wake_word = text(desired_settings.get("wake_word"))
        active_wake_word = text(wake_engine.get("active_wake_word"))
        active_model_source = text(wake_engine.get("active_model_source"))
        if desired_wake_word == "custom_url":
            wake_model_matches = bool(
                active_model_source == "url"
                and text(wake_engine.get("active_model_url"))
                == text(desired_settings.get("wake_word_url"))
            )
        else:
            wake_model_matches = bool(
                desired_wake_word and active_wake_word == desired_wake_word
            )
        verifier_checks = max(
            self.wake_verifier_count,
            _as_int(device_verifier.get("completed")),
        )
        verifier_rejections = min(
            verifier_checks,
            max(
                self.wake_verifier_rejections,
                _as_int(device_verifier.get("rejections")),
            ),
        )
        verifier_fail_open = min(
            verifier_checks,
            max(
                self.wake_verifier_fail_open,
                _as_int(device_verifier.get("fail_open")),
            ),
        )
        available = self.manager.firmware.info_for_board(self.board)
        installed = self.firmware_version
        latest = text(available.get("firmware_version"))
        return {
            "device_id": self.device_id,
            "name": self.name,
            "board": self.board,
            "board_key": board_manifest_key(self.board),
            "room": self.room,
            "firmware_version": installed,
            "connected": self.connected,
            "remote": self.remote,
            "last_seen": self.last_seen,
            "last_error": self.last_error,
            "capabilities": self.capabilities,
            "state": text(status.get("state"))
            or ("idle" if self.connected else "offline"),
            "wifi_rssi": status.get("wifi_rssi"),
            "free_heap": status.get("free_heap"),
            "uptime_s": status.get("uptime_s"),
            "xmos_doa": status.get("xmos_doa")
            if isinstance(status.get("xmos_doa"), dict)
            else {},
            "xmos_firmware": status.get("xmos_firmware")
            if isinstance(status.get("xmos_firmware"), dict)
            else {},
            "transport": transport,
            "applied_settings": live,
            "settings_sync": {
                "state": self.settings_sync_state,
                "message": self.settings_sync_message,
                "generation": self.settings_generation(),
                "last_push": self.settings_last_push,
                "last_confirmed": self.settings_last_confirmed,
                "push_count": self.settings_push_count,
            },
            "wake_model": {
                "ready": bool(wake_engine.get("ready")),
                "desired": desired_wake_word,
                "active": active_wake_word,
                "active_label": text(wake_engine.get("active_wake_label")),
                "source": active_model_source,
                "matches": wake_model_matches,
                "downloading": bool(wake_engine.get("custom_download_running")),
                "download_failures": _as_int(
                    wake_engine.get("custom_download_failures")
                ),
                "last_error": text(wake_engine.get("last_error")),
                "desired_wake_sound_enabled": bool(
                    desired_settings.get("wake_sound_enabled")
                ),
                "wake_sound_enabled": (
                    bool(live.get("wake_sound_enabled"))
                    if "wake_sound_enabled" in live
                    else None
                ),
            },
            "settings": self.effective_settings(),
            "overrides": dict(self.record.get("overrides") or {}),
            "pipeline_id": text(self.record.get("pipeline_id")),
            "vad_sensitivity": text(self.record.get("vad_sensitivity")) or "default",
            "audio_drops": self.audio_drops,
            "wake_verifier": {
                "supported": (
                    "wake_verifier_mode" in live
                    or bool(device_verifier)
                    or bool(self.wake_verifier_last)
                ),
                "count": verifier_checks,
                "accepted": max(0, verifier_checks - verifier_rejections),
                "rejections": verifier_rejections,
                "fail_open": verifier_fail_open,
                "last": dict(self.wake_verifier_last),
                "device": dict(device_verifier),
                "target_phrase": self.manager.wake_verifier_phrase(self),
                "pipeline": self.manager.pipeline_info(self),
            },
            "ota": {
                "in_progress": self.ota_in_progress,
                "progress": self.ota_progress,
                "message": self.ota_message,
            },
            "firmware": {
                **available,
                "installed_version": installed,
                "update_available": bool(
                    latest and version_tuple(latest) > version_tuple(installed)
                ),
            },
            "logs": list(self.logs)[-80:],
        }


class TaterSatelliteManager:
    """Own satellite connections, settings, credentials, and firmware."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = {}
        self.runtimes: dict[str, SatelliteRuntime] = {}
        self.firmware = FirmwareCatalog(hass)
        self.trainer = TrainerLinkManager(self)
        self._save_lock = asyncio.Lock()
        self._pairing_code = ""
        self._pairing_expires = 0.0
        self._pairing_claimed_device = ""
        self._platforms: dict[str, tuple[EntityFactory, AddEntitiesCallback]] = {}
        self._assets_root = Path(hass.config.path("tater_satellite", "assets"))
        self._shutting_down = False

    async def async_setup(self) -> None:
        """Load persistent state and prepare services."""
        loaded = await self.store.async_load()
        self.data = loaded if isinstance(loaded, dict) else {}
        self.data.setdefault("global_settings", dict(DEFAULT_SETTINGS))
        self.data["global_settings"] = normalize_settings(
            self.data.get("global_settings")
        )
        self.data.setdefault("devices", {})
        self.data.setdefault("assets", {})
        self.trainer.setup()
        global_settings = self.data["global_settings"]
        if (
            global_settings.get("wake_word") == "custom_url"
            and text(global_settings.get("wake_word_url"))
            and not text(global_settings.get("wake_model_asset_id"))
            and text(global_settings.get("wake_verifier_phrase_url"))
            != text(global_settings.get("wake_word_url"))
        ):
            phrase = await self._async_wake_phrase_from_url(
                text(global_settings.get("wake_word_url"))
            )
            global_settings["wake_verifier_phrase"] = phrase
            global_settings["wake_verifier_phrase_url"] = text(
                global_settings.get("wake_word_url")
            )
            await self.async_save()
        await self.hass.async_add_executor_job(
            self._assets_root.mkdir, 0o755, True, True
        )
        await self.firmware.async_setup()
        for device_id, record in list(self.data["devices"].items()):
            if not isinstance(record, dict):
                continue
            safe_id = _safe_device_id(device_id)
            if not safe_id:
                continue
            self.runtimes[safe_id] = SatelliteRuntime(self, safe_id, record)
        with contextlib.suppress(Exception):
            await self.firmware.async_refresh()

    async def async_shutdown(self) -> None:
        """Close all device connections."""
        self._shutting_down = True
        for runtime in tuple(self.runtimes.values()):
            runtime.finish_audio()
            runtime.fail_playback_waiters()
            websocket = runtime.websocket
            if websocket is not None and not websocket.closed:
                with contextlib.suppress(Exception):
                    await websocket.close(code=1001, message=b"HA stopping")
            runtime.connected = False

    async def async_save(self) -> None:
        """Persist manager data."""
        async with self._save_lock:
            await self.store.async_save(self.data)

    def public_base_url(self) -> str:
        """Return the local Home Assistant URL satellites should use."""
        return get_url(
            self.hass,
            allow_internal=True,
            allow_external=True,
            prefer_external=False,
        ).rstrip("/")

    def start_pairing(self) -> dict[str, Any]:
        """Generate a short-lived pairing code."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._pairing_code = code
        self._pairing_expires = time.time() + PAIRING_CODE_TTL_SECONDS
        self._pairing_claimed_device = ""
        return self.pairing_snapshot()

    def pairing_snapshot(self) -> dict[str, Any]:
        """Return current pairing state."""
        active = bool(
            self._pairing_code
            and self._pairing_expires > time.time()
            and not self._pairing_claimed_device
        )
        code = self._pairing_code if active else ""
        return {
            "active": active,
            "code": f"{code[:3]}-{code[3:]}" if code else "",
            "expires_at": self._pairing_expires if active else 0,
            "claimed_device": self._pairing_claimed_device,
        }

    def _pairing_matches(self, supplied: str) -> bool:
        normalized = "".join(ch for ch in supplied if ch.isdigit())
        return bool(
            self._pairing_code
            and self._pairing_expires > time.time()
            and not self._pairing_claimed_device
            and hmac.compare_digest(normalized, self._pairing_code)
        )

    def _auth_token(self, request: web.Request) -> str:
        token = text(request.headers.get("X-Tater-Token"))
        if token:
            return token
        auth = text(request.headers.get("Authorization"))
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    async def _authenticate(
        self,
        request: web.Request,
        device_id: str,
        hello: dict[str, Any],
    ) -> tuple[bool, str]:
        supplied = self._auth_token(request)
        devices = self.data["devices"]
        record = devices.get(device_id)
        if isinstance(record, dict):
            expected = text(record.get("token_hash"))
            if (
                expected
                and supplied
                and hmac.compare_digest(expected, _token_hash(supplied))
            ):
                return True, ""
            return False, ""

        if not self._pairing_matches(supplied):
            return False, ""

        new_token = secrets.token_urlsafe(32)
        payload = message_payload(hello)
        record = {
            "token_hash": _token_hash(new_token),
            "name": text(payload.get("device_name")) or device_id,
            "board": text(payload.get("board")),
            "firmware_version": text(payload.get("firmware_version")),
            "room": text(payload.get("room")),
            "capabilities": (
                dict(payload["capabilities"])
                if isinstance(payload.get("capabilities"), dict)
                else {}
            ),
            "overrides": {},
            "pipeline_id": "",
            "vad_sensitivity": "default",
            "paired_at": time.time(),
        }
        devices[device_id] = record
        runtime = SatelliteRuntime(self, device_id, record)
        self.runtimes[device_id] = runtime
        self._pairing_claimed_device = device_id
        await self.async_save()
        self._add_runtime_entities(runtime)
        return True, new_token

    def register_platform(
        self,
        platform: str,
        factory: EntityFactory,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Register an entity factory and add existing satellites."""
        self._platforms[platform] = (factory, async_add_entities)
        for runtime in self.runtimes.values():
            self._add_runtime_platform(runtime, platform)

    def _add_runtime_platform(self, runtime: SatelliteRuntime, platform: str) -> None:
        if platform in runtime.created_platforms:
            return
        row = self._platforms.get(platform)
        if row is None:
            return
        factory, add_entities = row
        entities = factory(runtime)
        runtime.created_platforms.add(platform)
        if entities:
            add_entities(entities)

    def _add_runtime_entities(self, runtime: SatelliteRuntime) -> None:
        for platform in self._platforms:
            self._add_runtime_platform(runtime, platform)

    def notify_runtime(self, runtime: SatelliteRuntime) -> None:
        """Schedule entity state refreshes for one runtime."""
        for entity in runtime._entities:
            if getattr(entity, "hass", None) is not None:
                with contextlib.suppress(Exception):
                    entity.async_write_ha_state()

    def attach_entity(self, runtime: SatelliteRuntime, entity: Any) -> None:
        """Track an entity for state updates."""
        runtime._entities.append(entity)

    def effective_settings(self, device_id: str) -> dict[str, Any]:
        """Resolve global settings and per-device overrides."""
        runtime = self.runtimes.get(device_id)
        overrides = (
            runtime.record.get("overrides")
            if runtime is not None and isinstance(runtime.record.get("overrides"), dict)
            else {}
        )
        return merged_settings(self.data.get("global_settings"), overrides)

    def _asset_url(
        self,
        asset_id: str,
        filename_key: str,
        *,
        base_url: str,
    ) -> str:
        assets = self.data.get("assets")
        row = assets.get(asset_id) if isinstance(assets, dict) else None
        if not isinstance(row, dict):
            return ""
        filename = text(row.get(filename_key))
        token = text(row.get("token"))
        if not filename or not token:
            return ""
        return (
            f"{base_url}/api/tater/satellite/v1/assets/"
            f"{asset_id}/{filename}?token={token}"
        )

    def firmware_settings(self, device_id: str) -> dict[str, Any]:
        """Build firmware settings, resolving uploaded assets to signed URLs."""
        settings = self.effective_settings(device_id)
        model_asset = text(settings.get("wake_model_asset_id"))
        sound_asset = text(settings.get("wake_sound_asset_id"))
        runtime = self.runtimes.get(device_id)
        base_url = (
            runtime.server_base_url
            if runtime is not None and runtime.server_base_url
            else self.public_base_url()
        )
        if settings.get("wake_word") == "custom_url" and model_asset:
            settings["wake_word_url"] = self._asset_url(
                model_asset,
                "manifest_filename",
                base_url=base_url,
            )
        if settings.get("wake_sound") == "custom" and sound_asset:
            settings["wake_sound_url"] = self._asset_url(
                sound_asset,
                "filename",
                base_url=base_url,
            )
        return firmware_payload(settings)

    async def async_push_settings(
        self,
        runtime: SatelliteRuntime,
    ) -> bool:
        """Push current live settings; track firmware confirmation asynchronously."""
        if not runtime.connected:
            runtime.settings_sync_state = "offline"
            runtime.settings_sync_message = (
                "Satellite is offline; settings will be sent when it reconnects."
            )
            return False

        runtime.settings_push_baseline = runtime.settings_generation()
        runtime.settings_last_push = time.time()
        runtime.settings_push_count += 1
        runtime.settings_sync_state = "sending"
        runtime.settings_sync_message = "Sending live settings to the satellite."
        sent = await runtime.async_send(
            "settings", self.firmware_settings(runtime.device_id)
        )
        if not sent:
            runtime.settings_sync_state = "failed"
            runtime.settings_sync_message = "The settings message could not be sent."
            runtime.notify()
            return False

        runtime.settings_sync_state = "sent"
        runtime.settings_sync_message = "Waiting for the satellite to confirm settings."
        runtime.notify()
        return True

    async def _async_wake_phrase_from_url(self, url: str) -> str:
        """Read the wake phrase from a microWakeWord JSON manifest."""
        value = text(url)
        if not value:
            return ""
        try:
            async with asyncio.timeout(3):
                response = await async_get_clientsession(self.hass).get(
                    value,
                    headers={"Accept": "application/json"},
                )
                async with response:
                    response.raise_for_status()
                    raw = await response.content.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("wake manifest is larger than 64 KB")
            manifest = json.loads(raw)
            if not isinstance(manifest, dict):
                return ""
            return normalize_phrase(manifest.get("wake_word"))[:120].strip()
        except (TimeoutError, ValueError):
            return ""
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Unable to read custom wake phrase from manifest: %s",
                type(err).__name__,
            )
            return ""

    @staticmethod
    def _global_override_keys(changed_keys: set[str]) -> set[str]:
        """Expand dependent settings that must move together across satellites."""
        keys = set(changed_keys)
        if keys.intersection(_WAKE_MODEL_SETTING_KEYS):
            keys.update(_WAKE_MODEL_SETTING_KEYS)
        if keys.intersection(_WAKE_SOUND_SETTING_KEYS):
            keys.update(_WAKE_SOUND_SETTING_KEYS)
        if keys.intersection(_GLOBAL_WAKE_VERIFIER_KEYS):
            keys.update(_GLOBAL_WAKE_VERIFIER_KEYS)
        return keys

    async def async_set_global_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        """Save global defaults and update every connected satellite."""
        current = normalize_settings(self.data.get("global_settings"))
        patch = normalize_settings(values, base=current, partial=True)
        if "wake_word_url" in patch and text(patch.get("wake_word_url")) != text(
            current.get("wake_word_url")
        ):
            patch["wake_model_asset_id"] = ""
        if "wake_sound_url" in patch and text(patch.get("wake_sound_url")) != text(
            current.get("wake_sound_url")
        ):
            patch["wake_sound_asset_id"] = ""
        next_settings = normalize_settings({**current, **patch})
        if (
            next_settings.get("wake_word") == "custom_url"
            and text(next_settings.get("wake_word_url"))
            and not text(next_settings.get("wake_model_asset_id"))
        ):
            phrase = await self._async_wake_phrase_from_url(
                text(next_settings.get("wake_word_url"))
            )
            if not phrase and text(current.get("wake_verifier_phrase_url")) == text(
                next_settings.get("wake_word_url")
            ):
                phrase = normalize_phrase(current.get("wake_verifier_phrase"))
            next_settings["wake_verifier_phrase"] = phrase
            next_settings["wake_verifier_phrase_url"] = text(
                next_settings.get("wake_word_url")
            )
        elif next_settings.get("wake_word") != "custom_url" or text(
            next_settings.get("wake_model_asset_id")
        ):
            next_settings["wake_verifier_phrase"] = ""
            next_settings["wake_verifier_phrase_url"] = ""
        changed_keys = {
            key for key, value in next_settings.items() if value != current.get(key)
        }
        override_keys = self._global_override_keys(changed_keys)
        self.data["global_settings"] = next_settings
        if override_keys:
            for runtime in self.runtimes.values():
                overrides = runtime.record.get("overrides")
                if isinstance(overrides, dict):
                    runtime.record["overrides"] = {
                        key: value
                        for key, value in overrides.items()
                        if key not in override_keys
                    }
                if override_keys.intersection(_WAKE_MODEL_SETTING_KEYS):
                    runtime.record.pop("wake_verifier_phrase", None)
                    runtime.record.pop("wake_verifier_phrase_url", None)
        await self.async_save()
        connected = [runtime for runtime in self.runtimes.values() if runtime.connected]
        results = await asyncio.gather(
            *(self.async_push_settings(runtime) for runtime in connected),
            return_exceptions=True,
        )
        for runtime in self.runtimes.values():
            runtime.notify()
        failed = [
            runtime.name
            for runtime, result in zip(connected, results, strict=True)
            if result is not True
        ]
        if failed:
            raise RuntimeError(
                "Settings were saved, but they could not be sent to these satellites: "
                + ", ".join(failed)
            )
        return dict(self.data["global_settings"])

    async def async_publish_trainer_wake_word(
        self,
        wake_word: str,
        wake_word_url: str,
    ) -> dict[str, Any]:
        """Make a trainer-published wake word authoritative for every satellite."""
        current = normalize_settings(self.data.get("global_settings"))
        self.data["global_settings"] = normalize_settings(
            {
                **current,
                "wake_word": "custom_url",
                "wake_word_url": wake_word_url,
                "wake_model_asset_id": "",
                "wake_verifier_phrase": wake_word,
                "wake_verifier_phrase_url": wake_word_url,
            }
        )
        wake_override_keys = {
            "wake_word",
            "wake_word_url",
            "wake_model_asset_id",
            "wake_verifier_phrase",
            "wake_verifier_phrase_url",
        }
        for runtime in self.runtimes.values():
            overrides = runtime.record.get("overrides")
            if isinstance(overrides, dict):
                runtime.record["overrides"] = {
                    key: value
                    for key, value in overrides.items()
                    if key not in wake_override_keys
                }
            runtime.record.pop("wake_verifier_phrase", None)
            runtime.record.pop("wake_verifier_phrase_url", None)
        await self.async_save()
        connected = [runtime for runtime in self.runtimes.values() if runtime.connected]
        results = await asyncio.gather(
            *(self.async_push_settings(runtime) for runtime in connected),
            return_exceptions=True,
        )
        for runtime in self.runtimes.values():
            runtime.notify()
        failed = [
            runtime.name
            for runtime, result in zip(connected, results, strict=True)
            if result is not True
        ]
        if failed:
            raise RuntimeError(
                "Wake word was saved, but it could not be sent to these satellites: "
                + ", ".join(failed)
            )
        return {
            "settings": dict(self.data["global_settings"]),
            "push": {
                "count": sum(result is True for result in results),
                "attempted": len(connected),
            },
            "wake_word_name": wake_word,
        }

    async def async_set_device_settings(
        self,
        device_id: str,
        values: dict[str, Any],
        *,
        pipeline_id: str | None = None,
        vad_sensitivity: str | None = None,
    ) -> dict[str, Any]:
        """Save per-satellite overrides and push them live."""
        runtime = self.runtimes.get(device_id)
        if runtime is None:
            raise KeyError("Satellite not found")
        existing = (
            dict(runtime.record.get("overrides"))
            if isinstance(runtime.record.get("overrides"), dict)
            else {}
        )
        base = self.effective_settings(device_id)
        device_values = {
            key: value
            for key, value in values.items()
            if key not in _GLOBAL_WAKE_VERIFIER_KEYS
        }
        if "wake_word_url" in device_values and text(
            device_values.get("wake_word_url")
        ) != text(base.get("wake_word_url")):
            device_values["wake_model_asset_id"] = ""
        if "wake_sound_url" in device_values and text(
            device_values.get("wake_sound_url")
        ) != text(base.get("wake_sound_url")):
            device_values["wake_sound_asset_id"] = ""
        patch = normalize_settings(device_values, base=base, partial=True)
        existing.update(patch)
        runtime.record["overrides"] = existing
        if {
            "wake_word",
            "wake_word_url",
            "wake_model_asset_id",
        }.intersection(patch):
            effective = runtime.effective_settings()
            if effective.get("wake_word") == "custom_url" and not text(
                effective.get("wake_model_asset_id")
            ):
                phrase = await self._async_wake_phrase_from_url(
                    text(effective.get("wake_word_url"))
                )
                if not phrase and text(
                    runtime.record.get("wake_verifier_phrase_url")
                ) == text(effective.get("wake_word_url")):
                    phrase = normalize_phrase(
                        runtime.record.get("wake_verifier_phrase")
                    )
                runtime.record["wake_verifier_phrase"] = phrase
                runtime.record["wake_verifier_phrase_url"] = text(
                    effective.get("wake_word_url")
                )
            else:
                runtime.record.pop("wake_verifier_phrase", None)
                runtime.record.pop("wake_verifier_phrase_url", None)
        if pipeline_id is not None:
            runtime.record["pipeline_id"] = text(pipeline_id)
        if vad_sensitivity is not None:
            value = text(vad_sensitivity).lower()
            runtime.record["vad_sensitivity"] = (
                value if value in {"default", "relaxed", "aggressive"} else "default"
            )
        await self.async_save()
        if runtime.connected and not await self.async_push_settings(runtime):
            raise RuntimeError(
                f"Settings were saved, but they could not be sent to {runtime.name}."
            )
        runtime.notify()
        return runtime.public_snapshot()

    async def async_reset_device_settings(self, device_id: str) -> dict[str, Any]:
        """Remove all firmware setting overrides for one satellite."""
        runtime = self.runtimes.get(device_id)
        if runtime is None:
            raise KeyError("Satellite not found")
        runtime.record["overrides"] = {}
        runtime.record.pop("wake_verifier_phrase", None)
        runtime.record.pop("wake_verifier_phrase_url", None)
        await self.async_save()
        if runtime.connected and not await self.async_push_settings(runtime):
            raise RuntimeError(
                f"Settings were reset, but they could not be sent to {runtime.name}."
            )
        runtime.notify()
        return runtime.public_snapshot()

    async def async_resync_settings(self, device_id: str) -> dict[str, Any]:
        """Force-send current settings using the same live path as Tater."""
        runtime = self.runtimes.get(device_id)
        if runtime is None:
            raise KeyError("Satellite not found")
        if not runtime.connected:
            raise RuntimeError(f"{runtime.name} is offline")
        if not await self.async_push_settings(runtime):
            raise RuntimeError(f"Live settings could not be sent to {runtime.name}.")
        return runtime.public_snapshot()

    async def async_upload_asset(
        self,
        kind: str,
        filename: str,
        label: str,
        data_b64: str,
    ) -> dict[str, Any]:
        """Validate and store a custom wake model or wake sound."""
        try:
            raw = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError) as err:
            raise ValueError("Asset data is not valid base64") from err
        kind = text(kind).lower()
        if kind == "wake_model":
            if not raw or len(raw) > _MAX_MODEL_BYTES:
                raise ValueError("Wake model must be 512 KB or smaller")
            if len(raw) < 8 or raw[4:8] != b"TFL3":
                raise ValueError("Uploaded file is not a TensorFlow Lite model")
            extension = ".tflite"
        elif kind == "wake_sound":
            if not raw or len(raw) > _MAX_SOUND_BYTES:
                raise ValueError("Wake sound must be 512 KB or smaller")
            if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
                raise ValueError("Uploaded wake sound must be a WAV file")
            extension = ".wav"
        else:
            raise ValueError("Unsupported asset kind")

        digest = hashlib.sha256(raw).hexdigest()
        asset_id = f"{kind}_{digest[:16]}"
        asset_dir = self._assets_root / asset_id
        safe_label = text(label)[:80] or Path(filename).stem or "Custom"
        asset_filename = f"{asset_id}{extension}"
        asset_path = asset_dir / asset_filename
        manifest_filename = f"{asset_id}.json"
        manifest_path = asset_dir / manifest_filename

        def write() -> None:
            asset_dir.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(raw)
            if kind == "wake_model":
                manifest = {
                    "type": "micro",
                    "wake_word": safe_label,
                    "model": asset_filename,
                    "micro": {
                        "probability_cutoff": float(DEFAULT_SETTINGS["wake_threshold"]),
                        "sliding_window_size": int(
                            DEFAULT_SETTINGS["wake_sliding_window"]
                        ),
                    },
                    "tater_native": {
                        "close_miss_threshold": float(
                            DEFAULT_SETTINGS["close_miss_threshold"]
                        )
                    },
                }
                manifest_path.write_text(
                    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
                )

        await self.hass.async_add_executor_job(write)
        row = {
            "id": asset_id,
            "kind": kind,
            "label": safe_label,
            "filename": asset_filename,
            "manifest_filename": (manifest_filename if kind == "wake_model" else ""),
            "sha256": digest,
            "size_bytes": len(raw),
            "token": secrets.token_urlsafe(24),
            "created_at": time.time(),
        }
        self.data["assets"][asset_id] = row
        await self.async_save()
        return dict(row)

    def asset_file(
        self, asset_id: str, filename: str, token: str
    ) -> tuple[Path, str] | None:
        """Resolve an uploaded asset by opaque token."""
        row = self.data.get("assets", {}).get(asset_id)
        if not isinstance(row, dict):
            return None
        expected = text(row.get("token"))
        if not expected or not hmac.compare_digest(expected, text(token)):
            return None
        allowed = {
            text(row.get("filename")),
            text(row.get("manifest_filename")),
        }
        clean = Path(filename).name
        if clean not in allowed:
            return None
        path = self._assets_root / asset_id / clean
        if not path.is_file():
            return None
        content_type = (
            "application/json"
            if clean.endswith(".json")
            else ("audio/wav" if clean.endswith(".wav") else "application/octet-stream")
        )
        return path, content_type

    async def async_forget(self, device_id: str) -> None:
        """Forget an offline satellite and its credential."""
        runtime = self.runtimes.get(device_id)
        if runtime is None:
            raise KeyError("Satellite not found")
        if runtime.connected:
            raise RuntimeError("Disconnect the satellite before forgetting it")
        self.runtimes.pop(device_id, None)
        self.data["devices"].pop(device_id, None)
        await self.async_save()

    async def async_install_firmware(self, device_id: str) -> dict[str, Any]:
        """Prepare and command a board-matched OTA update."""
        runtime = self.runtimes.get(device_id)
        if runtime is None:
            raise KeyError("Satellite not found")
        if not runtime.connected:
            raise RuntimeError("Satellite is offline")
        signed = await self.firmware.async_prepare(runtime.board, "ota")
        base_url = runtime.server_base_url or self.public_base_url()
        url = (
            f"{base_url}/api/tater/satellite/v1/firmware/file/"
            f"{signed.filename}?token={signed.token}"
        )
        runtime.ota_in_progress = True
        runtime.ota_progress = 0
        runtime.ota_message = "OTA command sent"
        runtime.notify()
        if not await runtime.async_send("ota.url", {"url": url}):
            runtime.ota_in_progress = False
            raise RuntimeError("Unable to send OTA command")
        return {"ok": True, "url": url, "device": runtime.public_snapshot()}

    async def async_identify(self, device_id: str) -> None:
        """Play a short local tone to identify a satellite."""
        runtime = self.runtimes.get(device_id)
        if runtime is None or not runtime.connected:
            raise RuntimeError("Satellite is offline")
        await runtime.async_send(
            "play.tone",
            {"frequency_hz": 1040, "duration_ms": 350, "volume_percent": 55},
        )

    def pipelines_snapshot(self) -> list[dict[str, str]]:
        """Return Assist pipeline ids and names."""
        return [
            {"id": pipeline.id, "name": pipeline.name}
            for pipeline in async_get_pipelines(self.hass)
        ]

    def pipeline_info(self, runtime: SatelliteRuntime) -> dict[str, Any]:
        """Return the Assist pipeline and STT engine selected for a satellite."""
        selected_id = text(runtime.record.get("pipeline_id")) or None
        try:
            pipeline = async_get_pipeline(self.hass, pipeline_id=selected_id)
        except PipelineNotFound:
            return {
                "id": selected_id or "",
                "name": "Unavailable",
                "stt_engine": "",
                "stt_language": "",
                "stt_ready": False,
            }
        return {
            "id": pipeline.id,
            "name": pipeline.name,
            "stt_engine": text(pipeline.stt_engine),
            "stt_language": text(pipeline.stt_language or pipeline.language),
            "stt_ready": bool(pipeline.stt_engine),
        }

    def wake_verifier_phrase(self, runtime: SatelliteRuntime) -> str:
        """Resolve the current wake phrase without maintaining alias lists."""
        settings = runtime.effective_settings()
        wake_word = text(settings.get("wake_word"))
        if wake_word and wake_word != "custom_url":
            return normalize_phrase(wake_word)

        asset_id = text(settings.get("wake_model_asset_id"))
        assets = self.data.get("assets")
        asset = assets.get(asset_id) if asset_id and isinstance(assets, dict) else None
        if isinstance(asset, dict):
            phrase = normalize_phrase(asset.get("label"))
            if phrase:
                return phrase

        effective_url = text(settings.get("wake_word_url"))
        device_phrase = normalize_phrase(runtime.record.get("wake_verifier_phrase"))
        device_phrase_url = text(runtime.record.get("wake_verifier_phrase_url"))
        if device_phrase and effective_url and effective_url == device_phrase_url:
            return device_phrase

        global_settings = normalize_settings(self.data.get("global_settings"))
        global_url = text(global_settings.get("wake_word_url"))
        phrase_url = text(global_settings.get("wake_verifier_phrase_url"))
        explicit = normalize_phrase(global_settings.get("wake_verifier_phrase"))
        if (
            explicit
            and effective_url
            and effective_url == global_url
            and effective_url == phrase_url
        ):
            return explicit

        trainer = self.trainer.status()
        trainer_url = text(trainer.get("last_wake_word_url"))
        if effective_url and effective_url == trainer_url:
            return normalize_phrase(trainer.get("last_wake_word"))
        return ""

    async def _async_handle_wake_verifier_packet(
        self,
        runtime: SatelliteRuntime,
        data: bytes,
        websocket: web.WebSocketResponse,
    ) -> None:
        """Verify one pre-wake audio clip without blocking the socket reader."""
        settings = runtime.effective_settings()
        mode = text(settings.get("wake_verifier_mode")).lower()
        phrase = self.wake_verifier_phrase(runtime)
        if mode not in {"observe", "enforce"}:
            result = unavailable_result(
                data,
                "wake_verifier_disabled_fail_open",
                phrase=phrase,
                mode="off",
            )
        else:
            result = await async_verify_packet(
                self.hass,
                data,
                pipeline_id=text(runtime.record.get("pipeline_id")) or None,
                phrase=phrase,
                mode=mode,
                threshold=float(settings.get("wake_verifier_threshold") or 0.85),
                timeout_ms=int(settings.get("wake_verifier_timeout_ms") or 500),
            )

        try:
            async with runtime.send_lock:
                if runtime.websocket is not websocket or websocket.closed:
                    return
                await websocket.send_json(envelope("wake.verify.result", result))
        except (ConnectionError, RuntimeError):
            return
        runtime.record_wake_verifier_result(result)
        _LOGGER.info(
            "Wake verifier device=%s request=%s mode=%s accepted=%s "
            "available=%s score=%.3f stt_ms=%.1f total_ms=%.1f "
            "transcript=%r reason=%s",
            runtime.device_id,
            result.get("request_id"),
            mode,
            bool(result.get("accepted")),
            bool(result.get("available")),
            float(result.get("score") or 0),
            float(result.get("stt_ms") or 0),
            float(result.get("total_ms") or 0),
            text(result.get("transcript")),
            text(result.get("reason")),
        )

    def snapshot(self) -> dict[str, Any]:
        """Return the complete management-panel payload."""
        assets = [
            {key: value for key, value in row.items() if key != "token"}
            for row in self.data.get("assets", {}).values()
            if isinstance(row, dict)
        ]
        return {
            "configured": True,
            "server_address": self.public_base_url(),
            "websocket_path": "/api/tater/satellite/v1/ws",
            "pairing": self.pairing_snapshot(),
            "trainer_link": {
                **self.trainer.status(),
                "pairing": self.trainer.pairing_snapshot(),
            },
            "global_settings": dict(self.data.get("global_settings") or {}),
            "settings_schema": _json_copy(SETTINGS_SCHEMA, []),
            "assets": assets,
            "pipelines": self.pipelines_snapshot(),
            "firmware": self.firmware.snapshot(),
            "devices": [
                runtime.public_snapshot()
                for runtime in sorted(
                    self.runtimes.values(), key=lambda item: item.name.lower()
                )
            ],
        }

    async def _update_record_from_hello(
        self, runtime: SatelliteRuntime, payload: dict[str, Any]
    ) -> None:
        changed = False
        for key, source in (
            ("name", "device_name"),
            ("board", "board"),
            ("firmware_version", "firmware_version"),
            ("room", "room"),
        ):
            value = text(payload.get(source))
            if value and runtime.record.get(key) != value:
                runtime.record[key] = value
                changed = True
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, dict) and capabilities != runtime.record.get(
            "capabilities"
        ):
            runtime.record["capabilities"] = dict(capabilities)
            changed = True
        if changed:
            await self.async_save()

    async def _handle_text_message(
        self, runtime: SatelliteRuntime, message: dict[str, Any]
    ) -> None:
        kind = message_type(message)
        payload = message_payload(message)
        runtime.last_seen = time.time()
        if kind == "status":
            runtime.last_status = payload
            runtime.note_settings_status()
            runtime.notify()
            return
        if kind in {"log", "ota.status"}:
            level = text(payload.get("level")) or (
                "error" if text(payload.get("status")) == "error" else "info"
            )
            message_text = text(payload.get("message"))
            if kind == "ota.status":
                status = text(payload.get("status")).lower()
                progress = payload.get("progress")
                runtime.ota_progress = (
                    int(progress)
                    if isinstance(progress, (int, float))
                    else runtime.ota_progress
                )
                runtime.ota_message = message_text or status
                runtime.ota_in_progress = status not in {
                    "done",
                    "complete",
                    "success",
                    "error",
                    "failed",
                }
                if status in {"error", "failed"}:
                    runtime.last_error = runtime.ota_message
            runtime.add_log(level, message_text, kind=kind)
            runtime.notify()
            return
        if kind in {"voice.start", "audio.start"}:
            ok = False
            if runtime.assist_entity is not None:
                ok = await runtime.assist_entity.async_device_voice_start(payload)
            await runtime.async_send_json(
                envelope(
                    "voice.start.ack",
                    {"ok": ok},
                    message_id=text(message.get("id")),
                )
            )
            return
        if kind in {"voice.stop", "audio.stop"}:
            if runtime.assist_entity is not None:
                await runtime.assist_entity.async_device_voice_stop(payload)
            await runtime.async_send_json(
                envelope(
                    "voice.stop.ack",
                    {"ok": True},
                    message_id=text(message.get("id")),
                )
            )
            return
        if kind in {
            "announcement.finished",
            "playback.finished",
            "tts.finished",
        }:
            runtime.playback_finished(bool(payload.get("ok", True)))
            await runtime.async_send_json(
                envelope(
                    "announcement.finished.ack",
                    {"ok": True},
                    message_id=text(message.get("id")),
                )
            )
            return
        if kind == "timer.event":
            # Device-side expiry/stop is reflected locally. Home Assistant's
            # timer manager remains authoritative and will issue its next sync.
            runtime.add_log(
                "info",
                f"Timer {text(payload.get('event')) or 'event'}: "
                f"{text(payload.get('label')) or text(payload.get('id'))}",
                kind=kind,
            )
            await runtime.async_send_json(
                envelope(
                    "timer.event.ack",
                    {"ok": True},
                    message_id=text(message.get("id")),
                )
            )
            return
        if kind == "ping":
            await runtime.async_send_json(
                envelope(
                    "pong",
                    {"ok": True},
                    message_id=text(message.get("id")),
                )
            )

    async def async_handle_websocket(self, request: web.Request) -> web.StreamResponse:
        """Accept a firmware WebSocket connection."""
        # The firmware owns the RFC 6455 heartbeat and reconnect watchdog.
        # A second aiohttp heartbeat can expire while the ESP32 is streaming or
        # fetching TTS audio, causing a healthy completed turn to reconnect.
        websocket = web.WebSocketResponse(
            max_msg_size=max(MAX_TEXT_MESSAGE_BYTES, 2 * 1024 * 1024),
            autoclose=True,
        )
        await websocket.prepare(request)
        runtime: SatelliteRuntime | None = None
        try:
            first = await asyncio.wait_for(websocket.receive(), timeout=10)
            if first.type != WSMsgType.TEXT:
                await websocket.send_json(
                    envelope(
                        "error",
                        {"ok": False, "error": "First message must be hello"},
                    )
                )
                await websocket.close(code=1002)
                return websocket
            if len(first.data.encode("utf-8")) > MAX_TEXT_MESSAGE_BYTES:
                await websocket.close(code=1009)
                return websocket
            hello = parse_text_message(first.data)
            if message_type(hello) != "hello":
                await websocket.close(code=1002)
                return websocket
            payload = message_payload(hello)
            device_id = _safe_device_id(payload.get("device_id") or payload.get("id"))
            if not device_id:
                await websocket.close(code=1008)
                return websocket
            authorized, new_token = await self._authenticate(request, device_id, hello)
            if not authorized:
                await websocket.send_json(
                    envelope(
                        "error",
                        {
                            "ok": False,
                            "error": (
                                "Satellite is not paired. Start pairing in "
                                "Tater Satellites and enter that code during setup."
                            ),
                        },
                    )
                )
                await websocket.close(code=1008)
                return websocket
            runtime = self.runtimes[device_id]
            old_socket = runtime.websocket
            if old_socket is not None and not old_socket.closed:
                with contextlib.suppress(Exception):
                    await old_socket.close(code=1012, message=b"Replaced by reconnect")
            runtime.websocket = websocket
            runtime.connected = True
            runtime.last_status = {}
            runtime.server_base_url = f"{request.scheme}://{request.host}".rstrip("/")
            runtime.remote = request.remote or (
                request.transport.get_extra_info("peername")[0]
                if request.transport and request.transport.get_extra_info("peername")
                else ""
            )
            runtime.last_seen = time.time()
            runtime.last_error = ""
            await self._update_record_from_hello(runtime, payload)
            ack_payload: dict[str, Any] = {
                "ok": True,
                "protocol": 1,
                "selector": device_id,
                "server": "home_assistant",
                "capabilities": {
                    "settings": True,
                    "state": True,
                    "led": True,
                    "play_url": True,
                    "voice_stream": True,
                    "pcm_binary": True,
                    "wake_verifier": True,
                    "timers": True,
                    "ota": True,
                },
            }
            if new_token:
                ack_payload["device_token"] = new_token
            await runtime.async_send_json(
                envelope(
                    "hello.ack",
                    ack_payload,
                    message_id=text(hello.get("id")),
                )
            )
            await runtime.async_send("state", {"state": "idle"})
            await self.async_push_settings(runtime)
            runtime.notify()

            async for frame in websocket:
                if frame.type == WSMsgType.TEXT:
                    if len(frame.data.encode("utf-8")) > MAX_TEXT_MESSAGE_BYTES:
                        await websocket.close(code=1009)
                        break
                    try:
                        message = parse_text_message(frame.data)
                        await self._handle_text_message(runtime, message)
                    except (ValueError, json.JSONDecodeError) as err:
                        await runtime.async_send(
                            "error", {"ok": False, "error": str(err)}
                        )
                    except Exception as err:
                        _LOGGER.exception(
                            "Unable to handle message from %s",
                            runtime.device_id,
                        )
                        await runtime.async_send(
                            "error",
                            {
                                "ok": False,
                                "error": str(err) or type(err).__name__,
                            },
                        )
                elif frame.type == WSMsgType.BINARY:
                    data = bytes(frame.data or b"")
                    if is_wake_verifier_packet(data):
                        self.entry.async_create_background_task(
                            self.hass,
                            self._async_handle_wake_verifier_packet(
                                runtime,
                                data,
                                websocket,
                            ),
                            f"tater_satellite_wake_verifier_{runtime.device_id}",
                        )
                    elif runtime.assist_entity is not None:
                        runtime.assist_entity.device_audio(data)
                elif frame.type in {
                    WSMsgType.CLOSE,
                    WSMsgType.CLOSED,
                    WSMsgType.ERROR,
                }:
                    break
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await websocket.close(code=1002)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.exception("Tater satellite WebSocket failed")
            if runtime is not None:
                runtime.last_error = text(err) or type(err).__name__
        finally:
            if runtime is not None and runtime.websocket is websocket:
                close_code = websocket.close_code
                websocket_error = websocket.exception()
                close_detail = (
                    f"WebSocket disconnected (code {close_code or 'unknown'}"
                    f"{f': {websocket_error}' if websocket_error else ''})"
                )
                abnormal_close = close_code not in {1000, 1001}
                runtime.add_log(
                    "warning" if abnormal_close else "info",
                    close_detail,
                    kind="transport",
                )
                if abnormal_close and not self._shutting_down:
                    runtime.last_error = close_detail
                if runtime.assist_entity is not None:
                    with contextlib.suppress(Exception):
                        await runtime.assist_entity.async_device_voice_stop(
                            {"abort": True}
                        )
                runtime.websocket = None
                runtime.connected = False
                runtime.finish_audio()
                runtime.fail_playback_waiters()
                runtime.notify()
        return websocket
