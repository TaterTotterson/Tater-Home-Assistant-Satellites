"""Small, Home Assistant-only Tater voice runtime.

The desktop Tater runtime intentionally is not imported here. This module owns
the complete satellite turn when Tater mode is selected: STT, a Home Assistant
specific Astraeus/Thanatos/Hermes loop, device control, current-camera vision,
TTS, and a bounded execution ledger.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
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
    "vision_api_key",
    "stt_api_key",
    "tts_api_key",
    *HYDRA_ROLE_API_KEY_FIELDS,
)
MAX_PROVIDER_AUDIO_BYTES = 32 * 1024 * 1024
MAX_STORED_SPEECH_CLIPS = 20
MAX_VISION_IMAGES = 4
MAX_VISION_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VISION_TOTAL_BYTES = 12 * 1024 * 1024
MAX_TATER_VISION_CAMERAS = 6
VISION_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
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
    "vision_provider": "base",
    "vision_base_url": "",
    "vision_api_key": "",
    "vision_model": "",
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
    "vision_base_url": 500,
    "vision_model": 160,
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

DEVICE_CONTROL_VERBA_DESCRIPTION = (
    "Use for any request to control or check smart-home devices across integrations, "
    "including lights, switches, plugs, fans, covers, garage doors, locks, thermostats, "
    "media players, remotes, scenes, scripts, and appliance readings such as washer, dryer, "
    "or dishwasher status and remaining time. Use Tater Vision for visual camera questions."
)
TATER_VISION_VERBA_DESCRIPTION = (
    "Tater Vision is Tater's visual-question tool. Use it whenever the answer requires looking at a person, "
    "object, room, or named camera-covered area right now—including 'what is this?', 'how do I look?', "
    "'is the dog in the game room?', 'are there any dogs in the backyard?', and conversational follow-ups such "
    "as 'what did you see when you looked?'. If the user names a room or area, it automatically uses the cameras "
    "covering that location. If no location is named, use trusted room context supplied by a satellite or other "
    "room-aware platform; when no room context exists, ask which room, area, or camera to use."
)

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

_COLOR_NAMES = {
    "red",
    "orange",
    "amber",
    "yellow",
    "green",
    "blue",
    "cyan",
    "teal",
    "purple",
    "violet",
    "magenta",
    "pink",
    "white",
    "daylight",
    "warm white",
    "cool white",
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
    "back",
    "base",
    "brighten",
    "at",
    "can",
    "check",
    "clean",
    "close",
    "color",
    "colour",
    "could",
    "deactivate",
    "dim",
    "disable",
    "dock",
    "enable",
    "everything",
    "how",
    "for",
    "in",
    "inside",
    "is",
    "are",
    "list",
    "lock",
    "lower",
    "make",
    "me",
    "mute",
    "next",
    "mode",
    "my",
    "now",
    "open",
    "of",
    "off",
    "on",
    "please",
    "play",
    "press",
    "previous",
    "power",
    "raise",
    "resume",
    "return",
    "run",
    "s",
    "send",
    "set",
    "show",
    "skip",
    "shut",
    "speed",
    "state",
    "status",
    "start",
    "stop",
    "switch",
    "temperature",
    "tell",
    "temp",
    "the",
    "to",
    "toggle",
    "turn",
    "unlock",
    "unmute",
    "push",
    "volume",
    "what",
    "whether",
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
    out["vision_provider"] = (
        "openai_compatible"
        if _text(source.get("vision_provider")).lower() == "openai_compatible"
        else "base"
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
    vision_base_url = _text(source.get("vision_base_url"), 500)
    out["vision_base_url"] = (
        _normal_base_url(vision_base_url, "") if vision_base_url else ""
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


def normalize_vision_images(value: Any) -> list[dict[str, Any]]:
    """Validate bounded image data URLs received from the management chat."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Vision images must be a list")
    if len(value) > MAX_VISION_IMAGES:
        raise ValueError(f"Attach no more than {MAX_VISION_IMAGES} images")
    images: list[dict[str, Any]] = []
    total_bytes = 0
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError("Each vision image must be an object")
        data_url = _text(item.get("data_url"), MAX_VISION_IMAGE_BYTES * 2)
        match = re.fullmatch(
            r"data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)",
            data_url,
        )
        if not match:
            raise ValueError("Vision images must be base64 image data URLs")
        mime_type = match.group(1).lower()
        if mime_type not in VISION_IMAGE_TYPES:
            raise ValueError("Vision images must be JPEG, PNG, WebP, or GIF files")
        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError) as err:
            raise ValueError("Vision image data is not valid base64") from err
        if not raw:
            raise ValueError("Vision images cannot be empty")
        if len(raw) > MAX_VISION_IMAGE_BYTES:
            raise ValueError("Each vision image must be 5 MB or smaller")
        total_bytes += len(raw)
        if total_bytes > MAX_VISION_TOTAL_BYTES:
            raise ValueError("Vision attachments must total 12 MB or less")
        images.append(
            {
                "data_url": data_url,
                "name": _text(item.get("name"), 160) or f"image-{index}",
                "mime_type": mime_type,
                "size_bytes": len(raw),
            }
        )
    return images


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
    raw = _text(value).lower()
    raw = re.sub(r"https?://\S+", " ", raw)
    raw = re.sub(r"\brgb\s*\([^)]*\)", " ", raw, flags=re.I)
    raw = re.sub(r"#[0-9a-fA-F]{3,6}\b", " ", raw)
    raw = re.sub(r"\d{1,3}(?:\.\d+)?\s*(?:%|percent|degrees?|deg|f|c)?", " ", raw)
    text = _normalize_name(raw)
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

    def __init__(self, hass: HomeAssistant, settings_getter, llm_json=None) -> None:
        self.hass = hass
        self._settings_getter = settings_getter
        self._llm_json = llm_json

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
                f"- …and {len(rows) - limit} more. device_control resolves targets against the complete allowed inventory."
            )
        return "\n".join(lines) or "- No entities are available in the selected scope."

    @staticmethod
    def _percent_from_text(value: Any) -> int | None:
        raw = _text(value).lower()
        for pattern in (
            r"\b(\d{1,3})\s*(?:%|percent)\b",
            r"\b(?:to|at|level|position|volume|brightness|speed)\s+(\d{1,3})\b",
        ):
            match = re.search(pattern, raw)
            if match:
                return max(0, min(100, int(match.group(1))))
        return None

    @staticmethod
    def _temperature_from_text(value: Any) -> float | None:
        match = re.search(
            r"\b(\d{2,3}(?:\.\d+)?)\s*(?:degrees?|deg|°|f|c)?\b",
            _text(value).lower(),
        )
        return float(match.group(1)) if match else None

    @staticmethod
    def _rgb_from_text(value: Any) -> list[int] | None:
        raw = _text(value)
        rgb = re.search(
            r"\brgb\s*(?:\(\s*|[:=]?\s*)(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*\)?",
            raw,
            flags=re.I,
        )
        if rgb:
            return [max(0, min(255, int(rgb.group(index)))) for index in (1, 2, 3)]
        hex_color = re.search(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", raw)
        if not hex_color:
            return None
        token = hex_color.group(1)
        if len(token) == 3:
            token = "".join(character * 2 for character in token)
        return [int(token[0:2], 16), int(token[2:4], 16), int(token[4:6], 16)]

    @staticmethod
    def _color_name_from_text(value: Any) -> str:
        raw = _text(value).lower()
        for color in sorted(_COLOR_NAMES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(color)}\b", raw):
                return color
        return ""

    @staticmethod
    def _hvac_mode_from_text(value: Any) -> str:
        raw = f" {_text(value).lower()} "
        for mode in ("heat_cool", "auto", "cool", "heat", "off", "dry", "fan_only"):
            if f" {mode} " in raw or f" {mode.replace('_', ' ')} " in raw:
                return mode
        return ""

    @classmethod
    def _natural_arguments(cls, query: str) -> dict[str, Any]:
        """Interpret the same natural-language-first contract as Device Control."""
        raw = _text(query, 2000)
        compact = re.sub(r"\s+", " ", f" {raw.lower()} ")
        requested_categories = _requested_device_domains(raw)
        percent = cls._percent_from_text(raw)
        rgb_color = cls._rgb_from_text(raw)
        color_name = cls._color_name_from_text(raw)
        temperature = cls._temperature_from_text(raw)
        hvac_mode = cls._hvac_mode_from_text(raw)
        command = ""
        parameters: dict[str, Any] = {}

        if percent is not None and requested_categories == {"light"}:
            command = "set_brightness"
            parameters["brightness_pct"] = percent
        elif percent is not None and requested_categories == {"fan"}:
            command = "set_fan_percentage"
            parameters["percentage"] = percent
        elif percent is not None and requested_categories == {"cover"}:
            command = "set_cover_position"
            parameters["position"] = percent
        elif percent is not None and requested_categories == {"media_player"}:
            command = "set_volume"
            parameters["volume_level"] = round(percent / 100.0, 3)
        elif requested_categories == {"light"} and (rgb_color or color_name):
            command = "set_color"
            if rgb_color:
                parameters["rgb_color"] = rgb_color
            elif color_name:
                parameters["color_name"] = color_name
        elif requested_categories == {"climate"} and temperature is not None:
            command = "set_temperature"
            parameters["temperature"] = temperature
            if hvac_mode:
                parameters["hvac_mode"] = hvac_mode
        elif requested_categories == {"climate"} and hvac_mode:
            command = "set_hvac_mode"
            parameters["hvac_mode"] = hvac_mode
        elif re.search(r"\b(unlock|open lock)\b", compact):
            command = "unlock"
        elif re.search(r"\block\b", compact):
            command = "lock"
        elif "scene" in _requested_device_domains(raw) and re.search(r"\b(activate|run|start|turn on)\b", compact):
            command = "activate"
        elif "script" in _requested_device_domains(raw) and re.search(r"\b(run|start|execute|turn on)\b", compact):
            command = "activate"
        elif "button" in _requested_device_domains(raw) and re.search(r"\b(press|push|run)\b", compact):
            command = "press"
        elif "vacuum" in _requested_device_domains(raw) and re.search(r"\b(return|dock|base|home)\b", compact):
            command = "return_to_base"
        elif "vacuum" in _requested_device_domains(raw) and re.search(r"\b(start|clean|run)\b", compact):
            command = "start_vacuum"
        elif re.search(r"\b(turn|switch|power|set)\s+(?:[\w -]+?\s+)?on\b|\benable\b", compact):
            command = "turn_on"
        elif re.search(r"\b(turn|switch|power|shut|set)\s+(?:[\w -]+?\s+)?off\b|\b(disable|deactivate)\b", compact):
            command = "turn_off"
        elif re.search(r"\b(toggle|flip)\b", compact):
            command = "toggle"
        elif requested_categories == {"cover"} and re.search(r"\b(open|raise|up)\b", compact):
            command = "open_cover"
        elif requested_categories == {"cover"} and re.search(r"\b(close|shut|lower|down)\b", compact):
            command = "close_cover"
        elif requested_categories == {"cover"} and re.search(r"\b(stop|halt)\b", compact):
            command = "stop_cover"
        elif requested_categories == {"media_player"} and re.search(r"\b(next|skip)\b", compact):
            command = "media_next"
        elif requested_categories == {"media_player"} and re.search(r"\b(previous|back)\b", compact):
            command = "media_previous"
        elif requested_categories == {"media_player"} and re.search(r"\bpause\b", compact):
            command = "media_pause"
        elif requested_categories == {"media_player"} and re.search(r"\bstop\b", compact):
            command = "media_stop"
        elif requested_categories == {"media_player"} and re.search(r"\b(play|resume)\b", compact):
            command = "media_play"

        list_request = bool(
            re.search(r"\b(list|inventory)\b", compact)
            or re.search(r"\bshow\b.*\b(all|available|devices?|rooms?)\b", compact)
        )
        status_request = bool(
            not command
            and (
                re.search(r"\b(status|state|check|is|are|what|whether|how|show me)\b", compact)
                or "?" in raw
            )
        )
        operation = "search" if list_request else "get_state" if status_request else "control"

        target_source = raw
        if command == "set_color":
            for color in sorted(_COLOR_NAMES, key=len, reverse=True):
                target_source = re.sub(rf"\b{re.escape(color)}\b", " ", target_source, flags=re.I)
        if command == "set_hvac_mode":
            for mode in ("heat cool", "fan only", "auto", "cool", "heat", "off", "dry"):
                target_source = re.sub(rf"\b{re.escape(mode)}\b", " ", target_source, flags=re.I)
        target = _clean_control_target(target_source)
        explicit_global = bool(re.search(r"\b(all|every|everything)\b", compact))
        result: dict[str, Any] = {"operation": operation}
        if target:
            result["query"] = target
        elif explicit_global or operation in {"search", "get_state"}:
            result["query"] = "all"
        if command:
            result["command"] = command
        if parameters:
            result["parameters"] = parameters
        return result

    async def _complete_natural_arguments(
        self, query: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Use the Thanatos model only when deterministic Verba-style parsing is incomplete."""
        if not callable(self._llm_json):
            return arguments
        operation = _text(arguments.get("operation")).lower()
        if operation != "control" or (
            _text(arguments.get("command")) and _text(arguments.get("query"))
        ):
            return arguments
        prompt = (
            "Interpret one natural-language Home Assistant device request. Return JSON only with keys "
            "operation, command, target, and parameters. operation must be search, get_state, or control. "
            f"command must be one of {', '.join(sorted(_COMMANDS))}, or an empty string. "
            "target is only the named room or device without action words. Never invent a target, command, "
            "or value. parameters may contain only brightness_pct, temperature, position, percentage, "
            "color_name, rgb_color, hvac_mode, or volume_level."
        )
        try:
            value = await self._llm_json(prompt, {"query": query})
        except Exception:
            _LOGGER.debug("Mini-Tater device interpretation fallback failed", exc_info=True)
            return arguments
        if not isinstance(value, dict):
            return arguments
        completed = dict(arguments)
        deterministic_command = _text(completed.get("command"))
        proposed_operation = _text(value.get("operation")).lower()
        if proposed_operation in {"search", "get_state", "control"}:
            completed["operation"] = proposed_operation
        proposed_command = _text(value.get("command")).lower()
        if not completed.get("command") and proposed_command in _COMMANDS:
            completed["command"] = proposed_command
        target = _clean_control_target(value.get("target"))
        if target and (
            not _text(completed.get("query")) or not deterministic_command
        ):
            completed["query"] = target
        if not completed.get("parameters") and isinstance(value.get("parameters"), dict):
            completed["parameters"] = _json_safe(value["parameters"])
        return completed

    async def _choose_ambiguous_row(
        self,
        *,
        query: str,
        target: str,
        rows: list[HomeEntity],
    ) -> HomeEntity | None:
        """Match the Device Control Verba's bounded LLM chooser for ambiguous names."""
        if not callable(self._llm_json) or not rows:
            return None
        candidates = [
            {**row.public(), "aliases": list(row.aliases)} for row in rows[:80]
        ]
        prompt = (
            "Choose the best Home Assistant entity for this device request. Return JSON only as "
            "{\"entity_id\":\"an exact id from candidates or empty\"}. Use names, aliases, rooms, "
            "domains, states, and the requested action. Pick exactly one only when the request clearly "
            "identifies it. Return an empty id when ambiguous and never invent an id."
        )
        try:
            value = await self._llm_json(
                prompt,
                {"query": query, "target": target, "candidates": candidates},
            )
        except Exception:
            _LOGGER.debug("Mini-Tater device chooser failed", exc_info=True)
            return None
        entity_id = _text(value.get("entity_id")) if isinstance(value, dict) else ""
        return next((row for row in rows if row.entity_id == entity_id), None)

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
        natural_query = _text(arguments.get("query"), 2000)
        natural_contract = bool(natural_query and not _text(arguments.get("operation")))
        if natural_contract:
            request = natural_query
            arguments = self._natural_arguments(natural_query)
            arguments = await self._complete_natural_arguments(
                natural_query, arguments
            )
        operation = _text(arguments.get("operation")).lower() or "get_state"
        if operation == "control" and not _text(arguments.get("query")) and not arguments.get("entity_ids"):
            return {
                "ok": False,
                "error": "The device request needs a room or device name.",
                "needs": ["Which room or device should I use?"],
            }
        rows = self.resolve(arguments, request=request)
        if natural_contract and operation == "control" and len(rows) > 1:
            target = _clean_control_target(arguments.get("query"))
            if target and target != "all":
                exact = [
                    row
                    for row in rows
                    if target == _clean_control_target(row.name)
                    or any(
                        target == _clean_control_target(alias)
                        for alias in row.aliases
                    )
                ]
                room = [
                    row
                    for row in rows
                    if target == _clean_control_target(row.area)
                ]
                if len(exact) == 1:
                    rows = exact
                elif room:
                    rows = room
                else:
                    candidates = exact or rows
                    selected = await self._choose_ambiguous_row(
                        query=natural_query,
                        target=target,
                        rows=candidates,
                    )
                    if selected is None:
                        choices = ", ".join(
                            f"{row.name}{f' in {row.area}' if row.area else ''}"
                            for row in candidates[:10]
                        )
                        return {
                            "ok": False,
                            "error": f"The target '{target}' matched more than one device.",
                            "needs": [
                                f"Choose a room or specific device: {choices}"
                            ],
                        }
                    rows = [selected]
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
                "name": "device_control",
                "description": DEVICE_CONTROL_VERBA_DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "One complete natural-language device instruction, such as "
                                "'turn off the office lights' or 'is the bedroom fan on'."
                            ),
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }


