"""Small, Home Assistant-only Tater voice runtime.

The desktop Tater runtime intentionally is not imported here. This module owns
the complete satellite turn when Tater mode is selected: STT, a Home Assistant
specific Astraeus/Thanatos/Hermes loop, device control, TTS, and a bounded
execution ledger.
"""

from __future__ import annotations

import asyncio
from collections import deque
import importlib
import io
import json
import logging
import math
import re
import secrets
import time
import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from homeassistant.core import Context, HomeAssistant

    from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

ASSISTANT_MODE_HOME_ASSISTANT = "home_assistant"
ASSISTANT_MODE_TATER = "tater"
ENTITY_SCOPE_EXPOSED = "exposed"
ENTITY_SCOPE_ALL = "all"

HYDRA_ROLE_IDS = ("astraeus", "thanatos", "hermes")
HYDRA_ROLE_API_KEY_FIELDS = tuple(
    f"hydra_llm_{role}_api_key" for role in HYDRA_ROLE_IDS
)
API_KEY_FIELDS = (
    "llm_api_key",
    "stt_api_key",
    "tts_api_key",
    *HYDRA_ROLE_API_KEY_FIELDS,
)
MAX_PROVIDER_AUDIO_BYTES = 32 * 1024 * 1024
MAX_STORED_SPEECH_CLIPS = 20
VAD_PRE_ROLL_SECONDS = 0.4
VAD_SPEECH_START_SECONDS = 0.06
VAD_NO_SPEECH_SECONDS = 3.5
VAD_MAX_UTTERANCE_SECONDS = 8.5
VAD_END_SILENCE_SECONDS = {
    "aggressive": 0.5,
    "default": 0.78,
    "relaxed": 1.25,
}

DEFAULT_TATER_SETTINGS: dict[str, Any] = {
    "assistant_mode": ASSISTANT_MODE_HOME_ASSISTANT,
    "llm_base_url": "https://api.openai.com/v1",
    "llm_api_key": "",
    "llm_model": "",
    "llm_temperature": 0.2,
    "stt_provider": "openai",
    "stt_base_url": "https://api.openai.com/v1",
    "stt_api_key": "",
    "stt_model": "gpt-4o-transcribe",
    "stt_language": "",
    "stt_wyoming_host": "",
    "stt_wyoming_port": 10300,
    "stt_wyoming_model": "",
    "tts_provider": "openai",
    "tts_base_url": "https://api.openai.com/v1",
    "tts_api_key": "",
    "tts_model": "gpt-4o-tts",
    "tts_voice": "alloy",
    "tts_wyoming_host": "",
    "tts_wyoming_port": 10200,
    "tts_wyoming_voice": "",
    "entity_scope": ENTITY_SCOPE_EXPOSED,
    "assistant_name": "Tater",
    "personality": (
        "Be warm, concise, and useful. Speak naturally because replies are read aloud."
    ),
    "max_display": 8,
    "max_store": 20,
    "max_llm": 8,
    "hydra_max_ledger_items": 1500,
    "hydra_astraeus_plan_review_enabled": True,
    "hydra_auto_continue_incomplete_final_enabled": False,
    "hydra_beast_mode_enabled": False,
    **{
        f"hydra_llm_{role}_provider": "base"
        for role in HYDRA_ROLE_IDS
    },
    **{
        f"hydra_llm_{role}_host": ""
        for role in HYDRA_ROLE_IDS
    },
    **{
        f"hydra_llm_{role}_model": ""
        for role in HYDRA_ROLE_IDS
    },
    **{
        f"hydra_llm_{role}_api_key": ""
        for role in HYDRA_ROLE_IDS
    },
}

_STRING_LIMITS = {
    "llm_base_url": 500,
    "llm_model": 160,
    "stt_base_url": 500,
    "stt_model": 160,
    "stt_language": 32,
    "stt_wyoming_host": 255,
    "stt_wyoming_model": 160,
    "tts_base_url": 500,
    "tts_model": 160,
    "tts_voice": 160,
    "tts_wyoming_host": 255,
    "tts_wyoming_voice": 160,
    "assistant_name": 80,
    "personality": 4000,
    **{
        f"hydra_llm_{role}_host": 500
        for role in HYDRA_ROLE_IDS
    },
    **{
        f"hydra_llm_{role}_model": 160
        for role in HYDRA_ROLE_IDS
    },
}

_CONTROLLABLE_DOMAINS = {
    "alarm_control_panel",
    "button",
    "climate",
    "cover",
    "fan",
    "humidifier",
    "input_boolean",
    "light",
    "lock",
    "media_player",
    "remote",
    "scene",
    "script",
    "siren",
    "switch",
    "vacuum",
    "valve",
    "water_heater",
}
_READABLE_DOMAINS = _CONTROLLABLE_DOMAINS | {
    "binary_sensor",
    "sensor",
    "person",
    "device_tracker",
}

_COMMANDS: dict[str, tuple[str | None, str, dict[str, str]]] = {
    "turn_on": (None, "turn_on", {}),
    "turn_off": (None, "turn_off", {}),
    "toggle": (None, "toggle", {}),
    "open_cover": ("cover", "open_cover", {}),
    "close_cover": ("cover", "close_cover", {}),
    "stop_cover": ("cover", "stop_cover", {}),
    "set_cover_position": ("cover", "set_cover_position", {"position": "position"}),
    "lock": ("lock", "lock", {}),
    "unlock": ("lock", "unlock", {}),
    "set_temperature": (
        "climate",
        "set_temperature",
        {"temperature": "temperature", "hvac_mode": "hvac_mode"},
    ),
    "set_hvac_mode": ("climate", "set_hvac_mode", {"hvac_mode": "hvac_mode"}),
    "set_fan_percentage": ("fan", "set_percentage", {"percentage": "percentage"}),
    "set_brightness": ("light", "turn_on", {"brightness_pct": "brightness_pct"}),
    "set_color": (
        "light",
        "turn_on",
        {"color_name": "color_name", "rgb_color": "rgb_color"},
    ),
    "set_volume": (
        "media_player",
        "volume_set",
        {"volume_level": "volume_level"},
    ),
    "media_play": ("media_player", "media_play", {}),
    "media_pause": ("media_player", "media_pause", {}),
    "media_stop": ("media_player", "media_stop", {}),
    "media_next": ("media_player", "media_next_track", {}),
    "media_previous": ("media_player", "media_previous_track", {}),
    "start_vacuum": ("vacuum", "start", {}),
    "return_to_base": ("vacuum", "return_to_base", {}),
    "activate": (None, "turn_on", {}),
    "press": ("button", "press", {}),
}

_CONTROL_ACTION_PHRASES = {
    "turn_on": "Turned on",
    "turn_off": "Turned off",
    "toggle": "Toggled",
    "open_cover": "Opened",
    "close_cover": "Closed",
    "stop_cover": "Stopped",
    "lock": "Locked",
    "unlock": "Unlocked",
    "media_play": "Started playback on",
    "media_pause": "Paused",
    "media_stop": "Stopped playback on",
    "media_next": "Skipped to the next item on",
    "media_previous": "Went back on",
    "start_vacuum": "Started",
    "return_to_base": "Sent back to its base",
    "activate": "Activated",
    "press": "Pressed",
}

_DOMAIN_PLURALS = {
    "binary_sensor": "binary sensors",
    "climate": "climate devices",
    "cover": "covers",
    "device_tracker": "device trackers",
    "fan": "fans",
    "humidifier": "humidifiers",
    "input_boolean": "input booleans",
    "light": "lights",
    "lock": "locks",
    "media_player": "media players",
    "person": "people",
    "remote": "remotes",
    "scene": "scenes",
    "script": "scripts",
    "sensor": "sensors",
    "siren": "sirens",
    "switch": "switches",
    "vacuum": "vacuums",
    "valve": "valves",
    "water_heater": "water heaters",
}

_GENERIC_COMMAND_DOMAINS: dict[str, set[str]] = {
    "turn_on": {
        "fan",
        "humidifier",
        "input_boolean",
        "light",
        "media_player",
        "remote",
        "siren",
        "switch",
        "water_heater",
    },
    "turn_off": {
        "fan",
        "humidifier",
        "input_boolean",
        "light",
        "media_player",
        "remote",
        "siren",
        "switch",
        "water_heater",
    },
    "toggle": {"fan", "input_boolean", "light", "switch"},
    "activate": {"button", "scene", "script"},
}

