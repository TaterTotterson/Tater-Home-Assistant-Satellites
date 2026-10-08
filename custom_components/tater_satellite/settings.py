"""Firmware settings schema and validation."""

from __future__ import annotations

import copy
import re
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "wake_engine": "micro_wake_word",
    "wake_detector_mode": "dual",
    "wake_mww_enabled": True,
    "wake_oww_enabled": True,
    "wake_word": "hey_tater",
    "wake_word_url": "",
    "wake_model_revision": "",
    "wake_model_asset_id": "",
    "oww_wake_word": "hey_tater",
    "oww_wake_word_url": "",
    "oww_model_revision": "",
    "wake_sensitivity": "normal",
    "wake_environment": "balanced",
    "wake_threshold": 0.97,
    "wake_sliding_window": 5,
    "wake_verifier_mode": "off",
    "wake_verifier_phrase": "",
    "wake_verifier_phrase_url": "",
    "wake_verifier_threshold": 0.85,
    "wake_verifier_window_ms": 1000,
    "wake_verifier_timeout_ms": 500,
    "capture_wake_audio": False,
    "capture_close_misses": False,
    "close_miss_threshold": 0.78,
    "trainer_app_url": "http://trainer.local:8789",
    "wake_sound_enabled": False,
    "wake_sound": "no_sound",
    "wake_sound_url": "",
    "wake_sound_asset_id": "",
    "aec_enabled": False,
    "aec_strength_percent": 70,
    "aec_delay_ms": 85,
    "continued_chat": True,
    "barge_in_enabled": False,
    "volume_percent": 80,
    "muted": False,
    "screen_brightness": 80,
    "screen_night_mode_enabled": False,
    "screen_night_brightness": 10,
    "screen_night_start": "22:00",
    "screen_night_end": "07:00",
    "led_brightness": 80,
    "led_color": "#ff5a1f",
    "led_listening_animation": "directional",
    "led_thinking_animation": "sparkle",
    "led_tool_call_animation": "ping_pong",
    "led_replying_animation": "voice_ring",
    "led_music_animation": "audio_glow",
    "logging_level": "info",
}

FIRMWARE_SETTING_KEYS = {
    "wake_engine",
    "wake_mww_enabled",
    "wake_oww_enabled",
    "wake_word",
    "wake_word_url",
    "wake_model_revision",
    "oww_wake_word",
    "oww_wake_word_url",
    "oww_model_revision",
    "wake_sensitivity",
    "wake_environment",
    "wake_threshold",
    "wake_sliding_window",
    "wake_verifier_mode",
    "wake_verifier_window_ms",
    "wake_verifier_timeout_ms",
    "capture_wake_audio",
    "capture_close_misses",
    "close_miss_threshold",
    "trainer_app_url",
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
    "screen_brightness",
    "screen_night_mode_enabled",
    "screen_night_brightness",
    "screen_night_start",
    "screen_night_end",
    "led_brightness",
    "led_color",
    "led_listening_animation",
    "led_thinking_animation",
    "led_tool_call_animation",
    "led_replying_animation",
    "led_music_animation",
    "logging_level",
}

WAKE_WORD_OPTIONS = [
    {"value": "hey_tater", "label": "Hey Tater (built in)"},
    {"value": "custom_url", "label": "Custom model"},
]

WAKE_WORD_SOURCE_OPTIONS = [
    {"value": "hey_tater", "label": "Hey Tater (built in)"},
    {"value": "catalog", "label": "Tater Wake Word Catalog"},
    {"value": "custom_url", "label": "Custom model"},
]

OWW_WORD_SOURCE_OPTIONS = [
    {"value": "hey_tater", "label": "Hey Tater (built in)"},
    {"value": "custom_url", "label": "Custom Tater wake bundle"},
]

