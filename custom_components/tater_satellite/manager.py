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
from urllib.parse import urljoin

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
from homeassistant.util import dt as dt_util

from .const import (
    MAX_AUDIO_QUEUE_CHUNKS,
    MAX_TEXT_MESSAGE_BYTES,
    PAIRING_CODE_TTL_SECONDS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .bluetooth_proxy import TaterBluetoothProxyManager
from .firmware import FirmwareCatalog, board_manifest_key, version_tuple
from .intercom import TaterIntercomCoordinator, is_intercom_request
from .media import TaterMediaCoordinator
from .ota import OTA_VERIFY_TIMEOUT_SECONDS, OtaState
from .pairing import (
    PAIRING_RETRY_GRACE_SECONDS,
    normalize_hardware_id,
    pairing_retry_token,
)
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
    WAKE_FAMILIES,
    WAKE_FAMILY_SETTING_KEYS,
    board_supports_screen_settings,
    firmware_payload,
    merged_settings,
    normalize_settings,
    normalize_wake_family_settings,
    wake_family_for,
)
from .trainer import TrainerLinkManager
from .wake_verifier import (
    async_verify_packet,
    normalize_phrase,
    unavailable_result,
)
from .wake_word_catalog import WakeWordCatalog, resolve_wake_word_source_values

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)
_MAX_MODEL_BYTES = 512 * 1024
_MAX_SOUND_BYTES = 512 * 1024
_MAX_DEVICE_TEXT_FRAME_BYTES = 1000
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
    "wake_detector_mode",
    "wake_mww_enabled",
    "wake_oww_enabled",
    "wake_word",
    "wake_word_url",
    "wake_model_revision",
    "wake_model_asset_id",
    "oww_wake_word",
    "oww_wake_word_url",
    "oww_model_revision",
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
_SETTINGS_WIRE_GROUPS = (
    (
        "wake_engine",
        "wake_mww_enabled",
        "wake_word",
        "wake_word_url",
        "wake_model_revision",
        "wake_sensitivity",
        "wake_environment",
        "wake_threshold",
        "wake_sliding_window",
    ),
    (
        "wake_oww_enabled",
        "oww_wake_word",
        "oww_wake_word_url",
        "oww_model_revision",
    ),
    (
        "capture_wake_audio",
        "capture_close_misses",
        "close_miss_threshold",
        "trainer_app_url",
        "wake_verifier_mode",
        "wake_verifier_window_ms",
        "wake_verifier_timeout_ms",
    ),
    (
        "wake_sound_enabled",
        "wake_sound",
        "wake_sound_url",
        "aec_enabled",
        "aec_strength_percent",
        "aec_delay_ms",
        "continued_chat",
        "barge_in_enabled",
        "volume_percent",
        "muted",
        "output_channel_mode",
        "audio_output_mode",
    ),
    (
        "led_brightness",
        "led_color",
        "led_listening_animation",
        "led_thinking_animation",
        "led_tool_call_animation",
        "led_replying_animation",
        "led_music_animation",
        "logging_level",
    ),
    (
        "screen_brightness",
        "screen_night_mode_enabled",
        "screen_night_brightness",
        "screen_night_start",
        "screen_night_end",
        "screen_local_time_seconds",
    ),
)
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