_DEVICE_CATEGORY_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "light": ("light", "lights", "lamp", "lamps", "bulb", "bulbs", "dimmer", "dimmers"),
    "switch": ("switch", "switches", "relay", "relays"),
    "plug": ("plug", "plugs", "outlet", "outlets"),
    "fan": ("fan", "fans"),
    "garage_door": ("garage", "garage door", "garage doors", "garage opener"),
    "cover": ("cover", "covers", "shade", "shades", "blind", "blinds", "curtain", "curtains"),
    "lock": ("lock", "locks"),
    "camera": ("camera", "cameras", "doorbell", "doorbells"),
    "climate": ("climate", "thermostat", "thermostats", "hvac"),
    "media_player": ("media player", "media players", "speaker", "speakers", "television", "tv"),
    "remote": ("remote", "remotes"),
    "scene": ("scene", "scenes"),
    "script": ("script", "scripts"),
    "vacuum": ("vacuum", "vacuums", "robot vacuum", "robot vacuums"),
    "humidifier": ("humidifier", "humidifiers"),
    "siren": ("siren", "sirens", "alarm", "alarms"),
    "valve": ("valve", "valves"),
    "water_heater": ("water heater", "water heaters"),
    "button": ("button", "buttons"),
}

_DEVICE_CATEGORY_DOMAINS: dict[str, set[str]] = {
    "light": {"light"},
    "switch": {"switch"},
    "plug": {"switch"},
    "fan": {"fan"},
    "garage_door": {"cover"},
    "cover": {"cover"},
    "lock": {"lock"},
    "camera": {"camera"},
    "climate": {"climate"},
    "media_player": {"media_player"},
    "remote": {"remote"},
    "scene": {"scene"},
    "script": {"script"},
    "vacuum": {"vacuum"},
    "humidifier": {"humidifier"},
    "siren": {"siren"},
    "valve": {"valve"},
    "water_heater": {"water_heater"},
    "button": {"button"},
}

_MEDIA_PLAYER_COMMAND_FEATURES = {
    "turn_on": 128,
    "turn_off": 256,
    "set_volume": 4,
    "media_play": 16384,
    "media_pause": 1,
    "media_stop": 4096,
    "media_next": 32,
    "media_previous": 16,
}

_CONTROL_TARGET_IGNORED_WORDS = {
    "a",
    "all",
    "at",
    "can",
    "could",
    "deactivate",
    "disable",
    "enable",
    "everything",
    "for",
    "in",
    "inside",
    "my",
    "of",
    "off",
    "on",
    "please",
    "power",
    "set",
    "shut",
    "switch",
    "the",
    "to",
    "toggle",
    "turn",
    "with",
    "would",
    "you",
}

_SAFE_STATE_ATTRIBUTES = {
    "battery_level",
    "brightness",
    "color_mode",
    "color_temp_kelvin",
    "current_position",
    "current_temperature",
    "device_class",
    "fan_mode",
    "fan_modes",
    "friendly_name",
    "hvac_action",
    "hvac_mode",
    "hvac_modes",
    "media_artist",
    "media_content_type",
    "media_title",
    "percentage",
    "preset_mode",
    "preset_modes",
    "rgb_color",
    "supported_color_modes",
    "supported_features",
    "target_temp_high",
    "target_temp_low",
    "temperature",
    "unit_of_measurement",
    "volume_level",
}


def _text(value: Any, maximum: int = 0) -> str:
    result = str(value or "").strip()
    return result[:maximum] if maximum else result


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def _bounded_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def _normal_base_url(value: Any, fallback: str) -> str:
    raw = _text(value, 500).rstrip("/")
    if not raw:
        return fallback
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Provider URL must be an http or https address")
    return raw if "://" in raw else f"http://{raw}"


def _provider_needs_key(base_url: str) -> bool:
    """Return whether an endpoint is OpenAI's hosted API."""
    hostname = (urlparse(base_url).hostname or "").lower()
    return hostname == "openai.com" or hostname.endswith(".openai.com")


def normalize_tater_settings(
    value: Any, *, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Normalize persisted mini-Tater settings without dropping secrets."""
    provided: dict[str, Any] = {}
    if isinstance(base, dict):
        provided.update(base)
    if isinstance(value, dict):
        provided.update(value)
    source = dict(DEFAULT_TATER_SETTINGS)
    if isinstance(base, dict):
        source.update(base)
    if isinstance(value, dict):
        source.update(value)
    out = dict(DEFAULT_TATER_SETTINGS)
    out["assistant_mode"] = (
        ASSISTANT_MODE_TATER
        if _text(source.get("assistant_mode")).lower() == ASSISTANT_MODE_TATER
        else ASSISTANT_MODE_HOME_ASSISTANT
    )
    out["entity_scope"] = (
        ENTITY_SCOPE_ALL
        if _text(source.get("entity_scope")).lower() == ENTITY_SCOPE_ALL
        else ENTITY_SCOPE_EXPOSED
    )
    out["stt_provider"] = (
        "wyoming" if _text(source.get("stt_provider")).lower() == "wyoming" else "openai"
    )
    out["tts_provider"] = (
        "wyoming" if _text(source.get("tts_provider")).lower() == "wyoming" else "openai"
    )
    for key, maximum in _STRING_LIMITS.items():
        out[key] = _text(source.get(key), maximum)
    if out["stt_provider"] == "wyoming" and "stt_wyoming_model" not in provided:
        legacy_model = _text(provided.get("stt_model"), 160)
        if legacy_model != DEFAULT_TATER_SETTINGS["stt_model"]:
            out["stt_wyoming_model"] = legacy_model
    if out["tts_provider"] == "wyoming" and "tts_wyoming_voice" not in provided:
        legacy_voice = _text(provided.get("tts_voice"), 160)
        if legacy_voice != DEFAULT_TATER_SETTINGS["tts_voice"]:
            out["tts_wyoming_voice"] = legacy_voice
    for key in API_KEY_FIELDS:
        out[key] = _text(source.get(key), 1000)
    out["llm_base_url"] = _normal_base_url(
        source.get("llm_base_url"), DEFAULT_TATER_SETTINGS["llm_base_url"]
    )
    out["stt_base_url"] = _normal_base_url(
        source.get("stt_base_url"), DEFAULT_TATER_SETTINGS["stt_base_url"]
    )
    out["tts_base_url"] = _normal_base_url(
        source.get("tts_base_url"), DEFAULT_TATER_SETTINGS["tts_base_url"]
    )
    out["llm_temperature"] = _bounded_float(
        source.get("llm_temperature"), 0.2, 0.0, 2.0
    )
    out["stt_wyoming_port"] = _bounded_int(
        source.get("stt_wyoming_port"), 10300, 1, 65535
    )
    out["tts_wyoming_port"] = _bounded_int(
        source.get("tts_wyoming_port"), 10200, 1, 65535
    )
    out["max_display"] = _bounded_int(source.get("max_display"), 8, 1, 100)
    out["max_store"] = _bounded_int(source.get("max_store"), 20, 0, 10000)
    out["max_llm"] = _bounded_int(source.get("max_llm"), 8, 1, 100)
    out["hydra_max_ledger_items"] = _bounded_int(
        source.get("hydra_max_ledger_items"), 1500, 1, 10000
    )
    out["hydra_astraeus_plan_review_enabled"] = bool(
        source.get("hydra_astraeus_plan_review_enabled", True)
    )
    out["hydra_auto_continue_incomplete_final_enabled"] = bool(
        source.get("hydra_auto_continue_incomplete_final_enabled", False)
    )
    out["hydra_beast_mode_enabled"] = bool(
        source.get("hydra_beast_mode_enabled", False)
    )
    for role in HYDRA_ROLE_IDS:
        provider_key = f"hydra_llm_{role}_provider"
        host_key = f"hydra_llm_{role}_host"
        out[provider_key] = (
            "openai_compatible"
            if _text(source.get(provider_key)).lower() == "openai_compatible"
            else "base"
        )
        host = _text(source.get(host_key), 500)
        out[host_key] = _normal_base_url(host, "") if host else ""
    return out


def public_tater_settings(value: Any) -> dict[str, Any]:
    """Return settings safe for the management panel."""
    settings = normalize_tater_settings(value)
    public = {key: item for key, item in settings.items() if key not in API_KEY_FIELDS}
    for key in API_KEY_FIELDS:
        public[f"{key}_set"] = bool(settings.get(key))
    return public


def pcm_to_wav(pcm: bytes, audio_format: dict[str, Any] | None = None) -> bytes:
    """Wrap firmware PCM audio in a WAV container."""
    values = audio_format if isinstance(audio_format, dict) else {}
    rate = _bounded_int(values.get("rate"), 16000, 8000, 48000)
    width = _bounded_int(values.get("width"), 2, 1, 4)
    channels = _bounded_int(values.get("channels"), 1, 1, 8)
    alignment = width * channels
    payload = bytes(pcm[: len(pcm) - (len(pcm) % alignment)])
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(payload)
    return target.getvalue()


def _pcm16_rms(data: bytes, channels: int) -> float:
    """Return the RMS level for little-endian signed 16-bit PCM."""
    frame_bytes = max(1, channels) * 2
    usable = len(data) - (len(data) % frame_bytes)
    if usable <= 0:
        return 0.0
    samples = memoryview(data)[:usable].cast("h")
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


class _VadBackend:
    """Score native 16 kHz, mono, signed 16-bit PCM for speech."""

    name = "unknown"

    def process(self, data: bytes) -> float | None:
        raise NotImplementedError


class _MicroVadBackend(_VadBackend):
    """Use Home Assistant's bundled neural microVAD model."""

    name = "micro"
    _frame_bytes = 160 * 2

    def __init__(self) -> None:
        module = importlib.import_module("pymicro_vad")
        self._vad = module.MicroVad()
        self._process_10ms = getattr(self._vad, "Process10ms", None) or getattr(
            self._vad, "process_10ms", None
        )
        if not callable(self._process_10ms):
            raise RuntimeError("pymicro_vad does not expose a 10 ms processor")
        self._buffer = b""

    def process(self, data: bytes) -> float | None:
        payload = self._buffer + data
        offset = 0
        scores: list[float] = []
        while (offset + self._frame_bytes) <= len(payload):
            score = float(
                self._process_10ms(payload[offset : offset + self._frame_bytes])
            )
            offset += self._frame_bytes
            if score >= 0:
                scores.append(score)
        self._buffer = payload[offset:]
        return max(scores) if scores else None


class _EnergyVadBackend(_VadBackend):
    """Keep voice turns bounded if a packaged VAD engine cannot load."""

    name = "energy-fallback"

    def __init__(self) -> None:
        self._noise_floor: float | None = None

    def process(self, data: bytes) -> float | None:
        rms = _pcm16_rms(data, 1)
        threshold = max(450.0, (self._noise_floor or 0.0) * 2.8)
        if rms >= threshold:
            return 1.0
        self._noise_floor = (
            rms
            if self._noise_floor is None
            else (self._noise_floor * 0.92) + (rms * 0.08)
        )
        return 0.0


def _create_vad_backend(audio_format: dict[str, Any] | None) -> _VadBackend:
    """Create Home Assistant's neural detector with a bounded fail-safe."""
    values = audio_format if isinstance(audio_format, dict) else {}
    native_format = (
        _bounded_int(values.get("rate"), 16000, 8000, 48000) == 16000
        and _bounded_int(values.get("width"), 2, 1, 4) == 2
        and _bounded_int(values.get("channels"), 1, 1, 8) == 1
    )
    if not native_format:
        _LOGGER.warning(
            "Tater VAD received non-native audio; using the bounded energy detector"
        )
        return _EnergyVadBackend()

    try:
        return _MicroVadBackend()
    except Exception as err:
        _LOGGER.warning(
            "Unable to load Home Assistant's neural VAD (%s); using the bounded energy detector",
            err,
        )
        return _EnergyVadBackend()


def _endpoint(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    clean_suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    if base.endswith("/v1") and clean_suffix.startswith("/v1/"):
        clean_suffix = clean_suffix[3:]
    return f"{base}{clean_suffix}"


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return _text(value, 300)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            _text(key, 80): _json_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:40]]
    return _text(value, 300)


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).lower()).strip()


