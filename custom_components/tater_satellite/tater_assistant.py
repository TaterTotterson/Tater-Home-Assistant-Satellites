"""Small, Home Assistant-only Tater voice runtime.

The desktop Tater runtime intentionally is not imported here.  This module owns
the complete satellite turn when Tater mode is selected: STT, the compact Hydra
tool loop, Home Assistant device control, TTS, and a bounded execution ledger.
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

API_KEY_FIELDS = ("llm_api_key", "stt_api_key", "tts_api_key")
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
        wanted = _normalize_name(query)
        if not wanted:
            return True
        candidates = [row.entity_id, row.name, row.area, *row.aliases]
        normalized = [_normalize_name(item) for item in candidates if item]
        return any(wanted == item or wanted in item or item in wanted for item in normalized)

    def resolve(self, arguments: dict[str, Any]) -> list[HomeEntity]:
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
        if entity_ids:
            rows = [row for row in rows if row.entity_id.lower() in entity_ids]
        if domain:
            rows = [row for row in rows if row.domain == domain]
        if area:
            rows = [row for row in rows if _normalize_name(row.area) == area]
        if query and query.lower() not in {"all", "everything"}:
            rows = [row for row in rows if self._matches(row, query)]
        return rows

    async def async_call(self, arguments: dict[str, Any], context: Context | None) -> dict[str, Any]:
        operation = _text(arguments.get("operation")).lower() or "get_state"
        rows = self.resolve(arguments)
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
            data: dict[str, Any] = {"entity_id": entity_ids}
            for source, destination in parameter_map.items():
                if source in parameters:
                    data[destination] = _json_safe(parameters[source])
            await self.hass.services.async_call(
                domain,
                actual_service,
                data,
                blocking=True,
                context=context,
            )
            performed.append(
                {"domain": domain, "service": actual_service, "entity_ids": entity_ids}
            )
        return {"ok": True, "performed": performed}

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
                        "query": {"type": "string", "description": "Friendly name, alias, entity ID, or 'all'."},
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

    async def _chat(self, messages: list[dict[str, Any]], *, tools: bool = True) -> dict[str, Any]:
        settings = self.settings()
        if not settings["llm_model"]:
            raise RuntimeError("Configure the Tater LLM model first")
        if _provider_needs_key(settings["llm_base_url"]) and not settings["llm_api_key"]:
            raise RuntimeError("Configure the Tater LLM API key first")
        payload: dict[str, Any] = {
            "model": settings["llm_model"],
            "messages": messages,
            "temperature": settings["llm_temperature"],
        }
        if tools:
            payload["tools"] = [self.home.definition()]
            payload["tool_choice"] = "auto"
        endpoint = _endpoint(settings["llm_base_url"], "/v1/chat/completions")
        try:
            result = await self._post_json(endpoint, settings["llm_api_key"], payload)
        except RuntimeError as err:
            if "temperature" not in str(err).lower():
                raise
            payload.pop("temperature", None)
            result = await self._post_json(endpoint, settings["llm_api_key"], payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("The LLM returned no response choice")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("The LLM returned an invalid response message")
        return message

    async def _review_action(self, user_text: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        if arguments.get("operation") != "control":
            return True, "Read-only device operation"
        settings = self.settings()
        if not settings["hydra_astraeus_plan_review_enabled"]:
            return True, "Second plan check disabled"
        review_messages = [
            {
                "role": "system",
                "content": (
                    "You are Hydra's second plan checker. Review one proposed Home Assistant device action. "
                    "Approve only when it clearly matches the user's request and has a concrete target. "
                    "Return JSON only: {\"approved\":true|false,\"reason\":\"short reason\"}."
                ),
            },
            {"role": "user", "content": json.dumps({"request": user_text, "proposed_control_home": arguments})},
        ]
        try:
            message = await self._chat(review_messages, tools=False)
            content = _text(message.get("content"), 2000)
            match = re.search(r"\{.*\}", content, re.DOTALL)
            value = json.loads(match.group(0) if match else content)
            if isinstance(value, dict):
                return bool(value.get("approved")), _text(value.get("reason"), 300)
        except Exception as err:
            _LOGGER.warning("Hydra plan review failed; blocking action: %s", err)
            return False, f"Plan review failed: {err}"
        return False, "Plan review did not return a valid decision"

    def _system_prompt(self) -> str:
        settings = self.settings()
        return (
            f"You are {settings['assistant_name'] or 'Tater'}, a voice assistant inside Home Assistant.\n"
            f"{settings['personality']}\n"
            "You have exactly one tool: control_home. Use it only to search, read, or control the user's Home Assistant home. "
            "Never claim an action succeeded before the tool confirms it. Search when a target is ambiguous. "
            "For general knowledge or conversation, answer directly without a tool. Keep spoken replies concise.\n"
            "Available home entities in the selected scope:\n"
            f"{self.home.summary()}"
        )

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
                {"role": "system", "content": self._system_prompt()},
                *model_history,
                {"role": "user", "content": user_text},
            ]
            final_text = ""
            try:
                for _index in range(8):
                    assistant = await self._chat(messages)
                    tool_calls = assistant.get("tool_calls")
                    if not isinstance(tool_calls, list) or not tool_calls:
                        final_text = _text(assistant.get("content"), 12000)
                        break
                    messages.append(assistant)
                    for tool_call in tool_calls:
                        function = tool_call.get("function") if isinstance(tool_call, dict) else None
                        function = function if isinstance(function, dict) else {}
                        name = _text(function.get("name"))
                        try:
                            arguments = json.loads(_text(function.get("arguments")) or "{}")
                        except json.JSONDecodeError:
                            arguments = {}
                        if name != "control_home" or not isinstance(arguments, dict):
                            result = {"ok": False, "error": "Only control_home is available"}
                            approved, review_reason = False, "Unknown tool"
                        else:
                            approved, review_reason = await self._review_action(user_text, arguments)
                            result = (
                                await self.home.async_call(arguments, context)
                                if approved
                                else {"ok": False, "error": review_reason}
                            )
                        ledger_row["tools"].append(
                            {
                                "name": name or "unknown",
                                "arguments": _json_safe(arguments),
                                "approved": approved,
                                "review": review_reason,
                                "result": _json_safe(result),
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": _text(tool_call.get("id")) or secrets.token_hex(4),
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                if not final_text and settings["hydra_auto_continue_incomplete_final_enabled"]:
                    messages.append({"role": "user", "content": "Finish with a short final spoken response."})
                    final_text = _text((await self._chat(messages, tools=False)).get("content"), 12000)
                if not final_text:
                    final_text = "I couldn't complete that request."
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