class TaterVisionTool:
    """Fresh, ephemeral visual questions through Home Assistant cameras."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: TaterSatelliteManager,
        allowed,
        describe_images,
    ) -> None:
        self.hass = hass
        self.manager = manager
        self._allowed = allowed
        self._describe_images = describe_images

    @staticmethod
    def definition() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "tater_vision",
                "description": TATER_VISION_VERBA_DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's complete visual question, unchanged.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }

    @staticmethod
    def _normalized_words(value: Any) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", _text(value).casefold()))

    @staticmethod
    def _compact_words(value: Any) -> str:
        return "".join(re.findall(r"[a-z0-9]+", _text(value).casefold()))

    @classmethod
    def _query_mentions(cls, query: str, label: Any) -> bool:
        normalized_label = cls._normalized_words(label)
        if len(normalized_label) < 3 or normalized_label in {
            "camera",
            "show",
            "echo show",
            "room",
            "outside",
            "inside",
            "current room",
            "this room",
        }:
            return False
        normalized_query = cls._normalized_words(query)
        if re.search(
            rf"(?:^| ){re.escape(normalized_label)}(?: |$)", normalized_query
        ):
            return True
        compact_label = cls._compact_words(normalized_label)
        return len(compact_label) >= 5 and compact_label in cls._compact_words(
            normalized_query
        )

    @classmethod
    def _semantic_outdoor_area(cls, query: str) -> tuple[str, str] | None:
        normalized = cls._normalized_words(query)
        if re.search(
            r"(?:^| )(?:out front|front yard|front lawn|front of (?:the )?(?:house|home)|front exterior)(?: |$)",
            normalized,
        ):
            return "front", "Front"
        if re.search(
            r"(?:^| )(?:out back|back yard|backyard|rear yard|back lawn|back of (?:the )?(?:house|home)|rear exterior)(?: |$)",
            normalized,
        ):
            return "back", "Back"
        mentions_outside = bool(
            re.search(r"(?:^| )(?:outside|outdoors|exterior)(?: |$)", normalized)
            or re.search(
                r"(?:^| )around (?:the )?(?:house|home)(?: |$)", normalized
            )
        )
        appearance_question = bool(
            re.search(
                r"(?:^| )(?:wear|wearing|wore|outfit|clothes|clothing|dressed|dress|jacket|coat)(?: |$)",
                normalized,
            )
        )
        outdoor_view_request = bool(
            re.search(
                r"(?:^| )(?:look|see|show|check|view|inspect|watch)(?: (?:at|around|through))? (?:the )?outside(?: |$)",
                normalized,
            )
            or re.search(
                r"(?:^| )(?:weather|conditions|happening|going on) (?:out|outside)(?: |$)",
                normalized,
            )
            or re.search(
                r"(?:^| )(?:what|who|anything|anyone|someone|animal|animals|dog|dogs|cat|cats) .* outside(?: |$)",
                normalized,
            )
        )
        if mentions_outside and (outdoor_view_request or not appearance_question):
            return "outside", "Outside"
        if re.search(r"(?:^| )(?:the )?(?:yard|lawn)(?: |$)", normalized):
            return "yard", "Yard"
        return None

    @classmethod
    def _matches_semantic_area(cls, camera: dict[str, Any], area: str) -> bool:
        words = cls._normalized_words(
            " ".join(
                _text(value)
                for value in (
                    camera.get("room"),
                    camera.get("name"),
                    *(camera.get("aliases") or []),
                )
                if _text(value)
            )
        )
        tokens = set(words.split())
        front = {"front", "doorbell", "entry", "entrance", "driveway", "garage"}
        back = {"back", "rear", "backyard", "patio", "deck"}
        outside = front | back | {
            "yard",
            "lawn",
            "porch",
            "outside",
            "outdoor",
            "exterior",
            "gate",
            "side",
        }
        if area == "front":
            return bool(tokens & front) and not bool(tokens & {"back", "rear"})
        if area == "back":
            return bool(tokens & back) and "front" not in tokens
        if area == "yard":
            return bool(tokens & {"yard", "backyard", "lawn"})
        return area == "outside" and bool(tokens & outside)

    def cameras(self) -> list[dict[str, Any]]:
        """Return allowed HA cameras plus connected satellite cameras."""
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        area_registry = ar.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        rows: list[dict[str, Any]] = []
        for state in self.hass.states.async_all("camera"):
            entity_id = _text(getattr(state, "entity_id", ""))
            if not entity_id or not self._allowed(entity_id):
                continue
            entry = entity_registry.async_get(entity_id)
            area_id = _text(getattr(entry, "area_id", "")) if entry else ""
            if entry and not area_id and getattr(entry, "device_id", None):
                device = device_registry.async_get(entry.device_id)
                area_id = _text(getattr(device, "area_id", "")) if device else ""
            area = area_registry.async_get_area(area_id) if area_id else None
            attributes = dict(getattr(state, "attributes", {}) or {})
            rows.append(
                {
                    "source": "home_assistant",
                    "entity_id": entity_id,
                    "name": _text(attributes.get("friendly_name"))
                    or _text(getattr(state, "name", ""))
                    or entity_id,
                    "room": _text(getattr(area, "name", "")),
                    "aliases": [
                        _text(alias)
                        for alias in (getattr(entry, "aliases", ()) or ())
                        if _text(alias)
                    ],
                    "available": _text(getattr(state, "state", "")).lower()
                    not in {"unavailable", "unknown"},
                }
            )
        for runtime in getattr(self.manager, "runtimes", {}).values():
            if not runtime.connected or not bool(
                runtime.capabilities.get("camera_snapshot")
            ):
                continue
            rows.append(
                {
                    "source": "native_satellite",
                    "device_id": runtime.device_id,
                    "name": runtime.name,
                    "room": runtime.room,
                    "aliases": [],
                    "available": True,
                    "runtime": runtime,
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                _text(row.get("room")).casefold(),
                _text(row.get("name")).casefold(),
            ),
        )

    def summary(self) -> dict[str, Any]:
        cameras = self.cameras()
        return {
            "camera_count": len(cameras),
            "areas": len({_text(row.get("room")) for row in cameras if row.get("room")}),
            "examples": [
                {
                    "name": row.get("name"),
                    "room": row.get("room"),
                    "source": row.get("source"),
                    "available": row.get("available", True),
                }
                for row in cameras[:8]
            ],
        }

    @classmethod
    def _select_cameras(
        cls,
        cameras: list[dict[str, Any]],
        query: str,
        origin_room: str,
        device_id: str,
    ) -> tuple[list[dict[str, Any]], str, str]:
        known_rooms = sorted(
            {_text(row.get("room")) for row in cameras if row.get("room")},
            key=lambda value: (-len(cls._compact_words(value)), value.casefold()),
        )
        mentioned_rooms = [room for room in known_rooms if cls._query_mentions(query, room)]
        if mentioned_rooms:
            longest = max(len(cls._compact_words(room)) for room in mentioned_rooms)
            normalized = {
                cls._normalized_words(room)
                for room in mentioned_rooms
                if len(cls._compact_words(room)) == longest
            }
            selected = [
                row
                for row in cameras
                if cls._normalized_words(row.get("room")) in normalized
            ]
            return selected[:MAX_TATER_VISION_CAMERAS], "named_area", mentioned_rooms[0]

        named = [
            row
            for row in cameras
            if any(
                cls._query_mentions(query, alias)
                for alias in [row.get("name"), *(row.get("aliases") or [])]
            )
        ]
        if named:
            best = max(
                max(
                    (
                        len(cls._compact_words(alias))
                        for alias in [row.get("name"), *(row.get("aliases") or [])]
                    ),
                    default=0,
                )
                for row in named
            )
            selected = [
                row
                for row in named
                if max(
                    (
                        len(cls._compact_words(alias))
                        for alias in [row.get("name"), *(row.get("aliases") or [])]
                    ),
                    default=0,
                )
                == best
            ]
            return (
                selected[:MAX_TATER_VISION_CAMERAS],
                "named_camera",
                _text(selected[0].get("room")),
            )

        semantic = cls._semantic_outdoor_area(query)
        if semantic:
            area, label = semantic
            selected = [row for row in cameras if cls._matches_semantic_area(row, area)]
            return selected[:MAX_TATER_VISION_CAMERAS], "semantic_area", label

        normalized_origin = cls._normalized_words(origin_room)
        if not normalized_origin:
            return [], "origin_room_unknown", ""
        selected = [
            row
            for row in cameras
            if cls._normalized_words(row.get("room")) == normalized_origin
        ]
        selected.sort(
            key=lambda row: (
                0 if _text(row.get("device_id")) == device_id else 1,
                0 if row.get("source") == "native_satellite" else 1,
                _text(row.get("name")).casefold(),
            )
        )
        return selected[:MAX_TATER_VISION_CAMERAS], "asking_room", origin_room

    @staticmethod
    def _decode_snapshot(result: Any) -> tuple[bytes | None, str]:
        payload = (
            result.get("result")
            if isinstance(result, dict) and isinstance(result.get("result"), dict)
            else result
        )
        mime_type = "image/jpeg"
        if isinstance(payload, dict):
            candidate_type = _text(
                payload.get("content_type")
                or payload.get("mimetype")
                or payload.get("mime")
                or payload.get("media_content_type")
            ).lower()
            if candidate_type.startswith("image/"):
                mime_type = candidate_type.split(";", 1)[0]
            values = [
                payload.get(key)
                for key in (
                    "image_base64",
                    "bytes",
                    "data",
                    "content",
                    "image_bytes",
                    "image_data",
                )
            ]
        else:
            values = [payload]
        for value in values:
            if isinstance(value, (bytes, bytearray, memoryview)):
                image = bytes(value)
            elif isinstance(value, str):
                encoded = (
                    value.split(",", 1)[1]
                    if value.startswith("data:") and "," in value
                    else value
                )
                try:
                    image = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    continue
            else:
                continue
            if 0 < len(image) <= MAX_VISION_IMAGE_BYTES:
                return image, mime_type
        return None, mime_type

    async def _snapshot(self, camera: dict[str, Any]) -> tuple[bytes, str]:
        if camera.get("source") == "native_satellite":
            result = await camera["runtime"].async_request(
                "camera.snapshot",
                {"reason": "explicit_tater_vision_request"},
                timeout=11.0,
            )
            image, mime_type = self._decode_snapshot(result)
            if not image:
                raise RuntimeError("The satellite returned no usable image")
            return image, mime_type
        from homeassistant.components.camera import async_get_image

        image = await async_get_image(
            self.hass, camera["entity_id"], timeout=10, width=1280
        )
        content = bytes(image.content)
        mime_type = _text(image.content_type).split(";", 1)[0].lower()
        if not content or len(content) > MAX_VISION_IMAGE_BYTES:
            raise RuntimeError("The camera returned an empty or oversized image")
        if mime_type not in VISION_IMAGE_TYPES:
            raise RuntimeError(f"The camera returned unsupported {mime_type or 'image'} data")
        return content, mime_type

    @staticmethod
    def _vision_prompt(query: str, name: str, room: str, camera_count: int) -> str:
        multi_view = (
            " This is one of several views; report only the evidence visible here so Hermes can combine them."
            if camera_count > 1
            else ""
        )
        return (
            f"This is a current still image from {name or 'a camera'}"
            f"{f' in {room}' if room else ''}. Answer this exact visual request directly: {query}."
            f"{multi_view} For appearance questions, give a warm, honest, practical opinion based only on what is visible. "
            "For objects or activity, report only what the image supports. Do not identify people or infer sensitive "
            "traits. If the subject is not visible or framing is poor, say so clearly. Keep the response concise."
        )

    async def async_call(
        self,
        arguments: dict[str, Any],
        context: Context | None,
        *,
        request: str = "",
        device_id: str = "",
    ) -> dict[str, Any]:
        del context
        query = _text(arguments.get("query") or request, 2000)
        if not query:
            return {
                "ok": False,
                "error": "Please provide the visual question for Tater Vision.",
                "needs": ["Ask what Tater should look at or comment on."],
                "say_hint": "Ask what the user wants Tater to look at.",
            }
        cameras = self.cameras()
        origin_runtime = getattr(self.manager, "runtimes", {}).get(device_id)
        origin_room = _text(getattr(origin_runtime, "room", ""))
        selected, reason, target_room = self._select_cameras(
            cameras, query, origin_room, device_id
        )
        if not selected and reason == "origin_room_unknown":
            return {
                "ok": False,
                "error": (
                    "The asking satellite needs a room assignment before Tater can choose a nearby camera."
                    if device_id and device_id != "management-panel"
                    else "Tater Vision needs a room, area, or camera name for this request."
                ),
                "needs": [
                    "Assign the asking satellite to a room."
                    if device_id and device_id != "management-panel"
                    else "Name the room, area, or camera Tater should use."
                ],
                "say_hint": "Ask which room, area, or camera Tater should look through.",
            }
        if not selected:
            return {
                "ok": False,
                "error": f"No available camera was found for {target_room or 'that location'}.",
                "needs": ["Make a camera available in that Home Assistant area or choose another camera."],
                "say_hint": "Explain that Tater cannot see that location because no camera is available there.",
            }

        descriptions: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        snapshot_bytes = 0
        for index, camera in enumerate(selected):
            name = _text(camera.get("name")) or "Camera"
            room = _text(camera.get("room")) or target_room
            try:
                image_bytes, mime_type = await self._snapshot(camera)
                snapshot_bytes += len(image_bytes)
                data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
                observation = await self._describe_images(
                    self._vision_prompt(query, name, room, len(selected)),
                    [
                        {
                            "name": f"tater-vision-{index + 1}.jpg",
                            "mime_type": mime_type,
                            "size_bytes": len(image_bytes),
                            "data_url": data_url,
                        }
                    ],
                )
                descriptions.append(
                    {"camera": name, "room": room, "description": observation}
                )
            except Exception as err:
                failures.append(
                    {"camera": name, "error": _text(err, 500) or type(err).__name__}
                )
        if not descriptions:
            detail = "; ".join(
                f"{row['camera']}: {row['error']}" for row in failures[:3]
            )
            return {
                "ok": False,
                "error": detail or "No selected camera returned a usable image.",
                "say_hint": "Explain that cameras were found, but Tater could not get or analyze their current images.",
            }
        summary = (
            descriptions[0]["description"]
            if len(descriptions) == 1
            else "\n".join(
                f"{row['camera']}: {row['description']}" for row in descriptions
            )
        )
        return {
            "ok": True,
            "facts": {
                "camera_count": len(selected),
                "vision_count": len(descriptions),
                "vision_failure_count": len(failures),
                "target_room": target_room,
                "selection_reason": reason,
                "snapshot_bytes": snapshot_bytes,
            },
            "data": {
                "description": summary,
                "vision_descriptions": descriptions,
                "vision_failures": failures,
                "target_room": target_room,
            },
            "summary_for_user": summary,
            "say_hint": (
                "Answer the user's visual question directly using the returned camera descriptions. "
                "Combine multiple views when needed and do not add details the vision model did not report."
            ),
        }


class MiniTaterRuntime:
    """Own Tater-mode provider calls, Hydra turns, and generated speech."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.home = HomeControlTool(
            self.hass,
            self.settings,
            self._device_llm_json,
        )
        self.vision = TaterVisionTool(
            self.hass,
            self.manager,
            self.home._allowed,
            self._describe_images,
        )
        self._clips: dict[str, tuple[float, str, bytes]] = {}
        self._turn_lock = asyncio.Lock()
        self._structured_text_fallbacks: set[str] = set()

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
        try:
            vision_summary = self.vision.summary()
        except Exception:
            _LOGGER.debug("Unable to summarize Tater Vision cameras", exc_info=True)
            vision_summary = {"camera_count": 0, "areas": 0, "examples": []}
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
            "tater_vision": vision_summary,
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
        vision_missing: list[str] = []
        if settings["vision_provider"] == "openai_compatible":
            if not settings["vision_base_url"]:
                vision_missing.append("Vision API base URL")
            if not settings["vision_model"]:
                vision_missing.append("Vision model")
            if (
                settings["vision_base_url"]
                and _provider_needs_key(settings["vision_base_url"])
                and not settings["vision_api_key"]
            ):
                vision_missing.append("Vision API key")
        return {
            "ok": not missing,
            "missing": missing,
            "enabled": settings["assistant_mode"] == ASSISTANT_MODE_TATER,
            "vision": {
                "ok": not vision_missing,
                "missing": vision_missing,
                "provider": settings["vision_provider"],
            },
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

    def _vision_model_settings(self) -> dict[str, Any]:
        """Resolve image understanding to Base or a dedicated endpoint."""
        settings = self.settings()
        if settings["vision_provider"] == "base":
            return {
                "base_url": settings["llm_base_url"],
                "api_key": settings["llm_api_key"],
                "model": settings["llm_model"],
                "temperature": settings["llm_temperature"],
                "dedicated": False,
            }
        return {
            "base_url": settings["vision_base_url"],
            "api_key": settings["vision_api_key"],
            "model": settings["vision_model"],
            "temperature": settings["llm_temperature"],
            "dedicated": True,
        }

    @staticmethod
    def _message_text(message: dict[str, Any]) -> str:
        """Read text from common OpenAI-compatible message shapes."""
        content = message.get("content")
        if isinstance(content, str):
            return _text(content, 12000)
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if _text(item.get("type")).lower() not in {"text", "output_text"}:
                continue
            part = _text(item.get("text"), 12000)
            if part:
                parts.append(part)
        return _text("\n".join(parts), 12000)

    async def _describe_images(
        self, user_text: str, images: list[dict[str, Any]]
    ) -> str:
        """Produce bounded visual context before the normal Hydra turn."""
        model = self._vision_model_settings()
        if not model["model"]:
            raise RuntimeError("Configure a vision-capable Base model or a dedicated Vision model first")
        if not model["base_url"]:
            raise RuntimeError("Configure the Vision API base URL first")
        if _provider_needs_key(model["base_url"]) and not model["api_key"]:
            raise RuntimeError("Configure the Vision API key first")
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Inspect the attached image or images for Mini-Tater. Answer the user's visual request with a "
                    "concise, factual observation. Identify uncertainty. Do not claim that any Home Assistant action "
                    "was performed. User request: "
                    f"{user_text or 'Describe the attached image.'}"
                ),
            }
        ]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": image["data_url"]},
            }
            for image in images
        )
        payload: dict[str, Any] = {
            "model": model["model"],
            "messages": [{"role": "user", "content": content}],
            "temperature": model["temperature"],
            "max_tokens": 1200,
        }
        endpoint = _endpoint(model["base_url"], "/v1/chat/completions")
        try:
            result = await self._post_json(endpoint, model["api_key"], payload)
        except RuntimeError as err:
            if "temperature" not in str(err).lower():
                raise
            payload.pop("temperature", None)
            result = await self._post_json(endpoint, model["api_key"], payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("The Vision model returned no response choice")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("The Vision model returned an invalid response message")
        observation = self._message_text(message)
        if not observation:
            raise RuntimeError("The Vision model returned an empty observation")
        return observation

    async def _chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: bool = True,
        role: str = "hermes",
        tool_choice: str | dict[str, Any] = "auto",
        native_tools: list[dict[str, Any]] | None = None,
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
        if native_tools is not None:
            payload["tools"] = native_tools
            payload["tool_choice"] = tool_choice
        elif tools:
            payload["tools"] = [self.home.definition(), self.vision.definition()]
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

    async def _structured_head_json(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str,
        function_name: str,
        description: str,
        schema: dict[str, Any],
        label: str,
    ) -> dict[str, Any]:
        """Use Tater-style native structured output with a cached text fallback."""
        message: dict[str, Any] | None = None
        if function_name not in self._structured_text_fallbacks:
            native_tool = {
                "type": "function",
                "function": {
                    "name": function_name,
                    "description": description,
                    "parameters": schema,
                },
            }
            try:
                message = await self._chat(
                    messages,
                    tools=False,
                    role=role,
                    tool_choice="required",
                    native_tools=[native_tool],
                )
            except RuntimeError:
                self._structured_text_fallbacks.add(function_name)
        if isinstance(message, dict):
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    function = (
                        tool_call.get("function")
                        if isinstance(tool_call, dict)
                        else None
                    )
                    if not isinstance(function, dict) or _text(
                        function.get("name")
                    ) != function_name:
                        continue
                    try:
                        value = json.loads(
                            _text(function.get("arguments")) or "{}"
                        )
                    except json.JSONDecodeError:
                        break
                    if isinstance(value, dict):
                        return value
            if _text(message.get("content")):
                return self._message_json(message, label)
        fallback = await self._chat(messages, tools=False, role=role)
        return self._message_json(fallback, label)

    async def _device_llm_json(
        self, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Provide the Device Control Verba's bounded interpretation/chooser call."""
        message = await self._chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            tools=False,
            role="thanatos",
        )
        return self._message_json(message, "Device Control")

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
                r"[^a-zA-Z0-9_-]+",
                "-",
                _text(raw_step.get("id") or raw_step.get("step_id"), 40),
            ).strip("-") or f"step-{index}"
            if step_id in used_ids:
                step_id = f"{step_id}-{index}"
            used_ids.add(step_id)
            natural_instruction = _text(
                raw_step.get("nl") or raw_step.get("instruction"),
                500,
            )
            if not natural_instruction:
                raise RuntimeError("Astraeus planned a tool step without a natural-language instruction")
            tool_hint = _text(raw_step.get("tool_hint") or "device_control", 80)
            if tool_hint not in {"device_control", "tater_vision"}:
                raise RuntimeError("Astraeus selected an unavailable Mini-Tater tool")
            plan["steps"].append(
                {
                    "id": step_id,
                    "intent": _text(raw_step.get("intent"), 300)
                    or natural_instruction,
                    "nl": natural_instruction,
                    "tool_hint": tool_hint,
                }
            )
        return plan

    def _astraeus_prompt(self) -> str:
        return (
            "You are Astraeus, Hydra's planning head for Mini-Tater. Route the request and return JSON only. "
            "The user message is a JSON input envelope containing the current request and, when available, a "
            "conversation transcript. Use the transcript only to resolve follow-ups and references; it contains "
            "Hermes replies and is not an example of your output format. "
            "Use mode chat for conversation, knowledge, or an attached-image request whose input already contains a visual "
            "observation. Use clarify only when a required target or value is truly missing. Use execute for Home Assistant "
            "searches, reads, actions, or a request to inspect a current camera view. For execute, create an ordered atomic "
            "plan with one step for every requested action or visual question. Never omit a clause. Different device commands "
            "require separate steps; several devices receiving the same command may share one step. Resolve follow-up references "
            "in nl using the conversation transcript. Use device_control for Home Assistant device searches, states, and actions. "
            "Use tater_vision for current visual questions that require a fresh camera image, including what is visible, how the "
            "user looks, or whether a person, animal, or object is in a named room or outdoor area. The nl field must preserve "
            "the user's complete request, target, action, and value. Do not invent devices, cameras, locations, or values.\n"
            "Schema: {\"mode\":\"chat|clarify|execute\",\"goal\":\"...\",\"response\":\"optional\","
            "\"steps\":[{\"id\":\"step-1\",\"intent\":\"short purpose\","
            "\"nl\":\"complete natural-language instruction\",\"tool_hint\":\"device_control|tater_vision\"}]}.\n"
            "Astraeus stable execution catalog:\n"
            "{\"available_tool_ids\":[\"device_control\",\"tater_vision\"],\"available_capabilities\":[{"
            f"\"id\":\"device_control\",\"description\":{json.dumps(DEVICE_CONTROL_VERBA_DESCRIPTION, ensure_ascii=False)}"
            "},{"
            f"\"id\":\"tater_vision\",\"description\":{json.dumps(TATER_VISION_VERBA_DESCRIPTION, ensure_ascii=False)}"
            "}]}"
        )

    async def _plan_turn(
        self,
        user_text: str,
        history: list[dict[str, Any]],
        *,
        repair_reason: str = "",
    ) -> dict[str, Any]:
        transcript = [
            {
                "role": row.get("role"),
                "content": _text(row.get("content"), 4000),
            }
            for row in history
            if isinstance(row, dict)
            and row.get("role") in {"user", "assistant"}
            and _text(row.get("content"))
        ]
        input_envelope: dict[str, Any] = {
            "request": user_text,
            "conversation": transcript,
        }
        if repair_reason:
            input_envelope["repair_reason"] = repair_reason
        messages = [
            {"role": "system", "content": self._astraeus_prompt()},
            {
                "role": "user",
                "content": json.dumps(input_envelope, ensure_ascii=False),
            },
        ]
        plan_schema = {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["chat", "clarify", "execute"],
                },
                "goal": {"type": "string"},
                "response": {"type": "string"},
                "steps": {
                    "type": "array",
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "intent": {"type": "string"},
                            "nl": {"type": "string"},
                            "tool_hint": {
                                "type": "string",
                                "enum": ["device_control", "tater_vision"],
                            },
                        },
                        "required": ["id", "intent", "nl", "tool_hint"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["mode", "goal", "response", "steps"],
            "additionalProperties": False,
        }
        return self._normalize_plan(
            await self._structured_head_json(
                messages,
                role="astraeus",
                function_name="submit_hydra_plan",
                description="Submit Mini-Tater's route and atomic built-in-tool plan.",
                schema=plan_schema,
                label="Astraeus",
            )
        )

    async def _review_plan(
        self, user_text: str, plan: dict[str, Any]
    ) -> tuple[bool, str]:
        if plan.get("mode") != "execute":
            return True, "No tool plan required"
        if not self.settings()["hydra_astraeus_plan_review_enabled"]:
            return True, "Second plan review disabled"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Astraeus's second plan check. Verify that the proposed Home Assistant plan covers every "
                    "action or current visual question in the user's request exactly once, uses only device_control or "
                    "tater_vision, selects the correct tool for each step, keeps every nl instruction atomic and "
                    "natural-language-first, does not broaden targets, and does not invent devices, cameras, locations, "
                    "or values. Return JSON only: "
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
            value = await self._structured_head_json(
                messages,
                role="astraeus",
                function_name="submit_hydra_plan_review",
                description="Approve or reject the proposed atomic built-in-tool plan.",
                schema={
                    "type": "object",
                    "properties": {
                        "approved": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["approved", "reason"],
                    "additionalProperties": False,
                },
                label="Astraeus review",
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
        if set(proposed) != {"query"}:
            return False
        expected = " ".join(_text(planned.get("query"), 500).split()).casefold()
        actual = " ".join(_text(proposed.get("query"), 500).split()).casefold()
        return bool(expected) and expected == actual

    async def _run_thanatos_step(
        self,
        *,
        user_text: str,
        step: dict[str, Any],
        previous_results: list[dict[str, Any]],
        context: Context | None,
        device_id: str = "",
    ) -> dict[str, Any]:
        tool_name = step["tool_hint"]
        tool_definition = (
            self.vision.definition()
            if tool_name == "tater_vision"
            else self.home.definition()
        )
        planned_arguments = {"query": step["nl"]}
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Thanatos, Hydra's execution head. Execute exactly one locked atomic Astraeus step. "
                    "The single native function supplied with this request is the authoritative execution tool contract. "
                    f"Call {tool_name} exactly once and pass the locked step's nl text unchanged as query. Do not broaden, "
                    "combine, skip, reinterpret, substitute the target, action, or value, or select another tool. "
                    "Return only the native tool call."
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
        last_error = f"Thanatos did not return a valid {tool_name} call"
        for attempt in range(2):
            attempt_messages = list(messages)
            if attempt:
                attempt_messages[0] = {
                    "role": "system",
                    "content": (
                        f"{messages[0]['content']} Repair the previous call: {last_error}. "
                        f"Call {tool_name} once with exactly {{\"query\":{json.dumps(step['nl'])}}}."
                    ),
                }
            assistant = await self._chat(
                attempt_messages,
                role="thanatos",
                tool_choice="required",
                native_tools=[tool_definition],
            )
            tool_calls = assistant.get("tool_calls")
            if not isinstance(tool_calls, list) or len(tool_calls) != 1:
                last_error = f"Thanatos did not return exactly one {tool_name} call"
                continue
            tool_call = tool_calls[0]
            function = tool_call.get("function") if isinstance(tool_call, dict) else None
            function = function if isinstance(function, dict) else {}
            if _text(function.get("name")) != tool_name:
                last_error = "Thanatos selected an unavailable tool"
                continue
            try:
                proposed = json.loads(_text(function.get("arguments")) or "{}")
            except json.JSONDecodeError as err:
                last_error = f"Thanatos returned invalid arguments: {err.msg}"
                continue
            if not isinstance(proposed, dict) or not self._same_locked_action(
                planned_arguments, proposed
            ):
                last_error = "Thanatos changed the locked Astraeus natural-language action"
                continue
            if tool_name == "tater_vision":
                return await self.vision.async_call(
                    proposed,
                    context,
                    request=step["nl"],
                    device_id=device_id,
                )
            return await self.home.async_call(proposed, context, request=step["nl"])
        return {"ok": False, "error": last_error, "attempts": 2}

    def _hermes_prompt(self) -> str:
        settings = self.settings()
        return (
            f"You are Hermes, Hydra's response head for {settings['assistant_name'] or 'Tater'}, a voice assistant inside Home Assistant.\n"
            f"{settings['personality']}\n"
            "For an execution turn, report only outcomes supported by the supplied device_control or tater_vision results. "
            "Cover every requested action or visual question, including partial failures. Use friendly device, camera, or "
            "room names and requested values. For vision, answer the exact question from the returned descriptions and do "
            "not add visual details the model did not report. "
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
                f"{failures} requested step{'s' if failures != 1 else ''} could not be completed."
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
        images: Any = None,
    ) -> dict[str, Any]:
        user_text = _text(text, 12000)
        vision_images = normalize_vision_images(images)
        if not user_text and vision_images:
            user_text = "Describe the attached image."
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
            "images": [
                {
                    "name": image["name"],
                    "mime_type": image["mime_type"],
                    "size_bytes": image["size_bytes"],
                }
                for image in vision_images
            ],
        }
        async with self._turn_lock:
            conversations = self.manager.data.setdefault("tater_conversations", {})
            history = conversations.get(session_id)
            history = history if isinstance(history, list) else []
            model_history: list[dict[str, Any]] = []
            for row in history[-settings["max_llm"] :]:
                if not isinstance(row, dict) or row.get("role") not in {
                    "user",
                    "assistant",
                }:
                    continue
                history_content = _text(row.get("content"), 12000)
                prior_vision = _text(row.get("vision_context"), 12000)
                if row.get("role") == "user" and prior_vision:
                    history_content = (
                        f"{history_content}\n\nPrior visual observation:\n{prior_vision}"
                    )
                model_history.append(
                    {"role": row.get("role"), "content": history_content}
                )
            messages: list[dict[str, Any]] = [
                *model_history,
            ]
            final_text = ""
            vision_context = ""
            try:
                hydra_request = user_text
                if vision_images:
                    vision_context = await self._describe_images(user_text, vision_images)
                    vision_model = self._vision_model_settings()
                    ledger_row["vision"] = {
                        "provider": (
                            "dedicated" if vision_model["dedicated"] else "base"
                        ),
                        "model": vision_model["model"],
                        "image_count": len(vision_images),
                        "observation": vision_context,
                    }
                    hydra_request = (
                        f"{user_text}\n\nVisual observation from the configured Vision model:\n"
                        f"{vision_context}"
                    )
                plan = await self._plan_turn(hydra_request, messages)
                initial_plan_mode = plan["mode"]
                approved, review_reason = await self._review_plan(hydra_request, plan)
                if not approved:
                    plan = await self._plan_turn(
                        hydra_request,
                        messages,
                        repair_reason=review_reason,
                    )
                    if initial_plan_mode == "execute" and plan["mode"] != "execute":
                        approved = False
                        review_reason = "The repaired plan dropped the required tool execution"
                    else:
                        approved, review_reason = await self._review_plan(
                            hydra_request, plan
                        )
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
                            user_text=hydra_request,
                            step=step,
                            previous_results=executions,
                            context=context,
                            device_id=device_id,
                        )
                        execution = {
                            "step_id": step["id"],
                            "intent": step["intent"],
                            "nl": step["nl"],
                            "tool_hint": step["tool_hint"],
                            "arguments": {"query": step["nl"]},
                            "result": _json_safe(result),
                        }
                        executions.append(execution)
                        ledger_row["tools"].append(
                            {
                                "name": step["tool_hint"],
                                "head": "thanatos",
                                "step_id": step["id"],
                                "arguments": {"query": step["nl"]},
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
                        user_text=hydra_request,
                        history=messages,
                        plan=plan,
                        executions=executions,
                    )
                except Exception as err:
                    if plan["mode"] != "execute":
                        raise
                    _LOGGER.warning(
                        "Hermes response failed after tool execution: %s", err
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
                        {
                            "role": "user",
                            "content": user_text,
                            "time": now,
                            "attachments": ledger_row["images"],
                            "vision_context": vision_context,
                        },
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
            "vision": ledger_row.get("vision"),
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