def _requested_device_domains(value: Any) -> set[str]:
    """Infer Home Assistant domains using Tater Shop device-control terms."""
    raw = _normalize_name(value)
    domains: set[str] = set()
    for category_id, terms in _DEVICE_CATEGORY_QUERY_TERMS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", raw) for term in terms):
            domains.update(_DEVICE_CATEGORY_DOMAINS.get(category_id, set()))
    return domains


def _clean_control_target(value: Any) -> str:
    """Remove device categories and action words like the Shop device Verba."""
    text = _normalize_name(value)
    category_terms = {
        term
        for terms in _DEVICE_CATEGORY_QUERY_TERMS.values()
        for term in terms
    }
    ignored = sorted(category_terms | _CONTROL_TARGET_IGNORED_WORDS, key=len, reverse=True)
    if ignored:
        text = re.sub(r"\b(?:" + "|".join(re.escape(item) for item in ignored) + r")\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class HomeEntity:
    entity_id: str
    name: str
    domain: str
    state: str
    area: str
    aliases: tuple[str, ...]
    attributes: dict[str, Any]

    def public(self, *, attributes: bool = False) -> dict[str, Any]:
        row: dict[str, Any] = {
            "entity_id": self.entity_id,
            "name": self.name,
            "domain": self.domain,
            "state": self.state,
            "area": self.area,
        }
        if attributes:
            row["attributes"] = _json_safe(
                {
                    key: value
                    for key, value in self.attributes.items()
                    if key in _SAFE_STATE_ATTRIBUTES
                }
            )
        return row


class HomeControlTool:
    """One bounded Hydra tool for Home Assistant entities and services."""

    def __init__(self, hass: HomeAssistant, settings_getter) -> None:
        self.hass = hass
        self._settings_getter = settings_getter

    def _allowed(self, entity_id: str) -> bool:
        settings = self._settings_getter()
        if settings.get("entity_scope") == ENTITY_SCOPE_ALL:
            return True
        try:
            from homeassistant.components.homeassistant.const import DATA_EXPOSED_ENTITIES

            exposed = self.hass.data.get(DATA_EXPOSED_ENTITIES)
            if not exposed:
                return False
            should_expose = getattr(exposed, "async_get_should_expose", None)
            if should_expose is None:
                should_expose = getattr(exposed, "async_should_expose", None)
            return bool(
                should_expose and should_expose("conversation", entity_id)
            )
        except (ImportError, KeyError, RuntimeError):
            _LOGGER.debug("Unable to read Assist exposure for %s", entity_id, exc_info=True)
            return False

    def entities(self) -> list[HomeEntity]:
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        area_registry = ar.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        rows: list[HomeEntity] = []
        for state in self.hass.states.async_all():
            entity_id = _text(getattr(state, "entity_id", ""))
            domain = entity_id.partition(".")[0]
            if domain not in _READABLE_DOMAINS or not self._allowed(entity_id):
                continue
            entry = entity_registry.async_get(entity_id)
            attributes = dict(getattr(state, "attributes", {}) or {})
            name = _text(attributes.get("friendly_name")) or entity_id
            area_id = _text(getattr(entry, "area_id", "")) if entry else ""
            aliases = tuple(_text(alias) for alias in (getattr(entry, "aliases", ()) or ()) if _text(alias))
            if entry and not area_id and getattr(entry, "device_id", None):
                device = device_registry.async_get(entry.device_id)
                area_id = _text(getattr(device, "area_id", "")) if device else ""
            area = area_registry.async_get_area(area_id) if area_id else None
            rows.append(
                HomeEntity(
                    entity_id=entity_id,
                    name=name,
                    domain=domain,
                    state=_text(getattr(state, "state", "")),
                    area=_text(getattr(area, "name", "")),
                    aliases=aliases,
                    attributes=attributes,
                )
            )
        return rows

    def summary(self, limit: int = 80) -> str:
        rows = self.entities()
        lines = [
            f"- {row.entity_id} | {row.name} | {row.area or 'No area'} | {row.state}"
            for row in rows[:limit]
        ]
        if len(rows) > limit:
            lines.append(
                f"- …and {len(rows) - limit} more. Use control_home search before acting on an unseen target."
            )
        return "\n".join(lines) or "- No entities are available in the selected scope."

    def _matches(self, row: HomeEntity, query: str) -> bool:
        wanted = _clean_control_target(query) or _normalize_name(query)
        if not wanted:
            return True
        candidates = [row.entity_id, row.name, row.area, *row.aliases]
        normalized = [
            _clean_control_target(item) or _normalize_name(item)
            for item in candidates
            if item
        ]
        return any(wanted == item or wanted in item or item in wanted for item in normalized)

    def resolve(self, arguments: dict[str, Any], *, request: str = "") -> list[HomeEntity]:
        rows = self.entities()
        explicit = arguments.get("entity_ids")
        entity_ids = {
            _text(item).lower()
            for item in (explicit if isinstance(explicit, list) else [])
            if _text(item)
        }
        query = _text(arguments.get("query"))
        area = _normalize_name(arguments.get("area"))
        domain = _text(arguments.get("domain")).lower()
        request_domains = _requested_device_domains(request)
        query_domains = _requested_device_domains(query)
        # A single-category request is authoritative and guards against a model
        # choosing a similarly named entity from the wrong domain. Compound
        # requests use the current atomic tool query to select the relevant
        # category instead of broadening every step to every requested domain.
        if len(request_domains) == 1:
            requested_domains = request_domains
        elif query_domains:
            requested_domains = query_domains & request_domains or query_domains
        else:
            requested_domains = request_domains
        if requested_domains:
            rows = [row for row in rows if row.domain in requested_domains]
        elif domain:
            rows = [row for row in rows if row.domain == domain]
        if entity_ids:
            explicit_rows = [row for row in rows if row.entity_id.lower() in entity_ids]
            if explicit_rows:
                rows = explicit_rows
            elif not requested_domains and not domain:
                rows = []
        if area:
            rows = [row for row in rows if _normalize_name(row.area) == area]
        request_target = _clean_control_target(request)
        query_target = _clean_control_target(query)
        query_conflicts_with_request_domain = bool(
            len(request_domains) == 1
            and query_domains
            and not (query_domains & request_domains)
        )
        target = (
            request_target
            if query_conflicts_with_request_domain and request_target
            else query_target or request_target
        )
        if target and query.lower() not in {"all", "everything"}:
            rows = [row for row in rows if self._matches(row, target)]
        return rows

    @staticmethod
    def _supports_command(row: HomeEntity, command: str) -> bool:
        if row.domain != "media_player":
            return True
        required_feature = _MEDIA_PLAYER_COMMAND_FEATURES.get(command)
        if required_feature is None:
            return True
        try:
            supported = int(row.attributes.get("supported_features") or 0)
        except (TypeError, ValueError):
            supported = 0
        return bool(supported & required_feature)

    @staticmethod
    def _target_label(rows: list[HomeEntity]) -> str:
        """Describe verified targets with friendly names and rooms."""
        unique = list({row.entity_id: row for row in rows}.values())
        if len(unique) == 1:
            row = unique[0]
            name = row.name or row.entity_id
            if row.area and _normalize_name(row.area) not in _normalize_name(name):
                return f"{name} in {row.area}"
            return name
        areas = {row.area for row in unique if row.area}
        domains = {row.domain for row in unique}
        if len(areas) == 1 and len(domains) == 1:
            domain = next(iter(domains))
            label = _DOMAIN_PLURALS.get(domain, f"{domain.replace('_', ' ')} entities")
            return f"{len(unique)} {label} in {next(iter(areas))}"
        names = [row.name or row.entity_id for row in unique]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        if len(names) <= 4:
            return f"{', '.join(names[:-1])}, and {names[-1]}"
        return f"{', '.join(names[:3])}, and {len(names) - 3} more"

    @classmethod
    def _control_summary(
        cls,
        command: str,
        rows: list[HomeEntity],
        parameters: dict[str, Any],
        failure_count: int,
    ) -> str:
        """Build the factual summary that Mini-Tater turns into a spoken reply."""
        target = cls._target_label(rows)
        if command == "set_brightness" and parameters.get("brightness_pct") is not None:
            summary = f"Set {target} to {parameters['brightness_pct']}% brightness."
        elif command == "set_color":
            color = parameters.get("color_name") or parameters.get("rgb_color")
            summary = f"Set {target} to {color}."
        elif command == "set_cover_position" and parameters.get("position") is not None:
            summary = f"Set {target} to {parameters['position']}% open."
        elif command == "set_fan_percentage" and parameters.get("percentage") is not None:
            summary = f"Set {target} to {parameters['percentage']}%."
        elif command == "set_temperature" and parameters.get("temperature") is not None:
            summary = f"Set {target} to {parameters['temperature']} degrees."
        elif command == "set_hvac_mode" and parameters.get("hvac_mode"):
            summary = f"Set {target} to {parameters['hvac_mode']} mode."
        elif command == "set_volume" and parameters.get("volume_level") is not None:
            summary = f"Set the volume on {target} to {parameters['volume_level']}."
        else:
            phrase = _CONTROL_ACTION_PHRASES.get(command)
            summary = (
                f"{phrase} {target}."
                if phrase
                else f"Ran {command.replace('_', ' ')} on {target}."
            )
        if failure_count:
            noun = "target" if failure_count == 1 else "targets"
            summary += f" {failure_count} {noun} could not be changed."
        return summary

    async def async_call(
        self,
        arguments: dict[str, Any],
        context: Context | None,
        *,
        request: str = "",
    ) -> dict[str, Any]:
        operation = _text(arguments.get("operation")).lower() or "get_state"
        rows = self.resolve(arguments, request=request)
        if operation == "search":
            return {"ok": True, "matches": [row.public() for row in rows[:40]], "count": len(rows)}
        if not rows:
            return {"ok": False, "error": "No allowed Home Assistant entity matched that target."}
        if operation == "get_state":
            return {"ok": True, "entities": [row.public(attributes=True) for row in rows[:40]], "count": len(rows)}
        if operation != "control":
            return {"ok": False, "error": "operation must be search, get_state, or control"}

        command = _text(arguments.get("command")).lower()
        command_spec = _COMMANDS.get(command)
        if command_spec is None:
            return {"ok": False, "error": f"Unsupported device command: {command or 'missing'}"}
        required_domain, service, parameter_map = command_spec
        if required_domain:
            rows = [row for row in rows if row.domain == required_domain]
        elif command in _GENERIC_COMMAND_DOMAINS:
            rows = [row for row in rows if row.domain in _GENERIC_COMMAND_DOMAINS[command]]
        else:
            rows = [row for row in rows if row.domain in _CONTROLLABLE_DOMAINS]
        rows = [row for row in rows if self._supports_command(row, command)]
        if not rows:
            return {"ok": False, "error": "The matched entities do not support that command."}

        parameters = arguments.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        grouped: dict[str, list[str]] = {}
        for row in rows:
            # Recheck exposure immediately before every mutation.
            if self._allowed(row.entity_id):
                grouped.setdefault(row.domain, []).append(row.entity_id)
        if not grouped:
            return {"ok": False, "error": "The target is no longer available in the selected entity scope."}

        performed: list[dict[str, Any]] = []
        performed_rows: list[HomeEntity] = []
        failures: list[dict[str, str]] = []
        rows_by_id = {row.entity_id: row for row in rows}
        for domain, entity_ids in grouped.items():
            actual_service = service
            if command == "activate":
                actual_service = "press" if domain == "button" else "turn_on"
            has_service = getattr(self.hass.services, "has_service", None)
            if callable(has_service) and not has_service(domain, actual_service):
                return {
                    "ok": False,
                    "error": f"{domain}.{actual_service} is unavailable for that target.",
                }
            for entity_id in entity_ids:
                data: dict[str, Any] = {"entity_id": [entity_id]}
                for source, destination in parameter_map.items():
                    if source in parameters:
                        data[destination] = _json_safe(parameters[source])
                try:
                    await self.hass.services.async_call(
                        domain,
                        actual_service,
                        data,
                        blocking=True,
                        context=context,
                    )
                except Exception as err:
                    _LOGGER.warning(
                        "Home control action %s.%s failed for %s: %s",
                        domain,
                        actual_service,
                        entity_id,
                        err,
                    )
                    failed_row = rows_by_id.get(entity_id)
                    failures.append(
                        {
                            "entity_id": entity_id,
                            "name": failed_row.name if failed_row else entity_id,
                            "area": failed_row.area if failed_row else "",
                            "error": _text(err, 500),
                        }
                    )
                    continue
                performed_row = rows_by_id[entity_id]
                performed_rows.append(performed_row)
                performed.append(
                    {
                        "domain": domain,
                        "service": actual_service,
                        "entity_ids": [entity_id],
                        "name": performed_row.name,
                        "area": performed_row.area,
                    }
                )
        if not performed:
            return {
                "ok": False,
                "error": "Home Assistant rejected the action for every matched entity.",
                "failures": failures,
            }
        result: dict[str, Any] = {
            "ok": True,
            "performed": performed,
            "facts": {
                "action": command,
                "success_count": len(performed),
                "failure_count": len(failures),
            },
            "summary_for_user": self._control_summary(
                command,
                performed_rows,
                parameters,
                len(failures),
            ),
            "say_hint": (
                "Report the verified outcome naturally and briefly. Use the friendly target or room, "
                "include any requested value, and mention partial failures."
            ),
        }
        if failures:
            result["failures"] = failures
        return result

    @staticmethod
    def definition() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "control_home",
                "description": (
                    "Search, read, or control Home Assistant devices and entities. "
                    "This is the only action tool. Search first if a target is ambiguous."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["search", "get_state", "control"]},
                        "query": {
                            "type": "string",
                            "description": (
                                "Requested room or device phrase, including category words such as lights, "
                                "fans, switches, or speakers; use 'all' only for an explicit global request."
                            ),
                        },
                        "entity_ids": {"type": "array", "items": {"type": "string"}},
                        "area": {"type": "string"},
                        "domain": {"type": "string"},
                        "command": {"type": "string", "enum": sorted(_COMMANDS)},
                        "parameters": {
                            "type": "object",
                            "description": "Command values such as brightness_pct, temperature, position, percentage, color_name, rgb_color, hvac_mode, or volume_level.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["operation"],
                    "additionalProperties": False,
                },
            },
        }