WAKE_DETECTOR_MODES = {"mww", "oww", "dual"}
WAKE_FAMILIES = {"mww", "echo"}
WAKE_FAMILY_SETTING_KEYS = {
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

WAKE_SOUND_OPTIONS = [
    {"value": "no_sound", "label": "No sound"},
    {"value": "default", "label": "Default"},
    {"value": "blip2", "label": "Blip 2"},
    {"value": "message-notification-4", "label": "Message Notification 4"},
    {"value": "notification-ding", "label": "Notification Ding"},
    {"value": "notification-squeak", "label": "Notification Squeak"},
    {"value": "phone-chime", "label": "Phone Chime"},
    {"value": "pop-up-sound", "label": "Pop Up Sound"},
    {"value": "short-definite-fart", "label": "Short Definite Fart"},
    {
        "value": "star_treck_communications_start_transmission",
        "label": "Star Trek Communications",
    },
    {
        "value": "star_treck_computer_work_beep",
        "label": "Star Trek Computer Work Beep",
    },
    {"value": "tater_notify_digital_blip", "label": "Tater Digital Blip"},
    {
        "value": "turning-off-microphone-percussion-1",
        "label": "Microphone Percussion",
    },
    {"value": "wake_word_triggered", "label": "Wake Word Triggered"},
    {"value": "waterdrop", "label": "Waterdrop"},
    {"value": "custom", "label": "Custom WAV"},
]

ANIMATION_OPTIONS = [
    {"value": "directional", "label": "Directional Listening"},
    {"value": "sparkle", "label": "Sparkle"},
    {"value": "ping_pong", "label": "Ping Pong"},
    {"value": "audio_glow", "label": "Audio Glow"},
    {"value": "voice_ring", "label": "Voice Ring"},
    {"value": "spinner", "label": "Spinner"},
    {"value": "orbit", "label": "Orbit"},
    {"value": "pulse", "label": "Pulse"},
    {"value": "breathe", "label": "Breathe"},
    {"value": "comet", "label": "Comet"},
    {"value": "dual_comet", "label": "Dual Comet"},
    {"value": "scanner", "label": "Scanner"},
    {"value": "ripple", "label": "Ripple"},
    {"value": "heartbeat", "label": "Heartbeat"},
    {"value": "theater", "label": "Theater Chase"},
    {"value": "wave", "label": "Wave"},
    {"value": "shimmer", "label": "Shimmer"},
    {"value": "twinkle", "label": "Twinkle"},
    {"value": "equalizer", "label": "Equalizer"},
    {"value": "solid", "label": "Solid"},
]


def _animation_options(*preferred: str, include_audio_glow: bool = False):
    """Return Tater's ordered animation choices with an explicit off option."""
    labels = {str(row["value"]): str(row["label"]) for row in ANIMATION_OPTIONS}
    ordered: list[dict[str, str]] = [{"value": "off", "label": "No Animation"}]
    used = {"off"}
    for value in preferred:
        if value in labels and value not in used:
            ordered.append({"value": value, "label": labels[value]})
            used.add(value)
    for value, label in labels.items():
        if value in used or (value == "audio_glow" and not include_audio_glow):
            continue
        ordered.append({"value": value, "label": label})
        used.add(value)
    return ordered


LISTENING_ANIMATION_OPTIONS = _animation_options(
    "directional", "pulse", "spinner", "breathe"
)
THINKING_ANIMATION_OPTIONS = _animation_options(
    "sparkle", "shimmer", "twinkle", "breathe"
)
TOOL_CALL_ANIMATION_OPTIONS = _animation_options(
    "ping_pong", "scanner", "orbit", "comet"
)
REPLYING_ANIMATION_OPTIONS = _animation_options(
    "audio_glow",
    "voice_ring",
    "wave",
    "ripple",
    "equalizer",
    include_audio_glow=True,
)
MUSIC_ANIMATION_OPTIONS = [
    {"value": "off", "label": "No Animation"},
    {"value": "audio_glow", "label": "Audio Glow"},
    {"value": "music_pulse", "label": "Beat Pulse"},
    {"value": "music_bars", "label": "Level Bars"},
    {"value": "music_orbit", "label": "Reactive Orbit"},
    {"value": "music_wave", "label": "Reactive Wave"},
]

WAKE_SENSITIVITY_ADJUSTMENTS = {
    "conservative": 0.02,
    "normal": 0.0,
    "high": -0.05,
}

SETTINGS_SCHEMA: list[dict[str, Any]] = [
    {
        "section": "wake",
        "title": "Wake Word",
        "description": "On-device wake model and false-wake tuning.",
        "fields": [
            {
                "key": "wake_engine",
                "label": "Wake engine",
                "type": "select",
                "options": [
                    {"value": "micro_wake_word", "label": "microWakeWord"},
                    {"value": "button", "label": "Button only"},
                    {"value": "off", "label": "Off"},
                ],
            },
            {
                "key": "wake_detector_mode",
                "label": "Wake detection mode",
                "type": "select",
                "wake_families": ["echo"],
                "options": [
                    {"value": "mww", "label": "microWakeWord"},
                    {"value": "oww", "label": "openWakeWord"},
                    {"value": "dual", "label": "Dual Wake Word"},
                ],
                "description": (
                    "Use either detector alone, or require both detectors to "
                    "agree before opening the microphone."
                ),
            },
            {
                "key": "wake_word",
                "label": "Wake word",
                "type": "select",
                "detector_modes": ["mww"],
                "options": WAKE_WORD_SOURCE_OPTIONS,
            },
            {
                "key": "wake_word_catalog_url",
                "label": "Wake Word Catalog",
                "type": "select",
                "detector_modes": ["mww"],
                "options": [],
                "show_when": {"key": "wake_word", "equals": "catalog"},
                "description": (
                    "Choose a versioned model from the official Tater "
                    "Wake Word Catalog."
                ),
            },
            {
                "key": "wake_model_asset_id",
                "label": "Uploaded wake model",
                "type": "wake_model_asset",
                "detector_modes": ["mww"],
                "show_when": {"key": "wake_word", "equals": "custom_url"},
            },
            {
                "key": "wake_word_url",
                "label": "External wake JSON or TFLite URL",
                "type": "url",
                "detector_modes": ["mww"],
                "show_when": {"key": "wake_word", "equals": "custom_url"},
                "placeholder": "https://example.local/wake_word.json",
            },
            {
                "key": "oww_wake_word",
                "label": "openWakeWord model",
                "type": "select",
                "wake_families": ["echo"],
                "detector_modes": ["oww", "dual"],
                "options": OWW_WORD_SOURCE_OPTIONS,
                "description": (
                    "Use the built-in Hey Tater model or a matching dual-model "
                    "bundle produced by a Tater Wake Word Trainer."
                ),
            },
            {
                "key": "oww_wake_word_url",
                "label": "Tater wake-bundle URL",
                "type": "url",
                "wake_families": ["echo"],
                "detector_modes": ["oww", "dual"],
                "show_when": {"key": "oww_wake_word", "equals": "custom_url"},
                "placeholder": (
                    "http://trainer.local:8789/api/trained_wake_words/"
                    "hey_tater.wake-bundle.json"
                ),
            },
            {
                "key": "wake_sensitivity",
                "label": "Wake sensitivity",
                "type": "select",
                "detector_modes": ["mww", "dual"],
                "options": [
                    {"value": "conservative", "label": "Conservative"},
                    {"value": "normal", "label": "Normal"},
                    {"value": "high", "label": "High"},
                ],
            },
            {
                "key": "wake_environment",
                "label": "Wake environment",
                "type": "select",
                "detector_modes": ["mww", "dual"],
                "options": [
                    {"value": "balanced", "label": "Balanced"},
                    {"value": "tv_nearby", "label": "TV Nearby"},
                    {"value": "strict", "label": "Strict"},
                    {"value": "far_field", "label": "Far Field / Quiet Room"},
                ],
            },
            {
                "key": "wake_threshold",
                "label": "Base wake threshold",
                "type": "number",
                "detector_modes": ["mww", "dual"],
                "min": 0.01,
                "max": 0.99,
                "step": 0.01,
            },
            {
                "key": "wake_sliding_window",
                "label": "Sliding window",
                "type": "number",
                "detector_modes": ["mww", "dual"],
                "min": 1,
                "max": 10,
                "step": 1,
            },
        ],
    },
    {
        "section": "verifier",
        "title": "Verification Mode",
        "description": (
            "Choose whether Home Assistant observes or blocks wake-word "
            "transcript mismatches."
        ),
        "scopes": ["global"],
        "fields": [
            {
                "key": "wake_verifier_mode",
                "label": "STT wake check",
                "type": "select",
                "options": [
                    {"value": "off", "label": "Disabled"},
                    {"value": "observe", "label": "Observe"},
                    {"value": "enforce", "label": "Enabled"},
                ],
            },
        ],
    },
    {
        "section": "wake_sound",
        "title": "Wake Sound",
        "description": "Choose the acknowledgement sound played after a wake word.",
        "fields": [
            {
                "key": "wake_sound_enabled",
                "label": "Play wake sound",
                "type": "boolean",
            },
            {
                "key": "wake_sound",
                "label": "Wake sound",
                "type": "select",
                "options": WAKE_SOUND_OPTIONS,
            },
            {
                "key": "wake_sound_asset_id",
                "label": "Uploaded custom WAV",
                "type": "wake_sound_asset",
                "show_when": {"key": "wake_sound", "equals": "custom"},
            },
            {
                "key": "wake_sound_url",
                "label": "External custom WAV URL",
                "type": "url",
                "show_when": {"key": "wake_sound", "equals": "custom"},
            },
        ],
    },
    {
        "section": "feedback",
        "title": "Trainer Feedback",
        "description": "Choose what wake audio satellites send back to the trainer.",
        "fields": [
            {
                "key": "capture_wake_audio",
                "label": "Send good wakes to trainer",
                "type": "boolean",
            },
            {
                "key": "capture_close_misses",
                "label": "Send close misses to trainer",
                "type": "boolean",
            },
            {
                "key": "close_miss_threshold",
                "label": "Close-miss threshold",
                "type": "number",
                "min": 0.01,
                "max": 0.99,
                "step": 0.01,
            },
            {
                "key": "trainer_app_url",
                "label": "Trainer URL",
                "type": "url",
                "placeholder": "http://trainer.local:8789",
            },
        ],
    },
    {
        "section": "audio",
        "title": "Audio & Conversation",
        "description": "Speaker, microphone, echo cancellation, and follow-up behavior.",
        "fields": [
            {"key": "muted", "label": "Mute microphone", "type": "boolean"},
            {
                "key": "continued_chat",
                "label": "Continued conversation",
                "type": "boolean",
            },
            {
                "key": "barge_in_enabled",
                "label": "Wake-word barge-in during replies",
                "type": "boolean",
            },
            {
                "key": "aec_enabled",
                "label": "Acoustic echo cancellation",
                "type": "boolean",
            },
            {
                "key": "aec_strength_percent",
                "label": "AEC strength",
                "type": "number",
                "min": 0,
                "max": 100,
                "step": 1,
                "show_when": {"key": "aec_enabled", "equals": True},
            },
            {
                "key": "aec_delay_ms",
                "label": "AEC delay (ms)",
                "type": "number",
                "min": 0,
                "max": 220,
                "step": 5,
                "show_when": {"key": "aec_enabled", "equals": True},
            },
        ],
    },
    {
        "section": "display",
        "title": "S3 Box Display",
        "description": (
            "Set this S3 Box screen brightness and optionally dim it on a "
            "daily local-time schedule."
        ),
        "scopes": ["device"],
        "include_boards": ["s3_box"],
        "fields": [
            {
                "key": "screen_brightness",
                "label": "Screen brightness",
                "type": "number",
                "min": 0,
                "max": 100,
                "step": 1,
            },
            {
                "key": "screen_night_mode_enabled",
                "label": "Scheduled night dimming",
                "type": "boolean",
            },
            {
                "key": "screen_night_start",
                "label": "Dim at",
                "type": "time",
                "show_when": {
                    "key": "screen_night_mode_enabled",
                    "equals": True,
                },
            },
            {
                "key": "screen_night_end",
                "label": "Restore at",
                "type": "time",
                "show_when": {
                    "key": "screen_night_mode_enabled",
                    "equals": True,
                },
            },
            {
                "key": "screen_night_brightness",
                "label": "Night brightness",
                "type": "number",
                "min": 0,
                "max": 100,
                "step": 1,
                "show_when": {
                    "key": "screen_night_mode_enabled",
                    "equals": True,
                },
            },
        ],
    },
    {
        "section": "led",
        "title": "LEDs",
        "description": "Brightness, voice color, and animation for each stage.",
        "scopes": ["device"],
        "exclude_boards": ["s3_box"],
        "fields": [
            {
                "key": "led_brightness",
                "label": "LED brightness",
                "type": "number",
                "min": 0,
                "max": 100,
                "step": 1,
            },
            {"key": "led_color", "label": "Voice LED color", "type": "color"},
            {
                "key": "led_listening_animation",
                "label": "Listening animation",
                "type": "select",
                "options": LISTENING_ANIMATION_OPTIONS,
            },
            {
                "key": "led_thinking_animation",
                "label": "Thinking animation",
                "type": "select",
                "options": THINKING_ANIMATION_OPTIONS,
            },
            {
                "key": "led_tool_call_animation",
                "label": "Tool-call animation",
                "type": "select",
                "options": TOOL_CALL_ANIMATION_OPTIONS,
            },
            {
                "key": "led_replying_animation",
                "label": "Replying animation",
                "type": "select",
                "options": REPLYING_ANIMATION_OPTIONS,
            },
            {
                "key": "led_music_animation",
                "label": "Music animation",
                "type": "select",
                "include_boards": ["biscuit"],
                "options": MUSIC_ANIMATION_OPTIONS,
                "description": (
                    "Audio-reactive Biscuit ring animation for music playback, "
                    "including Sendspin."
                ),
            },
        ],
    },
    {
        "section": "diagnostics",
        "title": "Diagnostics",
        "description": "Device logging sent over the satellite connection.",
        "fields": [
            {
                "key": "logging_level",
                "label": "Firmware logging",
                "type": "select",
                "options": [
                    {"value": "error", "label": "Error"},
                    {"value": "warning", "label": "Warning"},
                    {"value": "info", "label": "Info"},
                    {"value": "debug", "label": "Debug"},
                ],
            }
        ],
    },
]

_ALLOWED = {
    "wake_engine": {"micro_wake_word", "button", "off"},
    "wake_detector_mode": WAKE_DETECTOR_MODES,
    "wake_word": {row["value"] for row in WAKE_WORD_OPTIONS},
    "oww_wake_word": {row["value"] for row in OWW_WORD_SOURCE_OPTIONS},
    "wake_sensitivity": {"conservative", "normal", "high"},
    "wake_environment": {"balanced", "tv_nearby", "strict", "far_field"},
    "wake_verifier_mode": {"off", "observe", "enforce"},
    "wake_sound": {row["value"] for row in WAKE_SOUND_OPTIONS},
    "logging_level": {"error", "warning", "info", "debug"},
    "led_listening_animation": {
        row["value"] for row in LISTENING_ANIMATION_OPTIONS
    },
    "led_thinking_animation": {row["value"] for row in THINKING_ANIMATION_OPTIONS},
    "led_tool_call_animation": {
        row["value"] for row in TOOL_CALL_ANIMATION_OPTIONS
    },
    "led_replying_animation": {row["value"] for row in REPLYING_ANIMATION_OPTIONS},
    "led_music_animation": {row["value"] for row in MUSIC_ANIMATION_OPTIONS},
}
_BOOL_KEYS = {
    "wake_mww_enabled",
    "wake_oww_enabled",
    "capture_wake_audio",
    "capture_close_misses",
    "wake_sound_enabled",
    "aec_enabled",
    "continued_chat",
    "barge_in_enabled",
    "muted",
    "screen_night_mode_enabled",
}
_INT_RANGES = {
    "wake_sliding_window": (1, 10),
    "wake_verifier_window_ms": (500, 2000),
    "wake_verifier_timeout_ms": (100, 2000),
    "aec_strength_percent": (0, 100),
    "aec_delay_ms": (0, 220),
    "volume_percent": (0, 100),
    "screen_brightness": (0, 100),
    "screen_night_brightness": (0, 100),
    "led_brightness": (0, 100),
}
_FLOAT_RANGES = {
    "wake_threshold": (0.01, 0.99),
    "wake_verifier_threshold": (0.5, 1.0),
    "close_miss_threshold": (0.01, 0.99),
}
_TEXT_LIMITS = {
    "wake_word_url": 255,
    "wake_model_revision": 64,
    "wake_model_asset_id": 128,
    "oww_wake_word_url": 255,
    "oww_model_revision": 64,
    "wake_verifier_phrase": 120,
    "wake_verifier_phrase_url": 255,
    "trainer_app_url": 127,
    "wake_sound_url": 191,
    "wake_sound_asset_id": 128,
}
_TIME_KEYS = {
    "screen_night_start",
    "screen_night_end",
}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def board_supports_led_settings(board: Any) -> bool:
    """Return whether Tater exposes configurable LED settings for a board."""
    token = str(board or "").strip().lower().replace("_", "-").replace(" ", "-")
    compact = token.replace("-", "")
    return token not in {
        "s3-box",
        "s3-box-3",
        "esp32-s3-box",
        "esp32-s3-box-3",
    } and compact not in {
        "s3box",
        "s3box3",
        "esp32s3box",
        "esp32s3box3",
    }


def board_supports_music_led_settings(board: Any) -> bool:
    """Return whether a board supports the audio-reactive music LED setting."""
    token = str(board or "").strip().lower().replace("_", "-").replace(" ", "-")
    compact = token.replace("-", "")
    return token in {"biscuit", "echo-dot-2", "echo-dot-2nd-gen"} or compact in {
        "biscuit",
        "echodot2",
        "echodot2ndgen",
    }


def board_supports_screen_settings(board: Any) -> bool:
    """Return whether a board has the configurable S3 Box display."""
    token = str(board or "").strip().lower().replace("_", "-").replace(" ", "-")
    compact = token.replace("-", "")
    return token in {
        "s3-box",
        "s3-box-3",
        "esp32-s3-box",
        "esp32-s3-box-3",
    } or compact in {
        "s3box",
        "s3box3",
        "esp32s3box",
        "esp32s3box3",
    }


def _time_value(value: Any, default: str) -> str:
    """Return a normalized 24-hour HH:MM value."""
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        return default
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        return default
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return default
    return f"{hour:02d}:{minute:02d}"


def _boolean(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value or "").strip().lower()
    if token in {"1", "true", "yes", "on", "enabled"}:
        return True
    if token in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return round(max(minimum, min(maximum, result)), 3)


def normalize_settings(
    values: dict[str, Any] | None,
    *,
    base: dict[str, Any] | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    """Validate settings and return normalized values."""
    source = values if isinstance(values, dict) else {}
    current = copy.deepcopy(base if isinstance(base, dict) else DEFAULT_SETTINGS)
    result: dict[str, Any] = {} if partial else current
    keys = source.keys() if partial else DEFAULT_SETTINGS.keys()

    for key in keys:
        if key not in DEFAULT_SETTINGS or key not in source:
            continue
        value = source.get(key)
        default = current.get(key, DEFAULT_SETTINGS[key])
        if key in _ALLOWED:
            token = str(value or "").strip().lower()
            if key != "wake_sound":
                token = token.replace("-", "_")
            result[key] = token if token in _ALLOWED[key] else default
        elif key in _BOOL_KEYS:
            result[key] = _boolean(value, bool(default))
        elif key in _INT_RANGES:
            minimum, maximum = _INT_RANGES[key]
            result[key] = _bounded_int(value, int(default), minimum, maximum)
        elif key in _FLOAT_RANGES:
            minimum, maximum = _FLOAT_RANGES[key]
            result[key] = _bounded_float(value, float(default), minimum, maximum)
        elif key == "led_color":
            color = str(value or "").strip().lower()
            result[key] = color if _HEX_COLOR.fullmatch(color) else default
        elif key in _TIME_KEYS:
            result[key] = _time_value(value, str(default))
        elif key in _TEXT_LIMITS:
            result[key] = str(value or "").strip()[: _TEXT_LIMITS[key]]

    if not partial:
        if result.get("wake_word") != "custom_url":
            result["wake_word_url"] = ""
            result["wake_model_revision"] = ""
            result["wake_model_asset_id"] = ""
        if result.get("oww_wake_word") != "custom_url":
            result["oww_wake_word_url"] = ""
            result["oww_model_revision"] = ""
        if result.get("wake_sound") != "custom":
            result["wake_sound_url"] = ""
            result["wake_sound_asset_id"] = ""

    if "wake_detector_mode" in result or not partial:
        mode = str(result.get("wake_detector_mode") or "dual")
        if mode not in WAKE_DETECTOR_MODES:
            mode = "dual"
        result["wake_detector_mode"] = mode
        result["wake_mww_enabled"] = mode in {"mww", "dual"}
        result["wake_oww_enabled"] = mode in {"oww", "dual"}

    return result


def wake_family_for(
    *, capabilities: dict[str, Any] | None = None, board: Any = ""
) -> str:
    """Return the shared wake profile family for one satellite."""
    caps = capabilities if isinstance(capabilities, dict) else {}
    if any(
        _boolean(caps.get(key), False)
        for key in ("openwakeword", "wake_detector_selection", "dual_wake_confirmation")
    ):
        return "echo"
    token = str(board or "").strip().lower().replace("_", "-")
    return "echo" if token in {"biscuit", "checkers", "rook"} else "mww"


def normalize_wake_family_settings(
    family: Any,
    values: dict[str, Any] | None,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize the wake-only settings persisted for a satellite family."""
    token = str(family or "").strip().lower()
    if token not in WAKE_FAMILIES:
        raise ValueError(f"Unsupported wake family: {family}")
    source = {
        key: value
        for key, value in (values or {}).items()
        if key in WAKE_FAMILY_SETTING_KEYS
    }
    current = normalize_settings(source, base=base)
    mode = (
        "mww"
        if token == "mww"
        else str(current.get("wake_detector_mode") or "dual")
    )
    if mode not in WAKE_DETECTOR_MODES:
        mode = "dual"
    current["wake_detector_mode"] = mode
    current["wake_mww_enabled"] = mode in {"mww", "dual"}
    current["wake_oww_enabled"] = mode in {"oww", "dual"}
    return {key: current[key] for key in WAKE_FAMILY_SETTING_KEYS if key in current}


def merged_settings(
    global_settings: dict[str, Any] | None,
    overrides: dict[str, Any] | None,
    wake_family_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge normalized global settings with per-device overrides."""
    global_values = normalize_settings(global_settings)
    family_values = normalize_settings(
        wake_family_settings,
        base=global_values,
        partial=True,
    )
    base_values = normalize_settings({**global_values, **family_values})
    override_values = normalize_settings(overrides, base=base_values, partial=True)
    return normalize_settings({**base_values, **override_values})


def firmware_payload(
    settings: dict[str, Any],
    *,
    board: Any = "",
    capabilities: dict[str, Any] | None = None,
    local_time_seconds: int | None = None,
) -> dict[str, Any]:
    """Return only values understood by the firmware."""
    normalized = normalize_settings(settings)
    payload = {
        key: value for key, value in normalized.items() if key in FIRMWARE_SETTING_KEYS
    }
    if board_supports_screen_settings(board):
        if local_time_seconds is not None:
            payload["screen_local_time_seconds"] = max(
                0,
                min((24 * 60 * 60) - 1, int(local_time_seconds)),
            )
    else:
        for key in (
            "screen_brightness",
            "screen_night_mode_enabled",
            "screen_night_brightness",
            "screen_night_start",
            "screen_night_end",
        ):
            payload.pop(key, None)
    if not board_supports_music_led_settings(board):
        payload.pop("led_music_animation", None)
    base_threshold = float(normalized["wake_threshold"])
    adjustment = WAKE_SENSITIVITY_ADJUSTMENTS.get(
        str(normalized["wake_sensitivity"]), 0.0
    )
    payload["wake_threshold"] = round(
        max(0.01, min(0.99, base_threshold + adjustment)), 3
    )
    family = wake_family_for(capabilities=capabilities, board=board)
    if family == "mww":
        payload["wake_mww_enabled"] = True
        for key in (
            "wake_oww_enabled",
            "oww_wake_word",
            "oww_wake_word_url",
            "oww_model_revision",
        ):
            payload.pop(key, None)
    elif (
        payload.get("wake_mww_enabled")
        and payload.get("wake_oww_enabled")
        and payload.get("oww_wake_word") == "custom_url"
        and payload.get("oww_wake_word_url")
    ):
        # Echo firmware treats one validated trainer bundle as the authority
        # for both detectors in Dual mode.
        payload["oww_wake_word"] = "paired_bundle"
    return payload