def _compact_json(message: dict[str, Any]) -> str:
    """Serialize a device message without avoidable wire bytes."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def _settings_messages(
    settings: dict[str, Any],
    *,
    board: Any = "",
    capabilities: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build settings frames for the receiving firmware family."""

    def _message(payload: dict[str, Any]) -> dict[str, Any]:
        return envelope("settings", payload, include_metadata=False)

    complete = _message(settings)
    # Echo firmware applies the wake detector pair as one coherent settings
    # snapshot. Tater uses this same atomic contract, and Echo's WebSocket
    # transport accepts the larger frame. Keep legacy fragmentation only for
    # the MWW/ESP family whose older receive windows are limited to 1,000 bytes.
    if wake_family_for(capabilities=capabilities, board=board) == "echo":
        return [complete]
    if len(_compact_json(complete).encode("utf-8")) <= _MAX_DEVICE_TEXT_FRAME_BYTES:
        return [complete]

    messages: list[dict[str, Any]] = []
    included: set[str] = set()
    for keys in _SETTINGS_WIRE_GROUPS:
        payload = {key: settings[key] for key in keys if key in settings}
        if payload:
            messages.append(_message(payload))
            included.update(payload)

    # Preserve forward compatibility if a newer integration adds a setting
    # before it is assigned to a logical wire group.
    remainder = {
        key: value for key, value in settings.items() if key not in included
    }
    if remainder:
        messages.append(_message(remainder))
    return messages


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
        self.pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.media_session: dict[str, Any] = {}
        self.intercom_session: dict[str, Any] = {}
        self.ota = OtaState()
        self.connection_generation = 0
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
    def firmware_target(self) -> str:
        """Return the release target reported by the firmware."""
        return text(self.record.get("firmware_target"))

    @property
    def firmware_catalog_target(self) -> str:
        """Return the most specific identifier used for release selection."""
        return self.firmware_target or self.board

    @property
    def firmware_version(self) -> str:
        """Return the installed firmware version."""
        return text(self.record.get("firmware_version"))

    @property
    def room(self) -> str:
        """Return the suggested Home Assistant area."""
        return text(self.record.get("room"))

    @property
    def ota_in_progress(self) -> bool:
        """Return whether an OTA attempt is awaiting verified completion."""
        return self.ota.in_progress

    @property
    def ota_progress(self) -> int | None:
        """Return OTA progress, reserving 100% for reboot verification."""
        return self.ota.progress

    @property
    def ota_message(self) -> str:
        """Return the latest OTA status for entities and the custom panel."""
        return self.ota.message

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return declared capabilities."""
        value = self.record.get("capabilities")
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items()}

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
                await websocket.send_str(_compact_json(message))
            return True
        except (ConnectionError, RuntimeError) as err:
            self.last_error = text(err) or type(err).__name__
            return False

    async def async_request(
        self,
        message_type_value: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 3.0,
    ) -> dict[str, Any]:
        """Send a command and wait for its firmware result message."""
        if not self.connected:
            raise RuntimeError(f"{self.name} is offline")
        message = envelope(message_type_value, payload or {})
        request_id = text(message.get("id"))
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self.pending_requests[request_id] = future
        if not await self.async_send_json(message):
            self.pending_requests.pop(request_id, None)
            raise RuntimeError(f"Unable to send {message_type_value} to {self.name}")
        try:
            async with asyncio.timeout(max(0.25, timeout)):
                return await future
        finally:
            self.pending_requests.pop(request_id, None)

    def resolve_request(self, payload: dict[str, Any]) -> bool:
        """Resolve a pending command from its reply_to token."""
        request_id = text(payload.get("reply_to"))
        future = self.pending_requests.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(dict(payload))
        return True

    def fail_pending_requests(self) -> None:
        """Fail request waiters when the firmware transport closes."""
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError(f"{self.name} disconnected"))
        self.pending_requests.clear()

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
            else firmware_payload(
                self.effective_settings(),
                board=self.board,
                capabilities=self.capabilities,
            )
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
        available = self.manager.firmware.info_for_board(
            self.firmware_catalog_target
        )
        installed = self.firmware_version
        latest = text(available.get("firmware_version"))
        return {
            "device_id": self.device_id,
            "name": self.name,
            "board": self.board,
            "firmware_target": self.firmware_target,
            "board_key": board_manifest_key(self.firmware_catalog_target),
            "room": self.room,
            "firmware_version": installed,
            "connected": self.connected,
            "remote": self.remote,
            "last_seen": self.last_seen,
            "last_error": self.last_error,
            "capabilities": self.capabilities,
            "wake_family": wake_family_for(
                capabilities=self.capabilities,
                board=self.board,
            ),
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
            "media_session": dict(self.media_session),
            "intercom": self.manager.intercom.device_snapshot(self),
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
                "mode": text(desired_settings.get("wake_verifier_mode")) or "off",
                "applied_mode": text(live.get("wake_verifier_mode")),
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
        self.wake_word_catalog = WakeWordCatalog(async_get_clientsession(hass))
        self.trainer = TrainerLinkManager(self)
        self.media = TaterMediaCoordinator(self)
        self.intercom = TaterIntercomCoordinator(self)
        self.bluetooth = TaterBluetoothProxyManager(self)
        self._save_lock = asyncio.Lock()
        self._pairing_code = ""
        self._pairing_expires = 0.0
        self._pairing_claimed_device = ""
        self._pairing_claimed_hardware = ""
        self._pairing_retry_device_token = ""
        self._pairing_retry_expires = 0.0
        self._platforms: dict[str, tuple[EntityFactory, AddEntitiesCallback]] = {}
        self._assets_root = Path(hass.config.path("tater_satellite", "assets"))
        self._shutting_down = False

    async def async_setup(self) -> None:
        """Load persistent state and prepare services."""
        loaded = await self.store.async_load()
        self.data = loaded if isinstance(loaded, dict) else {}
        raw_global_settings = (
            dict(self.data.get("global_settings"))
            if isinstance(self.data.get("global_settings"), dict)
            else {}
        )
        self.data.setdefault("global_settings", dict(DEFAULT_SETTINGS))
        self.data["global_settings"] = normalize_settings(
            self.data.get("global_settings")
        )
        migrated_wake_families = False
        stored_families = self.data.get("wake_family_settings")
        if not isinstance(stored_families, dict):
            stored_families = {}
            migrated_wake_families = True
        global_settings = self.data["global_settings"]
        explicit_echo_mode = any(
            key in raw_global_settings
            for key in ("wake_detector_mode", "wake_mww_enabled", "wake_oww_enabled")
        )
        echo_mode = str(global_settings.get("wake_detector_mode") or "dual")
        if (
            not explicit_echo_mode
            and global_settings.get("wake_word") == "custom_url"
        ):
            # Preserve an existing custom MWW on upgrade. The user can switch
            # Echo devices to Dual after selecting its matching wake bundle.
            echo_mode = "mww"
        family_defaults = {
            "mww": {**global_settings, "wake_detector_mode": "mww"},
            "echo": {**global_settings, "wake_detector_mode": echo_mode},
        }
        normalized_families: dict[str, dict[str, Any]] = {}
        for family in sorted(WAKE_FAMILIES):
            raw_family = stored_families.get(family)
            if not isinstance(raw_family, dict):
                raw_family = family_defaults[family]
                migrated_wake_families = True
            normalized_families[family] = normalize_wake_family_settings(
                family,
                raw_family,
                base=global_settings,
            )
        self.data["wake_family_settings"] = normalized_families
        self.data.setdefault("devices", {})
        self.data.setdefault("assets", {})
        self.data.setdefault("bluetooth_devices", {})
        self.media.setup()
        self.trainer.setup()
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
        elif migrated_wake_families:
            await self.async_save()
        await self.hass.async_add_executor_job(
            self._assets_root.mkdir, 0o755, True, True
        )
        await self.firmware.async_setup()
        self.entry.async_create_background_task(
            self.hass,
            self.wake_word_catalog.async_refresh(),
            "tater_satellite_wake_word_catalog",
        )
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
        await self.bluetooth.async_shutdown()
        await self.intercom.async_shutdown()
        await self.media.async_shutdown()
        for runtime in tuple(self.runtimes.values()):
            runtime.finish_audio()
            runtime.fail_playback_waiters()
            runtime.fail_pending_requests()
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
        self._pairing_claimed_hardware = ""
        self._pairing_retry_device_token = ""
        self._pairing_retry_expires = 0.0
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
                if self._pairing_claimed_device == device_id:
                    self._pairing_retry_device_token = ""
                    self._pairing_retry_expires = 0.0
                return True, ""
            retry_token = pairing_retry_token(
                supplied_code=supplied,
                pairing_code=self._pairing_code,
                claimed_device_id=self._pairing_claimed_device,
                claimed_hardware_id=self._pairing_claimed_hardware,
                device_token=self._pairing_retry_device_token,
                retry_expires_at=self._pairing_retry_expires,
                device_id=device_id,
                hardware_id=message_payload(hello).get("hardware_id"),
                now=time.time(),
            )
            if retry_token:
                return True, retry_token
            return False, ""

        if not self._pairing_matches(supplied):
            return False, ""

        new_token = secrets.token_urlsafe(32)
        payload = message_payload(hello)
        record = {
            "token_hash": _token_hash(new_token),
            "name": text(payload.get("device_name")) or device_id,
            "board": text(payload.get("board")),
            "firmware_target": text(payload.get("firmware_target")),
            "hardware_id": normalize_hardware_id(payload.get("hardware_id")),
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
        self._pairing_claimed_hardware = record["hardware_id"]
        self._pairing_retry_device_token = new_token
        self._pairing_retry_expires = time.time() + PAIRING_RETRY_GRACE_SECONDS
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
        self.media.notify()

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
        family = wake_family_for(
            capabilities=runtime.capabilities if runtime is not None else {},
            board=runtime.board if runtime is not None else "",
        )
        families = self.data.get("wake_family_settings")
        family_settings = (
            families.get(family)
            if isinstance(families, dict) and isinstance(families.get(family), dict)
            else {}
        )
        return merged_settings(
            self.data.get("global_settings"),
            overrides,
            family_settings,
        )

    def _adopt_reported_device_volume(
        self, runtime: SatelliteRuntime, status: dict[str, Any]
    ) -> bool:
        """Keep physical satellite volume changes in Home Assistant."""
        if runtime.settings_sync_state != "confirmed":
            return False
        live = status.get("live_settings")
        if not isinstance(live, dict):
            live = status.get("settings")
        if not isinstance(live, dict):
            live = {}
        if "volume_percent" not in live:
            return False
        volume = max(0, min(100, _as_int(live.get("volume_percent"))))
        if volume == int(runtime.effective_settings().get("volume_percent") or 0):
            return False
        overrides = (
            dict(runtime.record.get("overrides"))
            if isinstance(runtime.record.get("overrides"), dict)
            else {}
        )
        overrides["volume_percent"] = volume
        runtime.record["overrides"] = overrides
        self.store.async_delay_save(lambda: self.data, 1.0)
        return True

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
            assets = self.data.get("assets")
            model_row = (
                assets.get(model_asset) if isinstance(assets, dict) else None
            )
            settings["wake_model_revision"] = (
                text(model_row.get("sha256")) if isinstance(model_row, dict) else ""
            )
        if settings.get("wake_sound") == "custom" and sound_asset:
            settings["wake_sound_url"] = self._asset_url(
                sound_asset,
                "filename",
                base_url=base_url,
            )
        board = runtime.board if runtime is not None else ""
        local_time_seconds: int | None = None
        if board_supports_screen_settings(board):
            local_now = dt_util.now()
            local_time_seconds = (
                (local_now.hour * 60 * 60)
                + (local_now.minute * 60)
                + local_now.second
            )
        payload = firmware_payload(
            settings,
            board=board,
            capabilities=runtime.capabilities if runtime is not None else {},
            local_time_seconds=local_time_seconds,
        )
        payload["output_channel_mode"] = self.media.output_channel_mode(device_id)
        return payload

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
        settings = self.firmware_settings(runtime.device_id)
        messages = _settings_messages(
            settings,
            board=runtime.board,
            capabilities=runtime.capabilities,
        )
        sent = True
        for message in messages:
            if not await runtime.async_send_json(message):
                sent = False
                break
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

    def wake_family_settings(self, family: str) -> dict[str, Any]:
        """Return one normalized shared wake-family profile."""
        token = text(family).lower()
        if token not in WAKE_FAMILIES:
            raise ValueError(f"Unsupported wake family: {family}")
        families = self.data.get("wake_family_settings")
        values = (
            families.get(token)
            if isinstance(families, dict) and isinstance(families.get(token), dict)
            else {}
        )
        return normalize_wake_family_settings(
            token,
            values,
            base=normalize_settings(self.data.get("global_settings")),
        )

    async def _async_wake_bundle(self, bundle_url: str) -> dict[str, str]:
        """Validate a trainer bundle and resolve its matching MWW manifest."""
        url = text(bundle_url)
        if not url.startswith(("http://", "https://")):
            raise ValueError(
                "The openWakeWord bundle URL must start with http:// or https://."
            )
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(8):
                async with session.get(url) as response:
                    response.raise_for_status()
                    raw = await response.content.read(256 * 1024 + 1)
        except Exception as err:  # noqa: BLE001
            raise ValueError(
                f"Could not read the Tater wake bundle: {type(err).__name__}"
            ) from err
        if len(raw) > 256 * 1024:
            raise ValueError("The Tater wake bundle is larger than 256 KB.")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ValueError("The Tater wake bundle is not valid JSON.") from err
        if not isinstance(payload, dict):
            raise ValueError("The Tater wake bundle must contain a JSON object.")
        if (
            payload.get("schema_version") != 1
            or text(payload.get("type")) != "tater_wake_word_bundle"
        ):
            raise ValueError("The URL is not a Tater dual-model wake bundle.")
        micro = payload.get("micro_wake_word")
        oww = payload.get("open_wake_word")
        if not isinstance(micro, dict) or not isinstance(oww, dict):
            raise ValueError(
                "The wake bundle must contain matching MWW and OWW models."
            )
        manifest_ref = text(micro.get("manifest"))
        model_ref = text(micro.get("model"))
        if not manifest_ref.lower().endswith(
            ".json"
        ) or not model_ref.lower().endswith(".tflite"):
            raise ValueError(
                "The wake bundle does not contain a valid microWakeWord package."
            )
        artifacts = oww.get("artifacts")
        model_artifacts = [
            row
            for row in artifacts.values()
            if isinstance(row, dict)
            and text(row.get("file")).lower().endswith((".onnx", ".tflite"))
        ] if isinstance(artifacts, dict) else []
        if not model_artifacts:
            raise ValueError("The wake bundle does not contain an openWakeWord model.")
        return {
            "wake_word": text(
                payload.get("wake_word") or payload.get("label") or payload.get("key")
            ),
            "manifest_url": urljoin(url, manifest_ref),
            "wake_model_revision": text(micro.get("manifest_sha256"))
            or hashlib.sha256(raw).hexdigest(),
            "oww_model_revision": hashlib.sha256(raw).hexdigest(),
        }

    async def async_set_wake_family_settings(
        self,
        family: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Save one family profile and update only matching satellites."""
        token = text(family).lower()
        if token not in WAKE_FAMILIES:
            raise ValueError(f"Unsupported wake family: {family}")
        incoming = resolve_wake_word_source_values(values)
        incoming = {
            key: value
            for key, value in incoming.items()
            if key in WAKE_FAMILY_SETTING_KEYS
        }
        current = self.wake_family_settings(token)
        bundle_profile: dict[str, str] | None = None
        if token == "mww":
            incoming["wake_detector_mode"] = "mww"
        mode = text(
            incoming.get("wake_detector_mode")
            or current.get("wake_detector_mode")
        )
        if token == "echo" and mode not in {"mww", "oww", "dual"}:
            mode = "dual"
        if token == "echo" and mode in {"oww", "dual"}:
            oww_source = text(
                incoming.get("oww_wake_word", current.get("oww_wake_word"))
            ).lower()
            oww_url = text(
                incoming.get("oww_wake_word_url", current.get("oww_wake_word_url"))
            )
            if oww_source == "custom_url":
                bundle_profile = await self._async_wake_bundle(oww_url)
                incoming["oww_wake_word_url"] = oww_url
                incoming["oww_model_revision"] = bundle_profile[
                    "oww_model_revision"
                ]
                if mode == "dual":
                    incoming.update(
                        {
                            "wake_word": "custom_url",
                            "wake_word_url": bundle_profile["manifest_url"],
                            "wake_model_asset_id": "",
                            "wake_model_revision": bundle_profile[
                                "wake_model_revision"
                            ],
                        }
                    )
            elif mode == "dual":
                # Built-in Dual always pairs the two Hey Tater models. This
                # prevents accidentally requiring two different phrases.
                incoming.update(
                    {
                        "wake_word": "hey_tater",
                        "wake_word_url": "",
                        "wake_model_asset_id": "",
                        "wake_model_revision": "",
                        "oww_wake_word": "hey_tater",
                        "oww_wake_word_url": "",
                        "oww_model_revision": "",
                    }
                )
        incoming["wake_detector_mode"] = "mww" if token == "mww" else mode
        next_settings = normalize_wake_family_settings(
            token,
            {**current, **incoming},
            base=normalize_settings(self.data.get("global_settings")),
        )
        families = self.data.setdefault("wake_family_settings", {})
        families[token] = next_settings

        verifier_phrase = ""
        verifier_phrase_url = ""
        custom_verifier_model = False
        if (
            next_settings.get("wake_oww_enabled")
            and not next_settings.get("wake_mww_enabled")
        ):
            custom_verifier_model = (
                next_settings.get("oww_wake_word") == "custom_url"
            )
            if custom_verifier_model:
                verifier_phrase_url = text(
                    next_settings.get("oww_wake_word_url")
                )
                verifier_phrase = normalize_phrase(
                    (bundle_profile or {}).get("wake_word")
                )
        elif next_settings.get("wake_word") == "custom_url" and not text(
            next_settings.get("wake_model_asset_id")
        ):
            custom_verifier_model = True
            verifier_phrase_url = text(next_settings.get("wake_word_url"))
            verifier_phrase = normalize_phrase(
                (bundle_profile or {}).get("wake_word")
            )
            if not verifier_phrase:
                verifier_phrase = await self._async_wake_phrase_from_url(
                    verifier_phrase_url
                )

        changed_keys = {
            key for key, value in next_settings.items() if value != current.get(key)
        }
        for runtime in self.runtimes.values():
            if wake_family_for(
                capabilities=runtime.capabilities,
                board=runtime.board,
            ) != token:
                continue
            if changed_keys:
                overrides = runtime.record.get("overrides")
                if isinstance(overrides, dict):
                    runtime.record["overrides"] = {
                        key: value
                        for key, value in overrides.items()
                        if key not in WAKE_FAMILY_SETTING_KEYS
                    }
            if verifier_phrase and verifier_phrase_url:
                runtime.record["wake_verifier_phrase"] = verifier_phrase
                runtime.record["wake_verifier_phrase_url"] = verifier_phrase_url
            elif not custom_verifier_model or text(
                runtime.record.get("wake_verifier_phrase_url")
            ) != verifier_phrase_url:
                runtime.record.pop("wake_verifier_phrase", None)
                runtime.record.pop("wake_verifier_phrase_url", None)

        await self.async_save()
        connected = [
            runtime
            for runtime in self.runtimes.values()
            if runtime.connected
            and wake_family_for(
                capabilities=runtime.capabilities,
                board=runtime.board,
            ) == token
        ]
        results = await asyncio.gather(
            *(self.async_push_settings(runtime) for runtime in connected),
            return_exceptions=True,
        )
        failed = [
            runtime.name
            for runtime, result in zip(connected, results, strict=True)
            if result is not True
        ]
        for runtime in self.runtimes.values():
            runtime.notify()
        if failed:
            raise RuntimeError(
                "Wake settings were saved, but they could not be sent to: "
                + ", ".join(failed)
            )
        return dict(next_settings)

    async def async_set_global_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        """Save global defaults and update every connected satellite."""
        values = resolve_wake_word_source_values(values)
        current = normalize_settings(self.data.get("global_settings"))
        patch = normalize_settings(values, base=current, partial=True)
        if "wake_word_url" in patch and text(patch.get("wake_word_url")) != text(
            current.get("wake_word_url")
        ):
            patch["wake_model_asset_id"] = ""
            patch["wake_model_revision"] = ""
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
        legacy_family_patch = {
            key: value
            for key, value in values.items()
            if key in WAKE_FAMILY_SETTING_KEYS
        }
        if legacy_family_patch:
            families = self.data.setdefault("wake_family_settings", {})
            for family in sorted(WAKE_FAMILIES):
                family_current = self.wake_family_settings(family)
                family_patch = dict(legacy_family_patch)
                if family == "mww":
                    family_patch["wake_detector_mode"] = "mww"
                elif (
                    family_current.get("wake_detector_mode") == "dual"
                    and family_patch.get("wake_word") == "custom_url"
                    and "oww_wake_word_url" not in family_patch
                ):
                    # A legacy client only knows how to publish one MWW model;
                    # keep Echo on that detector instead of pairing mismatched words.
                    family_patch["wake_detector_mode"] = "mww"
                families[family] = normalize_wake_family_settings(
                    family,
                    {**family_current, **family_patch},
                    base=next_settings,
                )
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
                "wake_model_revision": secrets.token_hex(16),
                "wake_model_asset_id": "",
                "wake_verifier_phrase": wake_word,
                "wake_verifier_phrase_url": wake_word_url,
            }
        )
        families = self.data.setdefault("wake_family_settings", {})
        family_targets = ["mww"]
        echo_current = self.wake_family_settings("echo")
        if echo_current.get("wake_detector_mode") == "mww":
            family_targets.append("echo")
        for family in family_targets:
            current_family = self.wake_family_settings(family)
            families[family] = normalize_wake_family_settings(
                family,
                {
                    **current_family,
                    "wake_word": "custom_url",
                    "wake_word_url": wake_word_url,
                    "wake_model_revision": secrets.token_hex(16),
                    "wake_model_asset_id": "",
                },
                base=self.data["global_settings"],
            )
        wake_override_keys = {
            "wake_word",
            "wake_word_url",
            "wake_model_revision",
            "wake_model_asset_id",
            "wake_verifier_phrase",
            "wake_verifier_phrase_url",
        }
        for runtime in self.runtimes.values():
            runtime_family = wake_family_for(
                capabilities=runtime.capabilities,
                board=runtime.board,
            )
            if runtime_family not in family_targets:
                continue
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
            for key, value in resolve_wake_word_source_values(values).items()
            if key not in _GLOBAL_WAKE_VERIFIER_KEYS
        }
        wake_family = wake_family_for(
            capabilities=runtime.capabilities,
            board=runtime.board,
        )
        wake_change_keys = WAKE_FAMILY_SETTING_KEYS.intersection(device_values)
        wake_changed = bool(wake_change_keys)
        device_bundle_profile: dict[str, str] | None = None
        if wake_changed and wake_family == "mww":
            device_values["wake_detector_mode"] = "mww"
            for key in (
                "wake_oww_enabled",
                "oww_wake_word",
                "oww_wake_word_url",
                "oww_model_revision",
            ):
                device_values.pop(key, None)
        elif wake_changed:
            candidate = {**base, **device_values}
            mode = text(candidate.get("wake_detector_mode")).lower()
            if mode not in {"mww", "oww", "dual"}:
                mode = "dual"
            device_values["wake_detector_mode"] = mode
            pairing_keys = {
                "wake_detector_mode",
                "wake_word",
                "wake_word_url",
                "wake_model_asset_id",
                "oww_wake_word",
                "oww_wake_word_url",
            }
            if mode in {"oww", "dual"} and pairing_keys.intersection(
                wake_change_keys
            ):
                oww_source = text(candidate.get("oww_wake_word")).lower()
                oww_url = text(candidate.get("oww_wake_word_url"))
                if oww_source == "custom_url":
                    device_bundle_profile = await self._async_wake_bundle(oww_url)
                    device_values["oww_wake_word_url"] = oww_url
                    device_values["oww_model_revision"] = device_bundle_profile[
                        "oww_model_revision"
                    ]
                    if mode == "dual":
                        device_values.update(
                            {
                                "wake_word": "custom_url",
                                "wake_word_url": device_bundle_profile[
                                    "manifest_url"
                                ],
                                "wake_model_asset_id": "",
                                "wake_model_revision": device_bundle_profile[
                                    "wake_model_revision"
                                ],
                            }
                        )
                elif mode == "dual":
                    device_values.update(
                        {
                            "wake_word": "hey_tater",
                            "wake_word_url": "",
                            "wake_model_asset_id": "",
                            "wake_model_revision": "",
                            "oww_wake_word": "hey_tater",
                            "oww_wake_word_url": "",
                            "oww_model_revision": "",
                        }
                    )
        if "wake_word_url" in device_values and text(
            device_values.get("wake_word_url")
        ) != text(base.get("wake_word_url")):
            device_values["wake_model_asset_id"] = ""
            device_values["wake_model_revision"] = ""
        if "wake_sound_url" in device_values and text(
            device_values.get("wake_sound_url")
        ) != text(base.get("wake_sound_url")):
            device_values["wake_sound_asset_id"] = ""
        patch = normalize_settings(device_values, base=base, partial=True)
        existing.update(patch)
        runtime.record["overrides"] = existing
        if {
            "wake_detector_mode",
            "wake_word",
            "wake_word_url",
            "wake_model_asset_id",
            "oww_wake_word",
            "oww_wake_word_url",
        }.intersection(patch):
            effective = runtime.effective_settings()
            oww_only = bool(effective.get("wake_oww_enabled")) and not bool(
                effective.get("wake_mww_enabled")
            )
            wake_word = effective.get(
                "oww_wake_word" if oww_only else "wake_word"
            )
            wake_url = text(
                effective.get(
                    "oww_wake_word_url" if oww_only else "wake_word_url"
                )
            )
            uses_uploaded_mww = not oww_only and bool(
                text(effective.get("wake_model_asset_id"))
            )
            if wake_word == "custom_url" and not uses_uploaded_mww:
                phrase = normalize_phrase(
                    (device_bundle_profile or {}).get("wake_word")
                )
                if not phrase and not oww_only:
                    phrase = await self._async_wake_phrase_from_url(wake_url)
                if not phrase and text(
                    runtime.record.get("wake_verifier_phrase_url")
                ) == wake_url:
                    phrase = normalize_phrase(
                        runtime.record.get("wake_verifier_phrase")
                    )
                runtime.record["wake_verifier_phrase"] = phrase
                runtime.record["wake_verifier_phrase_url"] = wake_url
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
        target = runtime.firmware_catalog_target
        signed = await self.firmware.async_prepare(target, "ota")
        expected_version = text(
            self.firmware.info_for_board(target).get("firmware_version")
        )
        if not expected_version:
            raise RuntimeError("The firmware catalog did not report a target version")
        base_url = runtime.server_base_url or self.public_base_url()
        url = (
            f"{base_url}/api/tater/satellite/v1/firmware/file/"
            f"{signed.filename}?token={signed.token}"
        )
        attempt = runtime.ota.begin(
            expected_version,
            runtime.connection_generation,
        )
        runtime.notify()
        if not await runtime.async_send(
            "ota.url",
            {
                "url": url,
                "sha256": signed.sha256,
                "size_bytes": signed.size_bytes,
            },
        ):
            runtime.ota.fail("Unable to send OTA command")
            runtime.last_error = runtime.ota.message
            runtime.notify()
            raise RuntimeError("Unable to send OTA command")
        self.entry.async_create_background_task(
            self.hass,
            self._async_verify_ota_timeout(runtime, attempt),
            f"tater_satellite_ota_verify_{runtime.device_id}_{attempt}",
        )
        return {"ok": True, "url": url, "device": runtime.public_snapshot()}

    async def _async_verify_ota_timeout(
        self,
        runtime: SatelliteRuntime,
        attempt: int,
    ) -> None:
        """Turn a missing post-reboot hello into a visible OTA failure."""
        await asyncio.sleep(OTA_VERIFY_TIMEOUT_SECONDS)
        if runtime.ota.expire(attempt):
            runtime.last_error = runtime.ota.message
            runtime.add_log("error", runtime.ota.message, kind="ota.status")
            runtime.notify()

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
        oww_only = bool(settings.get("wake_oww_enabled")) and not bool(
            settings.get("wake_mww_enabled")
        )
        wake_word = text(
            settings.get("oww_wake_word") if oww_only else settings.get("wake_word")
        )
        if wake_word and wake_word != "custom_url":
            return normalize_phrase(wake_word)

        asset_id = "" if oww_only else text(settings.get("wake_model_asset_id"))
        assets = self.data.get("assets")
        asset = assets.get(asset_id) if asset_id and isinstance(assets, dict) else None
        if isinstance(asset, dict):
            phrase = normalize_phrase(asset.get("label"))
            if phrase:
                return phrase

        effective_url = text(
            settings.get("oww_wake_word_url")
            if oww_only
            else settings.get("wake_word_url")
        )
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
            "wake_family_settings": {
                family: self.wake_family_settings(family)
                for family in sorted(WAKE_FAMILIES)
            },
            "settings_schema": _json_copy(SETTINGS_SCHEMA, []),
            "assets": assets,
            "stereo_pairs": self.media.list_pairs(),
            "intercom": self.intercom.snapshot(),
            "bluetooth": self.bluetooth.snapshot(),
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
            ("firmware_target", "firmware_target"),
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
        if kind.endswith(".result") and runtime.resolve_request(payload):
            return
        if self.bluetooth.handle_message(runtime, kind, payload):
            runtime.notify()
            return
        if self.media.handle_message(runtime, kind, payload):
            runtime.notify()
            return
        if kind == "status":
            runtime.last_status = payload
            runtime.note_settings_status()
            self._adopt_reported_device_volume(runtime, payload)
            runtime.notify()
            return
        if kind == "settings.changed":
            reported = (
                payload.get("settings")
                if isinstance(payload.get("settings"), dict)
                else payload
            )
            error = text(payload.get("error"))
            ok = bool(payload.get("ok", not error))
            if error or not ok:
                runtime.settings_sync_state = "failed"
                runtime.settings_sync_message = (
                    error or "Satellite rejected the live settings."
                )
                runtime.add_log(
                    "error",
                    runtime.settings_sync_message,
                    kind="settings.changed",
                )
            elif "wake_word" in reported:
                # Full settings acknowledgements include wake_word. Small
                # physical-control deltas must not overwrite sync diagnostics.
                runtime.settings_sync_state = "confirmed"
                runtime.settings_sync_message = (
                    "Satellite confirmed the live settings."
                )
                runtime.settings_last_confirmed = time.time()
            self._adopt_reported_device_volume(runtime, payload)
            runtime.notify()
            return
        if kind in {"log", "ota.status"}:
            level = text(payload.get("level")) or (
                "error" if text(payload.get("status")) == "error" else "info"
            )
            message_text = text(payload.get("message"))
            if kind == "ota.status":
                status = text(payload.get("status")).lower()
                runtime.ota.apply_status(payload)
                if status in {"error", "failed"}:
                    runtime.last_error = runtime.ota.message
            runtime.add_log(level, message_text, kind=kind)
            runtime.notify()
            return
        if kind in {"voice.start", "audio.start"}:
            if is_intercom_request(payload):
                ok, error = self.intercom.start_capture(runtime, payload)
                await runtime.async_send_json(
                    envelope(
                        "voice.start.ack",
                        {"ok": ok, "error": error},
                        message_id=text(message.get("id")),
                    )
                )
                return
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
            capture = self.intercom.finish_capture(
                runtime,
                abort=bool(payload.get("abort")),
            )
            if capture is not None:
                await runtime.async_send_json(
                    envelope(
                        "voice.stop.ack",
                        {"ok": True},
                        message_id=text(message.get("id")),
                    )
                )
                if not capture.get("aborted"):
                    self.entry.async_create_background_task(
                        self.hass,
                        self.intercom.async_broadcast(runtime, capture),
                        f"tater_intercom_broadcast_{runtime.device_id}",
                    )
                return
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
            # The satellite owns the countdown and alarm. Home Assistant keeps
            # only the transient mirror required by its built-in timer intents.
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

            # Finish the protocol handshake before replacing the previous
            # socket or updating registry and OTA state. The acknowledgement
            # may contain a newly paired device token that firmware must save
            # before its recovery watchdog can safely reconnect.
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
                    "media_player": True,
                    "sendspin_source": True,
                    "stereo_pairs": True,
                    "intercom": True,
                },
            }
            if new_token:
                ack_payload["device_token"] = new_token
            await websocket.send_str(
                _compact_json(
                    envelope(
                        "hello.ack",
                        ack_payload,
                        message_id=text(hello.get("id")),
                    )
                )
            )

            runtime = self.runtimes[device_id]
            old_socket = runtime.websocket
            if old_socket is not None and not old_socket.closed:
                with contextlib.suppress(Exception):
                    await old_socket.close(code=1012, message=b"Replaced by reconnect")
            runtime.websocket = websocket
            runtime.connected = True
            runtime.connection_generation += 1
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
            self.bluetooth.async_connect_runtime(runtime)
            ota_was_in_progress = runtime.ota.in_progress
            runtime.ota.note_reconnect(
                runtime.connection_generation,
                payload.get("firmware_version"),
            )
            if (
                ota_was_in_progress
                and not runtime.ota.in_progress
                and runtime.ota.progress == 100
            ):
                runtime.add_log(
                    "info",
                    runtime.ota.message,
                    kind="ota.status",
                )
            elif ota_was_in_progress and not runtime.ota.in_progress:
                runtime.last_error = runtime.ota.message
                runtime.add_log(
                    "error",
                    runtime.ota.message,
                    kind="ota.status",
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
                    if self.intercom.add_audio(runtime, data):
                        continue
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
                self.intercom.handle_disconnect(runtime)
                self.bluetooth.disconnect_runtime(runtime)
                if runtime.assist_entity is not None:
                    with contextlib.suppress(Exception):
                        await runtime.assist_entity.async_device_voice_stop(
                            {"abort": True}
                        )
                runtime.websocket = None
                runtime.connected = False
                runtime.ota.note_disconnect()
                runtime.finish_audio()
                runtime.fail_playback_waiters()
                runtime.fail_pending_requests()
                await self.media.async_handle_disconnect(runtime)
                runtime.notify()
        return websocket