class MiniTaterRuntime:
    """Own Tater-mode provider calls, Hydra turns, and generated speech."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.home = HomeControlTool(self.hass, self.settings)
        self._clips: dict[str, tuple[float, str, bytes]] = {}
        self._turn_lock = asyncio.Lock()

    def setup(self) -> None:
        current = self.manager.data.get("tater_settings")
        self.manager.data["tater_settings"] = normalize_tater_settings(current)
        self.manager.data.setdefault("tater_conversations", {})
        self.manager.data.setdefault("tater_hydra_ledger", [])

    def settings(self) -> dict[str, Any]:
        return normalize_tater_settings(self.manager.data.get("tater_settings"))

    def snapshot(self) -> dict[str, Any]:
        ledger = self.manager.data.get("tater_hydra_ledger")
        ledger = ledger if isinstance(ledger, list) else []
        conversations = self.manager.data.get("tater_conversations")
        conversations = conversations if isinstance(conversations, dict) else {}
        settings = self.settings()
        completed = sum(1 for row in ledger if isinstance(row, dict) and row.get("outcome") == "done")
        failed = sum(1 for row in ledger if isinstance(row, dict) and row.get("outcome") == "failed")
        tool_calls = sum(len(row.get("tools", [])) for row in ledger if isinstance(row, dict) and isinstance(row.get("tools"), list))
        try:
            home_entities = self.home.entities()
        except Exception:
            _LOGGER.debug("Unable to summarize Tater home-control entities", exc_info=True)
            home_entities = []
        return {
            "settings": public_tater_settings(settings),
            "ready": self.ready_status(),
            "metrics": {
                "turns": len(ledger),
                "completed": completed,
                "failed": failed,
                "tool_calls": tool_calls,
                "conversations": len(conversations),
            },
            "ledger": list(reversed(ledger[-settings["max_display"] :])),
            "messages": self.recent_messages(settings["max_display"]),
            "home_control": {
                "entity_count": len(home_entities),
                "areas": len({row.area for row in home_entities if row.area}),
                "domains": sorted({row.domain for row in home_entities}),
                "examples": [row.public() for row in home_entities[:12]],
            },
        }

    def ready_status(self) -> dict[str, Any]:
        settings = self.settings()
        missing: list[str] = []
        if not settings["llm_model"]:
            missing.append("LLM model")
        if _provider_needs_key(settings["llm_base_url"]) and not settings["llm_api_key"]:
            missing.append("LLM API key")
        if settings["hydra_beast_mode_enabled"]:
            for role in HYDRA_ROLE_IDS:
                if settings[f"hydra_llm_{role}_provider"] == "base":
                    continue
                label = role.capitalize()
                host = settings[f"hydra_llm_{role}_host"]
                if not host:
                    missing.append(f"{label} API base URL")
                if not settings[f"hydra_llm_{role}_model"]:
                    missing.append(f"{label} model")
                if host and _provider_needs_key(host) and not settings[
                    f"hydra_llm_{role}_api_key"
                ]:
                    missing.append(f"{label} API key")
        if settings["stt_provider"] == "openai" and not (
            settings["stt_api_key"] or settings["llm_api_key"]
        ) and _provider_needs_key(settings["stt_base_url"]):
            missing.append("STT API key")
        if settings["stt_provider"] == "wyoming" and not settings["stt_wyoming_host"]:
            missing.append("STT Wyoming host")
        if settings["tts_provider"] == "openai" and not (
            settings["tts_api_key"] or settings["llm_api_key"]
        ) and _provider_needs_key(settings["tts_base_url"]):
            missing.append("TTS API key")
        if settings["tts_provider"] == "wyoming" and not settings["tts_wyoming_host"]:
            missing.append("TTS Wyoming host")
        return {
            "ok": not missing,
            "missing": missing,
            "enabled": settings["assistant_mode"] == ASSISTANT_MODE_TATER,
        }

    async def async_update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        updates = dict(values) if isinstance(values, dict) else {}
        clear_keys = updates.pop("clear_api_keys", [])
        clear_keys = clear_keys if isinstance(clear_keys, list) else []
        allowed = set(DEFAULT_TATER_SETTINGS)
        updates = {key: value for key, value in updates.items() if key in allowed}
        for key in API_KEY_FIELDS:
            if key in updates and not _text(updates[key]):
                updates.pop(key)
            if key in clear_keys:
                updates[key] = ""
        next_settings = normalize_tater_settings(updates, base=current)
        self.manager.data["tater_settings"] = next_settings
        self._trim_stored_data(next_settings)
        await self.manager.async_save()
        return public_tater_settings(next_settings)

    async def async_clear_hydra(self, *, ledger: bool, conversations: bool) -> dict[str, Any]:
        removed_ledger = 0
        removed_conversations = 0
        if ledger:
            rows = self.manager.data.get("tater_hydra_ledger")
            removed_ledger = len(rows) if isinstance(rows, list) else 0
            self.manager.data["tater_hydra_ledger"] = []
        if conversations:
            rows = self.manager.data.get("tater_conversations")
            removed_conversations = len(rows) if isinstance(rows, dict) else 0
            self.manager.data["tater_conversations"] = {}
        await self.manager.async_save()
        return {"ok": True, "ledger_removed": removed_ledger, "conversations_removed": removed_conversations}

    def recent_messages(self, limit: int) -> list[dict[str, Any]]:
        conversations = self.manager.data.get("tater_conversations")
        if not isinstance(conversations, dict):
            return []
        rows: list[dict[str, Any]] = []
        for conversation_id, messages in conversations.items():
            if not isinstance(messages, list):
                continue
            for message in messages:
                if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
                    rows.append({**message, "conversation_id": conversation_id})
        rows.sort(key=lambda row: float(row.get("time") or 0))
        return rows[-limit:]

    def _trim_stored_data(self, settings: dict[str, Any]) -> None:
        ledger = self.manager.data.get("tater_hydra_ledger")
        if not isinstance(ledger, list):
            ledger = []
        self.manager.data["tater_hydra_ledger"] = ledger[-settings["hydra_max_ledger_items"] :]
        conversations = self.manager.data.get("tater_conversations")
        if not isinstance(conversations, dict):
            conversations = {}
        max_store = settings["max_store"]
        if max_store:
            for key, rows in list(conversations.items()):
                if isinstance(rows, list):
                    conversations[key] = rows[-max_store:]
                else:
                    conversations.pop(key, None)
        self.manager.data["tater_conversations"] = conversations

    def _session(self):
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        return async_get_clientsession(self.hass)

    @staticmethod
    async def _response_error(response: aiohttp.ClientResponse) -> str:
        try:
            payload = await response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                return _text(error.get("message"), 500)
            return _text(error, 500)
        except Exception:
            return _text(await response.text(), 500)

    async def _post_json(self, url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout = aiohttp.ClientTimeout(total=120)
        async with self._session().post(url, headers=headers, json=payload, timeout=timeout) as response:
            if response.status >= 400:
                detail = await self._response_error(response)
                raise RuntimeError(f"Provider returned HTTP {response.status}: {detail or 'request failed'}")
            data = await response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Provider returned an invalid JSON response")
        return data

    def _role_model_settings(self, role: str) -> dict[str, Any]:
        """Resolve one Hydra head to the Base or its Beast Mode model."""
        settings = self.settings()
        role_id = role if role in HYDRA_ROLE_IDS else "hermes"
        resolved = {
            "base_url": settings["llm_base_url"],
            "api_key": settings["llm_api_key"],
            "model": settings["llm_model"],
            "temperature": settings["llm_temperature"],
            "dedicated": False,
        }
        if not settings["hydra_beast_mode_enabled"]:
            return resolved
        if settings[f"hydra_llm_{role_id}_provider"] == "base":
            return resolved
        resolved.update(
            {
                "base_url": settings[f"hydra_llm_{role_id}_host"],
                "api_key": settings[f"hydra_llm_{role_id}_api_key"],
                "model": settings[f"hydra_llm_{role_id}_model"],
                "dedicated": True,
            }
        )
        return resolved

    async def _chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: bool = True,
        role: str = "hermes",
        tool_choice: str | dict[str, Any] = "auto",
    ) -> dict[str, Any]:
        model = self._role_model_settings(role)
        role_name = role.capitalize()
        if not model["model"]:
            raise RuntimeError(f"Configure the {role_name} model first")
        if not model["base_url"]:
            raise RuntimeError(f"Configure the {role_name} API base URL first")
        if _provider_needs_key(model["base_url"]) and not model["api_key"]:
            raise RuntimeError(f"Configure the {role_name} API key first")
        payload: dict[str, Any] = {
            "model": model["model"],
            "messages": messages,
            "temperature": model["temperature"],
        }
        if tools:
            payload["tools"] = [self.home.definition()]
            payload["tool_choice"] = tool_choice
        endpoint = _endpoint(model["base_url"], "/v1/chat/completions")
        for attempt in range(3):
            try:
                result = await self._post_json(endpoint, model["api_key"], payload)
                break
            except RuntimeError as err:
                detail = str(err).lower()
                if "temperature" in detail and "temperature" in payload:
                    payload.pop("temperature", None)
                    continue
                if (
                    payload.get("tool_choice") == "required"
                    and ("tool_choice" in detail or "required" in detail)
                ):
                    payload["tool_choice"] = "auto"
                    continue
                raise
        else:  # pragma: no cover - every retry either succeeds or raises
            raise RuntimeError(f"{role_name} provider rejected the request")
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("The LLM returned no response choice")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("The LLM returned an invalid response message")
        return message

    @staticmethod
    def _message_json(message: dict[str, Any], label: str) -> dict[str, Any]:
        """Extract one JSON object from a head response."""
        content = _text(message.get("content"), 30000)
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I)
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise RuntimeError(f"{label} did not return JSON") from None
            try:
                value = json.loads(match.group(0))
            except json.JSONDecodeError as err:
                raise RuntimeError(f"{label} returned invalid JSON: {err.msg}") from err
        if not isinstance(value, dict):
            raise RuntimeError(f"{label} returned an invalid object")
        return value

    @staticmethod
    def _normalize_control_arguments(value: Any) -> dict[str, Any]:
        """Keep a plan step inside the one supported Home Assistant tool."""
        source = value if isinstance(value, dict) else {}
        operation = _text(source.get("operation")).lower()
        if operation not in {"search", "get_state", "control"}:
            raise RuntimeError("Astraeus planned an unsupported home operation")
        result: dict[str, Any] = {"operation": operation}
        for key in ("query", "area", "domain"):
            if item := _text(source.get(key), 300):
                result[key] = item
        raw_ids = source.get("entity_ids")
        if isinstance(raw_ids, list):
            entity_ids = list(
                dict.fromkeys(_text(item, 300) for item in raw_ids if _text(item))
            )[:40]
            if entity_ids:
                result["entity_ids"] = entity_ids
        if operation == "control":
            command = _text(source.get("command")).lower()
            if command not in _COMMANDS:
                raise RuntimeError("Astraeus planned an unsupported device command")
            result["command"] = command
            parameters = source.get("parameters")
            if isinstance(parameters, dict) and parameters:
                result["parameters"] = _json_safe(parameters)
            if not any(result.get(key) for key in ("entity_ids", "query", "area")):
                raise RuntimeError("Astraeus planned a device action without a target")
        return result

    @classmethod
    def _normalize_plan(cls, value: Any) -> dict[str, Any]:
        """Validate Astraeus output before another head can act on it."""
        source = value if isinstance(value, dict) else {}
        mode = _text(source.get("mode")).lower()
        mode = {
            "action": "execute",
            "control": "execute",
            "answer": "chat",
            "question": "clarify",
        }.get(mode, mode)
        if mode not in {"chat", "clarify", "execute"}:
            raise RuntimeError("Astraeus did not choose a valid turn mode")
        plan: dict[str, Any] = {
            "mode": mode,
            "goal": _text(source.get("goal"), 500),
            "response": _text(source.get("response"), 4000),
            "steps": [],
        }
        if mode != "execute":
            return plan
        raw_steps = source.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise RuntimeError("Astraeus returned an empty execution plan")
        used_ids: set[str] = set()
        for index, raw_step in enumerate(raw_steps[:12], start=1):
            if not isinstance(raw_step, dict):
                raise RuntimeError("Astraeus returned an invalid plan step")
            step_id = re.sub(
                r"[^a-zA-Z0-9_-]+", "-", _text(raw_step.get("id"), 40)
            ).strip("-") or f"step-{index}"
            if step_id in used_ids:
                step_id = f"{step_id}-{index}"
            used_ids.add(step_id)
            plan["steps"].append(
                {
                    "id": step_id,
                    "instruction": _text(raw_step.get("instruction"), 500)
                    or f"Complete device action {index}",
                    "arguments": cls._normalize_control_arguments(
                        raw_step.get("arguments")
                    ),
                }
            )
        return plan

    def _astraeus_prompt(self) -> str:
        return (
            "You are Astraeus, Hydra's planning head for Mini-Tater. Route the request and return JSON only. "
            "Use mode chat for conversation or knowledge, clarify only when a required target or value is truly missing, "
            "and execute for Home Assistant searches, reads, or actions. For execute, create an ordered atomic plan with "
            "one step for every requested action. Never omit a clause. Different commands require separate steps; several "
            "entities receiving the same command may share one step. Prefer exact entity_ids from the inventory. Each step "
            "must contain only id, instruction, and arguments matching control_home. Do not invent entities, services, or values.\n"
            "Schema: {\"mode\":\"chat|clarify|execute\",\"goal\":\"...\",\"response\":\"optional\","
            "\"steps\":[{\"id\":\"step-1\",\"instruction\":\"...\",\"arguments\":{"
            "\"operation\":\"search|get_state|control\",\"query\":\"...\",\"entity_ids\":[\"domain.id\"],"
            "\"area\":\"...\",\"domain\":\"...\",\"command\":\"supported command\","
            "\"parameters\":{}}}]}.\n"
            f"Supported control commands: {', '.join(sorted(_COMMANDS))}.\n"
            "Available home entities in the selected scope:\n"
            f"{self.home.summary()}"
        )

    async def _plan_turn(
        self,
        user_text: str,
        history: list[dict[str, Any]],
        *,
        repair_reason: str = "",
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": self._astraeus_prompt()},
            *history,
            {
                "role": "user",
                "content": (
                    user_text
                    if not repair_reason
                    else (
                        f"Original request: {user_text}\n"
                        f"Repair the plan because the review found: {repair_reason}"
                    )
                ),
            },
        ]
        return self._normalize_plan(
            self._message_json(
                await self._chat(messages, tools=False, role="astraeus"),
                "Astraeus",
            )
        )

    async def _review_plan(
        self, user_text: str, plan: dict[str, Any]
    ) -> tuple[bool, str]:
        if plan.get("mode") != "execute":
            return True, "No device plan required"
        if not self.settings()["hydra_astraeus_plan_review_enabled"]:
            return True, "Second plan review disabled"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Astraeus's second plan check. Verify that the proposed Home Assistant plan covers every "
                    "action in the user's request exactly once, uses supported control_home arguments, does not broaden "
                    "targets, and does not invent devices or values. Return JSON only: "
                    "{\"approved\":true|false,\"reason\":\"short specific reason\"}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"request": user_text, "plan": plan}, ensure_ascii=False
                ),
            },
        ]
        try:
            value = self._message_json(
                await self._chat(messages, tools=False, role="astraeus"),
                "Astraeus review",
            )
            return bool(value.get("approved")), _text(value.get("reason"), 500)
        except Exception as err:
            _LOGGER.warning("Hydra plan review failed; blocking action: %s", err)
            return False, f"Plan review failed: {err}"

    @staticmethod
    def _same_locked_action(
        planned: dict[str, Any], proposed: dict[str, Any]
    ) -> bool:
        """Require Thanatos to execute the atomic action Astraeus locked."""
        return json.dumps(_json_safe(planned), sort_keys=True) == json.dumps(
            _json_safe(proposed), sort_keys=True
        )

    async def _run_thanatos_step(
        self,
        *,
        user_text: str,
        step: dict[str, Any],
        previous_results: list[dict[str, Any]],
        context: Context | None,
    ) -> dict[str, Any]:
        planned_arguments = step["arguments"]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Thanatos, Hydra's execution head. Execute exactly one locked atomic step by calling "
                    "control_home exactly once. Copy the locked arguments exactly. Do not broaden, combine, skip, "
                    "or substitute targets or commands. Return only the native tool call."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": user_text,
                        "locked_step": step,
                        "previous_results": previous_results,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        assistant = await self._chat(
            messages,
            role="thanatos",
            tool_choice="required",
        )
        tool_calls = assistant.get("tool_calls")
        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            return {
                "ok": False,
                "error": "Thanatos did not return exactly one control_home call",
            }
        tool_call = tool_calls[0]
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        function = function if isinstance(function, dict) else {}
        if _text(function.get("name")) != "control_home":
            return {"ok": False, "error": "Thanatos selected an unavailable tool"}
        try:
            proposed = self._normalize_control_arguments(
                json.loads(_text(function.get("arguments")) or "{}")
            )
        except (json.JSONDecodeError, RuntimeError) as err:
            return {"ok": False, "error": f"Thanatos returned invalid arguments: {err}"}
        if not self._same_locked_action(planned_arguments, proposed):
            return {
                "ok": False,
                "error": "Thanatos changed the locked Astraeus action",
            }
        return await self.home.async_call(proposed, context, request=user_text)

    def _hermes_prompt(self) -> str:
        settings = self.settings()
        return (
            f"You are Hermes, Hydra's response head for {settings['assistant_name'] or 'Tater'}, a voice assistant inside Home Assistant.\n"
            f"{settings['personality']}\n"
            "For an execution turn, report only outcomes supported by the supplied control_home results. Cover every "
            "requested action, including partial failures. Use friendly device or room names and requested values. "
            "Never claim a Home Assistant action happened when no verified execution result is supplied. "
            "Never mention tools, entity IDs, heads, plans, or internal execution. For chat, answer the user's request "
            "directly. Keep spoken replies concise and natural, usually one or two sentences."
        )

    @staticmethod
    def _execution_fallback(executions: list[dict[str, Any]]) -> str:
        summaries: list[str] = []
        failures = 0
        for execution in executions:
            result = execution.get("result")
            if isinstance(result, dict) and result.get("ok"):
                if summary := _text(result.get("summary_for_user"), 1000):
                    summaries.append(summary)
            else:
                failures += 1
        if failures:
            summaries.append(
                f"{failures} requested action{'s' if failures != 1 else ''} could not be completed."
            )
        return " ".join(summaries) or "I couldn't complete that request."

    async def _render_hermes(
        self,
        *,
        user_text: str,
        history: list[dict[str, Any]],
        plan: dict[str, Any],
        executions: list[dict[str, Any]],
    ) -> str:
        messages = [
            {"role": "system", "content": self._hermes_prompt()},
            *history,
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": user_text,
                        "route": plan.get("mode"),
                        "planner_response": plan.get("response"),
                        "goal": plan.get("goal"),
                        "executions": executions,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        message = await self._chat(messages, tools=False, role="hermes")
        final_text = _text(message.get("content"), 12000)
        if not final_text and self.settings()[
            "hydra_auto_continue_incomplete_final_enabled"
        ]:
            messages.append(
                {
                    "role": "user",
                    "content": "Finish with the complete short spoken response now.",
                }
            )
            final_text = _text(
                (
                    await self._chat(messages, tools=False, role="hermes")
                ).get("content"),
                12000,
            )
        return final_text

    async def async_process_text(
        self,
        text: str,
        *,
        conversation_id: str,
        device_id: str = "",
        context: Context | None = None,
    ) -> dict[str, Any]:
        user_text = _text(text, 12000)
        if not user_text:
            raise ValueError("The transcript was empty")
        settings = self.settings()
        session_id = _text(conversation_id, 160) or f"tater-{_text(device_id, 100) or secrets.token_hex(6)}"
        started = time.monotonic()
        ledger_row: dict[str, Any] = {
            "id": secrets.token_hex(8),
            "time": time.time(),
            "conversation_id": session_id,
            "device_id": _text(device_id, 160),
            "request": user_text,
            "outcome": "running",
            "tools": [],
        }
        async with self._turn_lock:
            conversations = self.manager.data.setdefault("tater_conversations", {})
            history = conversations.get(session_id)
            history = history if isinstance(history, list) else []
            model_history = [
                {"role": row.get("role"), "content": row.get("content")}
                for row in history[-settings["max_llm"] :]
                if isinstance(row, dict) and row.get("role") in {"user", "assistant"}
            ]
            messages: list[dict[str, Any]] = [
                *model_history,
            ]
            final_text = ""
            try:
                plan = await self._plan_turn(user_text, messages)
                initial_plan_mode = plan["mode"]
                approved, review_reason = await self._review_plan(user_text, plan)
                if not approved:
                    plan = await self._plan_turn(
                        user_text,
                        messages,
                        repair_reason=review_reason,
                    )
                    if initial_plan_mode == "execute" and plan["mode"] != "execute":
                        approved = False
                        review_reason = "The repaired plan dropped the required device execution"
                    else:
                        approved, review_reason = await self._review_plan(user_text, plan)
                ledger_row["plan"] = _json_safe(plan)
                ledger_row["plan_review"] = {
                    "approved": approved,
                    "reason": review_reason,
                }
                executions: list[dict[str, Any]] = []
                if plan["mode"] == "execute":
                    if not approved:
                        raise RuntimeError(
                            f"Astraeus could not produce an approved plan: {review_reason}"
                        )
                    for step in plan["steps"]:
                        result = await self._run_thanatos_step(
                            user_text=user_text,
                            step=step,
                            previous_results=executions,
                            context=context,
                        )
                        execution = {
                            "step_id": step["id"],
                            "instruction": step["instruction"],
                            "arguments": _json_safe(step["arguments"]),
                            "result": _json_safe(result),
                        }
                        executions.append(execution)
                        ledger_row["tools"].append(
                            {
                                "name": "control_home",
                                "head": "thanatos",
                                "step_id": step["id"],
                                "arguments": _json_safe(step["arguments"]),
                                "approved": bool(result.get("ok"))
                                if isinstance(result, dict)
                                else False,
                                "review": (
                                    "Executed the locked Astraeus step"
                                    if isinstance(result, dict) and result.get("ok")
                                    else _text(
                                        result.get("error")
                                        if isinstance(result, dict)
                                        else "Execution failed",
                                        500,
                                    )
                                ),
                                "result": _json_safe(result),
                            }
                        )
                try:
                    final_text = await self._render_hermes(
                        user_text=user_text,
                        history=messages,
                        plan=plan,
                        executions=executions,
                    )
                except Exception as err:
                    if plan["mode"] != "execute":
                        raise
                    _LOGGER.warning(
                        "Hermes response failed after device execution: %s", err
                    )
                    final_text = self._execution_fallback(executions)
                if not final_text:
                    final_text = (
                        self._execution_fallback(executions)
                        if plan["mode"] == "execute"
                        else plan.get("response") or "I couldn't complete that request."
                    )
                now = time.time()
                history.extend(
                    [
                        {"role": "user", "content": user_text, "time": now},
                        {"role": "assistant", "content": final_text, "time": now},
                    ]
                )
                conversations[session_id] = history
                ledger_row.update(
                    {
                        "outcome": "done",
                        "response": final_text,
                        "total_ms": round((time.monotonic() - started) * 1000),
                    }
                )
            except Exception as err:
                ledger_row.update(
                    {
                        "outcome": "failed",
                        "error": _text(err, 1000) or type(err).__name__,
                        "total_ms": round((time.monotonic() - started) * 1000),
                    }
                )
                raise
            finally:
                ledger = self.manager.data.setdefault("tater_hydra_ledger", [])
                if not isinstance(ledger, list):
                    ledger = []
                    self.manager.data["tater_hydra_ledger"] = ledger
                ledger.append(ledger_row)
                self._trim_stored_data(settings)
                await self.manager.async_save()
        return {
            "response": final_text,
            "conversation_id": session_id,
            "continue_conversation": False,
            "tools": ledger_row["tools"],
        }

    async def async_transcribe(
        self,
        audio_stream: AsyncGenerator[bytes],
        audio_format: dict[str, Any] | None,
    ) -> str:
        settings = self.settings()
        if settings["stt_provider"] == "wyoming":
            return await self._transcribe_wyoming(audio_stream, audio_format)
        chunks: list[bytes] = []
        audio_bytes = 0
        async for chunk in audio_stream:
            audio_bytes += len(chunk)
            if audio_bytes > MAX_PROVIDER_AUDIO_BYTES:
                raise RuntimeError("The captured voice request is too long")
            chunks.append(chunk)
        wav_bytes = pcm_to_wav(b"".join(chunks), audio_format)
        form = aiohttp.FormData()
        form.add_field("file", wav_bytes, filename="satellite.wav", content_type="audio/wav")
        form.add_field("model", settings["stt_model"] or "gpt-4o-transcribe")
        if settings["stt_language"]:
            form.add_field("language", settings["stt_language"])
        api_key = settings["stt_api_key"] or settings["llm_api_key"]
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        url = _endpoint(settings["stt_base_url"], "/v1/audio/transcriptions")
        async with self._session().post(
            url,
            headers=headers,
            data=form,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            if response.status >= 400:
                detail = await self._response_error(response)
                raise RuntimeError(f"STT returned HTTP {response.status}: {detail or 'request failed'}")
            payload = await response.json()
        return _text(payload.get("text") if isinstance(payload, dict) else "", 12000)

    async def _voice_activity_stream(
        self,
        audio_stream: AsyncGenerator[bytes],
        audio_format: dict[str, Any] | None,
        sensitivity: str,
        event_callback,
    ) -> AsyncGenerator[bytes]:
        """Yield one utterance and close capture using Home Assistant's neural VAD."""
        values = audio_format if isinstance(audio_format, dict) else {}
        rate = _bounded_int(values.get("rate"), 16000, 8000, 48000)
        width = _bounded_int(values.get("width"), 2, 1, 4)
        channels = _bounded_int(values.get("channels"), 1, 1, 8)
        backend = _create_vad_backend(audio_format)
        end_silence = VAD_END_SILENCE_SECONDS.get(
            _text(sensitivity).lower(),
            VAD_END_SILENCE_SECONDS["default"],
        )
        frame_bytes = width * channels
        pending: deque[tuple[bytes, float]] = deque()
        pending_seconds = 0.0
        total_seconds = 0.0
        speech_candidate_seconds = 0.0
        trailing_silence_seconds = 0.0
        speech_started = False
        vad_ended = False

        async def end_vad() -> None:
            nonlocal vad_ended
            if vad_ended:
                return
            vad_ended = True
            await event_callback("STT_VAD_END", {})

        try:
            async for chunk in audio_stream:
                if not chunk:
                    continue
                chunk_seconds = len(chunk) / max(1, rate * frame_bytes)
                total_seconds += chunk_seconds
                speech_probability = backend.process(chunk)

                if not speech_started:
                    pending.append((chunk, chunk_seconds))
                    pending_seconds += chunk_seconds
                    while pending and pending_seconds > VAD_PRE_ROLL_SECONDS:
                        _old_chunk, old_seconds = pending.popleft()
                        pending_seconds -= old_seconds

                    if speech_probability is not None:
                        if speech_probability >= 0.2:
                            speech_candidate_seconds += chunk_seconds
                        else:
                            speech_candidate_seconds = 0.0

                    if speech_candidate_seconds >= VAD_SPEECH_START_SECONDS:
                        speech_started = True
                        await event_callback("STT_VAD_START", {})
                        while pending:
                            buffered, _duration = pending.popleft()
                            yield buffered
                        pending_seconds = 0.0
                    elif total_seconds >= VAD_NO_SPEECH_SECONDS:
                        break
                    continue

                yield chunk
                if speech_probability is not None:
                    if speech_probability >= 0.5:
                        trailing_silence_seconds = 0.0
                    else:
                        trailing_silence_seconds += chunk_seconds
                if (
                    trailing_silence_seconds >= end_silence
                    or total_seconds >= VAD_MAX_UTTERANCE_SECONDS
                ):
                    break
        finally:
            await end_vad()

        if not speech_started:
            raise RuntimeError("No speech was detected")

    async def _transcribe_wyoming(
        self,
        audio_stream: AsyncGenerator[bytes],
        audio_format: dict[str, Any] | None,
    ) -> str:
        from wyoming.asr import Transcribe, Transcript
        from wyoming.audio import AudioChunk, AudioStart, AudioStop
        from wyoming.client import AsyncTcpClient
        from wyoming.error import Error

        settings = self.settings()
        values = audio_format if isinstance(audio_format, dict) else {}
        rate = _bounded_int(values.get("rate"), 16000, 8000, 48000)
        width = _bounded_int(values.get("width"), 2, 1, 4)
        channels = _bounded_int(values.get("channels"), 1, 1, 8)
        async with AsyncTcpClient(settings["stt_wyoming_host"], settings["stt_wyoming_port"]) as client:
            await client.write_event(
                Transcribe(
                    name=settings["stt_wyoming_model"] or None,
                    language=settings["stt_language"] or None,
                ).event()
            )
            await client.write_event(AudioStart(rate=rate, width=width, channels=channels).event())
            async for chunk in audio_stream:
                await client.write_event(
                    AudioChunk(rate=rate, width=width, channels=channels, audio=chunk).event()
                )
            await client.write_event(AudioStop().event())
            while event := await client.read_event():
                if Transcript.is_type(event.type):
                    return _text(Transcript.from_event(event).text, 12000)
                if Error.is_type(event.type):
                    raise RuntimeError(_text(Error.from_event(event).text) or "Wyoming STT failed")
        raise RuntimeError("Wyoming STT returned no transcript")

    async def async_synthesize(self, text: str) -> tuple[str, bytes]:
        settings = self.settings()
        if settings["tts_provider"] == "wyoming":
            return await self._synthesize_wyoming(text)
        payload = {
            "model": settings["tts_model"] or "gpt-4o-tts",
            "input": _text(text, 12000),
            "voice": settings["tts_voice"] or "alloy",
            "response_format": "wav",
        }
        api_key = settings["tts_api_key"] or settings["llm_api_key"]
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = _endpoint(settings["tts_base_url"], "/v1/audio/speech")
        async with self._session().post(
            url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            if response.status >= 400:
                detail = await self._response_error(response)
                raise RuntimeError(f"TTS returned HTTP {response.status}: {detail or 'request failed'}")
            audio = await response.read()
            if len(audio) > MAX_PROVIDER_AUDIO_BYTES:
                raise RuntimeError("The synthesized voice response is too large")
            return "audio/wav", audio

    async def _synthesize_wyoming(self, text: str) -> tuple[str, bytes]:
        from wyoming.audio import AudioChunk, AudioStart, AudioStop
        from wyoming.client import AsyncTcpClient
        from wyoming.error import Error
        from wyoming.tts import Synthesize, SynthesizeVoice

        settings = self.settings()
        voice = (
            SynthesizeVoice(name=settings["tts_wyoming_voice"])
            if settings["tts_wyoming_voice"]
            else None
        )
        audio_format = {"rate": 16000, "width": 2, "channels": 1}
        chunks: list[bytes] = []
        async with AsyncTcpClient(settings["tts_wyoming_host"], settings["tts_wyoming_port"]) as client:
            await client.write_event(Synthesize(text=_text(text, 12000), voice=voice).event())
            while event := await client.read_event():
                if AudioStart.is_type(event.type):
                    start = AudioStart.from_event(event)
                    audio_format = {"rate": start.rate, "width": start.width, "channels": start.channels}
                elif AudioChunk.is_type(event.type):
                    chunks.append(AudioChunk.from_event(event).audio)
                elif AudioStop.is_type(event.type):
                    break
                elif Error.is_type(event.type):
                    raise RuntimeError(_text(Error.from_event(event).text) or "Wyoming TTS failed")
        if not chunks:
            raise RuntimeError("Wyoming TTS returned no audio")
        return "audio/wav", pcm_to_wav(b"".join(chunks), audio_format)

    def store_clip(self, content_type: str, data: bytes) -> str:
        now = time.time()
        self._clips = {
            key: value for key, value in self._clips.items() if value[0] > now
        }
        clip_id = secrets.token_urlsafe(24)
        self._clips[clip_id] = (now + 10 * 60, content_type, bytes(data))
        if len(self._clips) > MAX_STORED_SPEECH_CLIPS:
            oldest = sorted(self._clips, key=lambda key: self._clips[key][0])
            for stale_id in oldest[: len(self._clips) - MAX_STORED_SPEECH_CLIPS]:
                self._clips.pop(stale_id, None)
        return clip_id

    def clip(self, clip_id: str) -> tuple[str, bytes] | None:
        value = self._clips.get(_text(clip_id))
        if value is None or value[0] <= time.time():
            self._clips.pop(_text(clip_id), None)
            return None
        return value[1], value[2]

    async def async_run_voice(
        self,
        satellite: SatelliteRuntime,
        audio_stream: AsyncGenerator[bytes],
        audio_format: dict[str, Any],
        conversation_id: str,
        event_callback,
    ) -> None:
        await event_callback("RUN_START", {})
        await event_callback("STT_START", {})
        vad_stream = self._voice_activity_stream(
            audio_stream,
            audio_format,
            "default",
            event_callback,
        )
        transcript = await self.async_transcribe(vad_stream, audio_format)
        if not transcript:
            raise RuntimeError("STT returned no speech")
        await event_callback("STT_END", {"text": transcript})
        await event_callback("INTENT_START", {})
        result = await self.async_process_text(
            transcript,
            conversation_id=conversation_id,
            device_id=satellite.device_id,
        )
        speech = _text(result.get("response"), 12000)
        await event_callback(
            "INTENT_END",
            {
                "conversation_id": result.get("conversation_id", ""),
                "continue_conversation": bool(result.get("continue_conversation")),
                "speech": speech,
            },
        )
        await event_callback("TTS_START", {"text": speech})
        content_type, audio = await self.async_synthesize(speech)
        clip_id = self.store_clip(content_type, audio)
        base_url = satellite.server_base_url or self.manager.public_base_url()
        url = f"{base_url}/api/tater/satellite/v1/tater/audio/{clip_id}"
        await event_callback("TTS_END", {"url": url})
        await event_callback("RUN_END", {})
