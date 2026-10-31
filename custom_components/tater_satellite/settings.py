"""Firmware settings schema and validation."""

from __future__ import annotations

import copy
import re
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "wake_engine": "micro_wake_word",
    "wake_detector_mode": "mww_oww",
    "wake_mww_enabled": True,
    "wake_oww_enabled": True,
    "wake_nww_enabled": False,
    "wake_word": "hey_tater",
    "wake_word_url": "",
    "wake_model_revision": "",
    "wake_model_asset_id": "",
    "oww_wake_word": "hey_tater",
    "oww_wake_word_url": "",
    "oww_model_revision": "",
    "nww_wake_word": "hey_tater",
    "nww_wake_word_url": "",
    "nww_model_revision": "",
    "nww_architecture": "cnn",
    "nww_available_architectures": "cnn,gru",
    "wake_profile_threshold": 0.98,
    "wake_profile_sliding_window": 5,
    "wake_profile_close_miss_threshold": 0.81,
    "oww_profile_threshold": 0.99,
    "oww_profile_patience": 3,
    "oww_profile_confirmation_threshold": 0.92,
    "oww_profile_confirmation_patience": 3,
    "nww_profile_threshold": 0.99,
    "nww_profile_patience": 3,
    "nww_cnn_profile_threshold": 0.99,
    "nww_cnn_profile_patience": 3,
    "nww_gru_profile_threshold": 0.99,
    "nww_gru_profile_patience": 3,
    "mww_tuning_override_enabled": False,
    "mww_threshold_override": 0.98,
    "mww_sliding_window_override": 5,
    "oww_tuning_override_enabled": False,
    "oww_threshold_override": 0.99,
    "oww_patience_override": 3,
    "nww_tuning_override_enabled": False,
    "nww_threshold_override": 0.99,
    "nww_patience_override": 3,
    "wake_sensitivity": "normal",
    "wake_environment": "balanced",
    "wake_threshold": 0.98,
    "wake_sliding_window": 5,
    "oww_threshold": 0.99,
    "oww_patience": 3,
    "nww_threshold": 0.99,
    "nww_patience": 3,
    "wake_verifier_mode": "off",
    "wake_verifier_phrase": "",
    "wake_verifier_phrase_url": "",
    "wake_verifier_threshold": 0.85,
    "wake_verifier_window_ms": 1000,
    "wake_verifier_timeout_ms": 500,
    "capture_wake_audio": False,
    "capture_close_misses": False,
    "close_miss_threshold": 0.81,
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
    "audio_output_mode": "auto",
    "screen_brightness": 80,
    "screen_auto_brightness_enabled": False,
    "screen_auto_brightness_minimum": 12,
    "screen_night_mode_enabled": False,
    "screen_night_brightness": 10,
    "screen_night_start": "22:00",
    "screen_night_end": "07:00",
    "screen_night_display": "red_clock",
    "screen_clock_format": "12h",
    "screen_climate_entity": "",
    "screen_room_temperature_entities": "",
    "led_brightness": 80,
    "led_color": "#ff5a1f",
    "led_listening_animation": "directional",
    "led_thinking_animation": "sparkle",
    "led_tool_call_animation": "ping_pong",
    "led_replying_animation": "voice_ring",
    "led_music_animation": "music_bars",
    "logging_level": "info",
}

ECHO_SCREEN_DEFAULTS: dict[str, Any] = {
    "screen_brightness": 35,
    "screen_auto_brightness_enabled": False,
    "screen_auto_brightness_minimum": 12,
    "screen_night_mode_enabled": False,
    "screen_night_brightness": 3,
    "screen_night_start": "22:00",
    "screen_night_end": "07:00",
    "screen_night_display": "red_clock",
    "screen_clock_format": "12h",
}

FIRMWARE_SETTING_KEYS = {
    "wake_engine",
    "wake_mww_enabled",
    "wake_oww_enabled",
    "wake_nww_enabled",
    "wake_word",
    "wake_word_url",
    "wake_model_revision",
    "oww_wake_word",
    "oww_wake_word_url",
    "oww_model_revision",
    "nww_wake_word",
    "nww_wake_word_url",
    "nww_model_revision",
    "nww_architecture",
    "wake_sensitivity",
    "wake_environment",
    "wake_threshold",
    "wake_sliding_window",
    "oww_threshold",
    "oww_patience",
    "nww_threshold",
    "nww_patience",
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
    "audio_output_mode",
    "screen_brightness",
    "screen_auto_brightness_enabled",
    "screen_auto_brightness_minimum",
    "screen_night_mode_enabled",
    "screen_night_brightness",
    "screen_night_start",
    "screen_night_end",
    "screen_night_display",
    "screen_clock_format",
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
    {"value": "catalog", "label": "Tater Wake Word Catalog"},
    {"value": "custom_url", "label": "Custom Tater wake bundle"},
]

WAKE_DETECTOR_MODES = {"mww", "oww", "nww", "mww_oww", "mww_nww"}
WAKE_FAMILIES = {"mww", "echo"}
WAKE_FAMILY_SETTING_KEYS = {
    "wake_engine",
    "wake_detector_mode",
    "wake_mww_enabled",
    "wake_oww_enabled",
    "wake_nww_enabled",
    "wake_word",
    "wake_word_url",
    "wake_model_revision",
    "wake_model_asset_id",
    "oww_wake_word",
    "oww_wake_word_url",
    "oww_model_revision",
    "nww_wake_word",
    "nww_wake_word_url",
    "nww_model_revision",
    "nww_architecture",
    "nww_available_architectures",
    "wake_profile_threshold",
    "wake_profile_sliding_window",
    "wake_profile_close_miss_threshold",
    "oww_profile_threshold",
    "oww_profile_patience",
    "oww_profile_confirmation_threshold",
    "oww_profile_confirmation_patience",
    "nww_profile_threshold",
    "nww_profile_patience",
    "nww_cnn_profile_threshold",
    "nww_cnn_profile_patience",
    "nww_gru_profile_threshold",
    "nww_gru_profile_patience",
    "mww_tuning_override_enabled",
    "mww_threshold_override",
    "mww_sliding_window_override",
    "oww_tuning_override_enabled",
    "oww_threshold_override",
    "oww_patience_override",
    "nww_tuning_override_enabled",
    "nww_threshold_override",
    "nww_patience_override",
}
WAKE_DEVICE_SETTING_KEYS = {"wake_sensitivity", "wake_environment"}
SHARED_WAKE_MODEL_SETTING_KEYS = WAKE_FAMILY_SETTING_KEYS - WAKE_DEVICE_SETTING_KEYS

# Keep each settings form on the same explicit boundary used by Tater. These
# are API allowlists, not merely UI groupings: unrelated draft fields must not
# be able to change wake, verifier, trainer, or voice-default state.
VOICE_DEFAULT_SETTING_KEYS = {
    "wake_sound_enabled",
    "wake_sound",
    "wake_sound_url",
    "wake_sound_asset_id",
    "muted",
    "continued_chat",
    "barge_in_enabled",
    "aec_enabled",
    "aec_strength_percent",
    "aec_delay_ms",
    "logging_level",
}
TRAINER_SETTING_KEYS = {
    "capture_wake_audio",
    "capture_close_misses",
    "close_miss_threshold",
    "trainer_app_url",
}
WAKE_VERIFIER_SETTING_KEYS = {"wake_verifier_mode"}

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
                "scopes": ["wake"],
                "options": [
                    {
                        "value": "micro_wake_word",
                        "label": "On-device wake detection",
                    },
                    {"value": "button", "label": "Button only"},
                    {"value": "off", "label": "Off"},
                ],
            },
            {
                "key": "wake_detector_mode",
                "label": "Wake detection mode",
                "type": "select",
                "scopes": ["wake"],
                "wake_families": ["echo"],
                "options": [
                    {"value": "mww", "label": "MWW", "group": "single"},
                    {"value": "oww", "label": "OWW", "group": "single"},
                    {"value": "nww", "label": "NWW", "group": "single"},
                    {"value": "mww_oww", "label": "MWW + OWW", "group": "dual"},
                    {"value": "mww_nww", "label": "MWW + NWW", "group": "dual"},
                ],
                "description": (
                    "Single modes use one detector on capable satellites. Dual "
                    "modes require MWW plus its companion. ESP32 and other "
                    "MWW-only devices always keep the bundle's MWW fallback."
                ),
            },
            {
                "key": "wake_word",
                "label": "Wake word",
                "type": "select",
                "scopes": ["wake"],
                "detector_modes": ["mww"],
                "options": WAKE_WORD_SOURCE_OPTIONS,
            },
            {
                "key": "wake_word_catalog_url",
                "label": "Wake Word Catalog",
                "type": "select",
                "scopes": ["wake"],
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
                "scopes": ["wake"],
                "detector_modes": ["mww"],
                "show_when": {"key": "wake_word", "equals": "custom_url"},
            },
            {
                "key": "wake_word_url",
                "label": "Wake bundle or MWW JSON URL",
                "type": "url",
                "scopes": ["wake"],
                "detector_modes": ["mww"],
                "show_when": {"key": "wake_word", "equals": "custom_url"},
                "placeholder": "https://example.local/wake_word.wake-bundle.json",
                "description": (
                    "Use the trainer's canonical wake bundle or a simple "
                    "ESPHome microWakeWord JSON package."
                ),
            },
            {
                "key": "oww_wake_word",
                "label": "Wake word bundle",
                "type": "select",
                "scopes": ["wake"],
                "wake_families": ["echo"],
                "detector_modes": ["oww", "nww", "mww_oww", "mww_nww"],
                "options": OWW_WORD_SOURCE_OPTIONS,
                "description": (
                    "One bundle supplies matching MWW, OWW, and NWW models. The "
                    "bridge sends only the models each satellite can run."
                ),
            },
            {
                "key": "oww_wake_word_catalog_url",
                "label": "Wake Word Catalog",
                "type": "select",
                "scopes": ["wake"],
                "wake_families": ["echo"],
                "detector_modes": ["oww", "nww", "mww_oww", "mww_nww"],
                "options": [],
                "show_when": {"key": "oww_wake_word", "equals": "catalog"},
                "description": (
                    "OWW requires a V7-or-newer bundle. NWW requires a "
                    "V8-or-newer bundle containing the selected architecture."
                ),
            },
            {
                "key": "oww_wake_word_url",
                "label": "Tater wake-bundle URL",
                "type": "url",
                "scopes": ["wake"],
                "wake_families": ["echo"],
                "detector_modes": ["oww", "nww", "mww_oww", "mww_nww"],
                "show_when": {"key": "oww_wake_word", "equals": "custom_url"},
                "placeholder": (
                    "http://trainer.local:8789/api/trained_wake_words/"
                    "hey_tater.wake-bundle.json"
                ),
            },
            {
                "key": "nww_architecture",
                "label": "NanoWakeWord architecture",
                "type": "select",
                "scopes": ["wake"],
                "wake_families": ["echo"],
                "detector_modes": ["nww", "mww_nww"],
                "options": [
                    {"value": "cnn", "label": "CNN"},
                    {"value": "gru", "label": "GRU"},
                ],
                "description": (
                    "Architectures not included in the selected bundle stay disabled."
                ),
            },
            {
                "key": "wake_sensitivity",
                "label": "Wake sensitivity",
                "type": "select",
                "scopes": ["device"],
                "detector_modes": ["mww", "oww", "nww", "mww_oww", "mww_nww"],
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
                "scopes": ["device"],
                "detector_modes": ["mww", "oww", "nww", "mww_oww", "mww_nww"],
                "options": [
                    {"value": "balanced", "label": "Balanced"},
                    {"value": "tv_nearby", "label": "TV Nearby"},
                    {"value": "strict", "label": "Strict"},
                    {"value": "far_field", "label": "Far Field / Quiet Room"},
                ],
            },
            {
                "key": "mww_tuning_override_enabled",
                "label": "Override MWW bundle tuning",
                "type": "boolean",
                "scopes": ["wake"],
                "detector_modes": ["mww", "mww_oww", "mww_nww"],
                "override_control": True,
            },
            {
                "key": "mww_threshold_override",
                "label": "MWW threshold",
                "type": "number",
                "scopes": ["wake"],
                "detector_modes": ["mww", "mww_oww", "mww_nww"],
                "show_when": {"key": "mww_tuning_override_enabled", "equals": True},
                "override_control": True,
                "min": 0.01,
                "max": 0.99,
                "step": 0.01,
            },
            {
                "key": "mww_sliding_window_override",
                "label": "MWW sliding window",
                "type": "number",
                "scopes": ["wake"],
                "detector_modes": ["mww", "mww_oww", "mww_nww"],
                "show_when": {"key": "mww_tuning_override_enabled", "equals": True},
                "override_control": True,
                "min": 1,
                "max": 10,
                "step": 1,
            },
            {
                "key": "oww_tuning_override_enabled",
                "label": "Override OWW bundle tuning",
                "type": "boolean",
                "scopes": ["wake"],
                "detector_modes": ["oww", "mww_oww"],
                "override_control": True,
            },
            {
                "key": "oww_threshold_override",
                "label": "OWW threshold",
                "type": "number",
                "scopes": ["wake"],
                "detector_modes": ["oww", "mww_oww"],
                "show_when": {"key": "oww_tuning_override_enabled", "equals": True},
                "override_control": True,
                "min": 0.01,
                "max": 1.0,
                "step": 0.01,
            },
            {
                "key": "oww_patience_override",
                "label": "OWW patience",
                "type": "number",
                "scopes": ["wake"],
                "detector_modes": ["oww", "mww_oww"],
                "show_when": {"key": "oww_tuning_override_enabled", "equals": True},
                "override_control": True,
                "min": 1,
                "max": 20,
                "step": 1,
            },
            {
                "key": "nww_tuning_override_enabled",
                "label": "Override NWW bundle tuning",
                "type": "boolean",
                "scopes": ["wake"],
                "detector_modes": ["nww", "mww_nww"],
                "override_control": True,
            },
            {
                "key": "nww_threshold_override",
                "label": "NWW threshold",
                "type": "number",
                "scopes": ["wake"],
                "detector_modes": ["nww", "mww_nww"],
                "show_when": {"key": "nww_tuning_override_enabled", "equals": True},
                "override_control": True,
                "min": 0.01,
                "max": 1.0,
                "step": 0.01,
            },
            {
                "key": "nww_patience_override",
                "label": "NWW patience",
                "type": "number",
                "scopes": ["wake"],
                "detector_modes": ["nww", "mww_nww"],
                "show_when": {"key": "nww_tuning_override_enabled", "equals": True},
                "override_control": True,
                "min": 1,
                "max": 20,
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
        "section": "audio_output",
        "title": "Satellite1 Audio Output",
        "description": (
            "Choose the internal speaker, 3.5 mm line-out, or both outputs."
        ),
        "scopes": ["device"],
        "include_boards": [
            "satellite1",
            "satellite_1",
            "sat1",
            "satellite1_beta_rev41",
            "sat1_beta_rev41",
        ],
        "fields": [
            {
                "key": "audio_output_mode",
                "label": "Audio output",
                "type": "select",
                "options": [
                    {"value": "auto", "label": "Automatic (jack detection)"},
                    {"value": "internal", "label": "Internal speaker"},
                    {"value": "aux", "label": "AUX / line-out"},
                    {"value": "both", "label": "Internal + AUX"},
                ],
                "description": (
                    "Automatic switches to the 3.5 mm output when a plug is "
                    "detected. AUX requires powered speakers or an external "
                    "amplifier."
                ),
            }
        ],
    },
    {
        "section": "display",
        "title": "Display & Night",
        "description": (
            "Control this satellite's screen, automatic room-light response, "
            "and overnight behavior."
        ),
        "scopes": ["device"],
        "include_boards": ["s3_box", "checkers", "crown", "athena", "rook"],
        "required_capability": "screen_power_management_version",
        "minimum_capability_version": 1,
        "capability_fallback_boards": ["s3_box"],
        "fields": [
            {
                "key": "screen_clock_format",
                "label": "Clock format",
                "type": "select",
                "exclude_boards": ["s3_box"],
                "required_capability": "screen_clock_format",
                "options": [
                    {"value": "12h", "label": "12-hour (6:48 PM)"},
                    {"value": "24h", "label": "24-hour (18:48)"},
                ],
            },
            {
                "key": "screen_climate_entity",
                "label": "Thermostat",
                "type": "select",
                "exclude_boards": ["s3_box"],
                "required_capability": "screen_climate",
                # Filled from Home Assistant's climate entities on each load.
                "options": [{"value": "", "label": "None"}],
                "description": (
                    "Shown on the touchscreen's Climate panel. Its buttons "
                    "change this entity, so pick a room thermostat, not a "
                    "water heater."
                ),
            },
            {
                "key": "screen_room_temperature_entities",
                "label": "Room temperatures",
                "type": "entity_list",
                "max_items": 6,
                "exclude_boards": ["s3_box"],
                "required_capability": "screen_climate",
                # Filled from Home Assistant's temperature sensors on each load.
                "options": [],
                "empty_label": "No temperature sensors found in Home Assistant.",
                "description": (
                    "Up to six readings shown beside the thermostat, labelled "
                    "with each sensor's area. Echo Spot shows the first three."
                ),
            },
            {
                "key": "screen_brightness",
                "label": "Screen brightness",
                "type": "number",
                "min": 0,
                "max": 100,
                "step": 1,
                "description": (
                    "Normal display brightness. Setting this to 0 turns the "
                    "backlight off."
                ),
            },
            {
                "key": "screen_auto_brightness_enabled",
                "label": "Automatic brightness",
                "type": "boolean",
                "exclude_boards": ["s3_box"],
                "description": (
                    "Follow the room's ambient-light sensor smoothly. Screen "
                    "brightness remains the maximum."
                ),
            },
            {
                "key": "screen_auto_brightness_minimum",
                "label": "Dimmest automatic level",
                "type": "number",
                "min": 1,
                "max": 50,
                "step": 1,
                "exclude_boards": ["s3_box"],
                "show_when": {
                    "key": "screen_auto_brightness_enabled",
                    "equals": True,
                },
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
                "key": "screen_night_display",
                "label": "Night display",
                "type": "select",
                "exclude_boards": ["s3_box"],
                "options": [
                    {"value": "red_clock", "label": "Dim red clock"},
                    {"value": "dim", "label": "Dim current display"},
                    {"value": "off", "label": "Screen off"},
                ],
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
                "include_boards": [
                    "biscuit",
                    "echo_dot_2",
                    "echo_dot_2nd_gen",
                    "radar",
                    "echo_2",
                    "echo_2_2017",
                    "echo_2nd_gen",
                    "voice_pe",
                    "satellite1",
                    "satellite_1",
                    "sat1",
                    "sat_1",
                    "respeaker_xvf3800",
                ],
                "options": MUSIC_ANIMATION_OPTIONS,
                "description": (
                    "Audio-reactive ring animation for music playback, including "
                    "Sendspin. Track colors are used when the player provides "
                    "them. Choose No Animation to keep the ring dark."
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
    "oww_wake_word": {"hey_tater", "custom_url"},
    "nww_wake_word": {"hey_tater", "custom_url"},
    "nww_architecture": {"cnn", "gru"},
    "wake_sensitivity": {"conservative", "normal", "high"},
    "wake_environment": {"balanced", "tv_nearby", "strict", "far_field"},
    "wake_verifier_mode": {"off", "observe", "enforce"},
    "wake_sound": {row["value"] for row in WAKE_SOUND_OPTIONS},
    "audio_output_mode": {"auto", "internal", "aux", "both"},
    "screen_night_display": {"dim", "red_clock", "off"},
    "screen_clock_format": {"12h", "24h"},
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
    "wake_nww_enabled",
    "mww_tuning_override_enabled",
    "oww_tuning_override_enabled",
    "nww_tuning_override_enabled",
    "capture_wake_audio",
    "capture_close_misses",
    "wake_sound_enabled",
    "aec_enabled",
    "continued_chat",
    "barge_in_enabled",
    "muted",
    "screen_auto_brightness_enabled",
    "screen_night_mode_enabled",
}
_INT_RANGES = {
    "wake_sliding_window": (1, 10),
    "wake_profile_sliding_window": (1, 10),
    "mww_sliding_window_override": (1, 10),
    "oww_profile_patience": (1, 20),
    "oww_profile_confirmation_patience": (1, 20),
    "nww_profile_patience": (1, 20),
    "nww_cnn_profile_patience": (1, 20),
    "nww_gru_profile_patience": (1, 20),
    "oww_patience_override": (1, 20),
    "nww_patience_override": (1, 20),
    "oww_patience": (1, 20),
    "nww_patience": (1, 20),
    "wake_verifier_window_ms": (500, 2000),
    "wake_verifier_timeout_ms": (100, 2000),
    "aec_strength_percent": (0, 100),
    "aec_delay_ms": (0, 220),
    "volume_percent": (0, 100),
    "screen_brightness": (0, 100),
    "screen_auto_brightness_minimum": (1, 50),
    "screen_night_brightness": (0, 100),
    "led_brightness": (0, 100),
}
_FLOAT_RANGES = {
    "wake_threshold": (0.01, 0.99),
    "wake_profile_threshold": (0.01, 0.99),
    "wake_profile_close_miss_threshold": (0.01, 0.99),
    "mww_threshold_override": (0.01, 0.99),
    "oww_profile_threshold": (0.01, 1.0),
    "oww_profile_confirmation_threshold": (0.01, 1.0),
    "nww_profile_threshold": (0.01, 1.0),
    "nww_cnn_profile_threshold": (0.01, 1.0),
    "nww_gru_profile_threshold": (0.01, 1.0),
    "oww_threshold_override": (0.01, 1.0),
    "nww_threshold_override": (0.01, 1.0),
    "oww_threshold": (0.01, 1.0),
    "nww_threshold": (0.01, 1.0),
    "wake_verifier_threshold": (0.5, 1.0),
    "close_miss_threshold": (0.01, 0.99),
}
_TEXT_LIMITS = {
    "screen_climate_entity": 255,
    "screen_room_temperature_entities": 1024,
    "wake_word_url": 255,
    "wake_model_revision": 64,
    "wake_model_asset_id": 128,
    "oww_wake_word_url": 255,
    "oww_model_revision": 64,
    "nww_wake_word_url": 255,
    "nww_model_revision": 64,
    "nww_available_architectures": 32,
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
    return token in {
        "biscuit",
        "echo-dot-2",
        "echo-dot-2nd-gen",
        "radar",
        "echo-2",
        "echo-2-2017",
        "echo-2nd-gen",
        "voice-pe",
        "satellite1",
        "satellite-1",
        "sat1",
        "sat-1",
        "respeaker-xvf3800",
    } or compact in {
        "biscuit",
        "echodot2",
        "echodot2ndgen",
        "radar",
        "echo2",
        "echo22017",
        "echo2ndgen",
        "voicepe",
        "satellite1",
        "sat1",
        "respeakerxvf3800",
    }


def board_is_s3_screen(board: Any) -> bool:
    """Return whether a board uses the established S3 Box screen contract."""
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


def board_supports_screen_settings(board: Any) -> bool:
    """Return whether a board has a configurable Tater display."""
    token = str(board or "").strip().lower().replace("_", "-").replace(" ", "-")
    compact = token.replace("-", "")
    return board_is_s3_screen(board) or token in {
        "checkers",
        "echo-show-5",
        "echo-show-5-1st-gen",
        "crown",
        "echo-show-8",
        "echo-show-8-1st-gen",
        "athena",
        "a8h3n2",
        "echo-show-8-2nd-gen",
        "rook",
        "echo-spot",
        "echo-spot-1st-gen",
    } or compact in {
        "checkers",
        "echoshow5",
        "echoshow51stgen",
        "crown",
        "echoshow8",
        "echoshow81stgen",
        "athena",
        "a8h3n2",
        "echoshow82ndgen",
        "rook",
        "echospot",
        "echospot1stgen",
    }


def board_is_echo_screen(board: Any) -> bool:
    """Return whether a board is one of the supported Echo displays."""
    return board_supports_screen_settings(board) and not board_is_s3_screen(board)


def supports_screen_power_management(
    board: Any,
    capabilities: dict[str, Any] | None = None,
) -> bool:
    """Return whether firmware can apply the display power settings."""
    if board_is_s3_screen(board):
        return True
    values = capabilities if isinstance(capabilities, dict) else {}
    value = values.get("screen_power_management_version")
    if isinstance(value, bool):
        return value
    try:
        return int(value or 0) >= 1
    except (TypeError, ValueError):
        return False


def supports_screen_clock_format(
    board: Any,
    capabilities: dict[str, Any] | None = None,
) -> bool:
    """Return whether Echo screen firmware accepts a 12/24-hour clock."""
    if board_is_s3_screen(board):
        return False
    values = capabilities if isinstance(capabilities, dict) else {}
    return values.get("screen_clock_format") is True


def board_supports_audio_output_settings(board: Any) -> bool:
    """Return whether a board supports Satellite1 output routing."""
    token = str(board or "").strip().lower().replace("_", "-").replace(" ", "-")
    compact = token.replace("-", "")
    return token in {
        "satellite1",
        "satellite-1",
        "sat1",
        "satellite1-beta-rev41",
        "sat1-beta-rev41",
    } or compact in {
        "satellite1",
        "sat1",
        "satellite1betarev41",
        "sat1betarev41",
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
            if key == "screen_night_display":
                token = {
                    "clock": "red_clock",
                    "red": "red_clock",
                    "screen_off": "off",
                }.get(token, token)
            if key == "screen_clock_format":
                token = {"12": "12h", "24": "24h"}.get(token, token)
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
            result["nww_model_revision"] = ""
        if result.get("nww_wake_word") != "custom_url":
            result["nww_wake_word_url"] = ""
        if result.get("wake_sound") != "custom":
            result["wake_sound_url"] = ""
            result["wake_sound_asset_id"] = ""

    if "wake_detector_mode" in result or not partial:
        mode = str(result.get("wake_detector_mode") or "mww_oww")
        if mode == "dual":
            mode = "mww_oww"
        if mode not in WAKE_DETECTOR_MODES:
            mode = "mww_oww"
        result["wake_detector_mode"] = mode
        result["wake_mww_enabled"] = mode in {"mww", "mww_oww", "mww_nww"}
        result["wake_oww_enabled"] = mode in {"oww", "mww_oww"}
        result["wake_nww_enabled"] = mode in {"nww", "mww_nww"}

    return result


def wake_family_for(
    *, capabilities: dict[str, Any] | None = None, board: Any = ""
) -> str:
    """Return the shared wake profile family for one satellite."""
    caps = capabilities if isinstance(capabilities, dict) else {}
    if any(
        _boolean(caps.get(key), False)
        for key in (
            "openwakeword",
            "nanowakeword",
            "wake_detector_selection",
            "dual_wake_confirmation",
        )
    ):
        return "echo"
    token = str(board or "").strip().lower().replace("_", "-")
    return (
        "echo"
        if token in {"biscuit", "radar", "checkers", "crown", "athena", "rook"}
        else "mww"
    )


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
        else str(current.get("wake_detector_mode") or "mww_oww")
    )
    if mode == "dual":
        mode = "mww_oww"
    if mode not in WAKE_DETECTOR_MODES:
        mode = "mww_oww"
    current["wake_detector_mode"] = mode
    current["wake_mww_enabled"] = mode in {"mww", "mww_oww", "mww_nww"}
    current["wake_oww_enabled"] = mode in {"oww", "mww_oww"}
    current["wake_nww_enabled"] = mode in {"nww", "mww_nww"}
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
    override_values = normalize_settings(
        {
            key: value
            for key, value in (overrides or {}).items()
            if key not in SHARED_WAKE_MODEL_SETTING_KEYS
        },
        base=base_values,
        partial=True,
    )
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
    screen_keys = (
        "screen_brightness",
        "screen_auto_brightness_enabled",
        "screen_auto_brightness_minimum",
        "screen_night_mode_enabled",
        "screen_night_brightness",
        "screen_night_start",
        "screen_night_end",
        "screen_night_display",
    )
    if not supports_screen_clock_format(board, capabilities):
        payload.pop("screen_clock_format", None)
    if supports_screen_power_management(board, capabilities):
        if board_is_s3_screen(board):
            for key in (
                "screen_auto_brightness_enabled",
                "screen_auto_brightness_minimum",
                "screen_night_display",
            ):
                payload.pop(key, None)
        if local_time_seconds is not None:
            if board_is_s3_screen(board):
                payload["screen_local_time_seconds"] = max(
                    0,
                    min((24 * 60 * 60) - 1, int(local_time_seconds)),
                )
    else:
        for key in screen_keys:
            payload.pop(key, None)
    if not board_supports_music_led_settings(board):
        payload.pop("led_music_animation", None)
    if not board_supports_audio_output_settings(board):
        payload.pop("audio_output_mode", None)
    profile_threshold = float(normalized["wake_profile_threshold"])
    adjustment = WAKE_SENSITIVITY_ADJUSTMENTS.get(
        str(normalized["wake_sensitivity"]), 0.0
    )
    payload["wake_threshold"] = round(
        float(normalized["mww_threshold_override"])
        if normalized["mww_tuning_override_enabled"]
        else max(0.01, min(0.99, profile_threshold + adjustment)),
        3,
    )
    payload["wake_sliding_window"] = (
        int(normalized["mww_sliding_window_override"])
        if normalized["mww_tuning_override_enabled"]
        else int(normalized["wake_profile_sliding_window"])
    )
    payload["close_miss_threshold"] = float(
        normalized["wake_profile_close_miss_threshold"]
    )

    mode = str(normalized.get("wake_detector_mode") or "mww_oww")
    if mode == "dual":
        mode = "mww_oww"
    oww_confirmation = mode == "mww_oww"
    oww_profile_threshold = float(
        normalized[
            "oww_profile_confirmation_threshold"
            if oww_confirmation
            else "oww_profile_threshold"
        ]
    )
    oww_profile_patience = int(
        normalized[
            "oww_profile_confirmation_patience"
            if oww_confirmation
            else "oww_profile_patience"
        ]
    )
    payload["oww_threshold"] = round(
        float(normalized["oww_threshold_override"])
        if normalized["oww_tuning_override_enabled"]
        else oww_profile_threshold,
        3,
    )
    payload["oww_patience"] = (
        int(normalized["oww_patience_override"])
        if normalized["oww_tuning_override_enabled"]
        else oww_profile_patience
    )

    architecture = str(normalized.get("nww_architecture") or "cnn")
    architecture = architecture if architecture in {"cnn", "gru"} else "cnn"
    nww_prefix = "nww_gru" if architecture == "gru" else "nww_cnn"
    payload["nww_threshold"] = round(
        float(normalized["nww_threshold_override"])
        if normalized["nww_tuning_override_enabled"]
        else float(normalized[f"{nww_prefix}_profile_threshold"]),
        3,
    )
    payload["nww_patience"] = (
        int(normalized["nww_patience_override"])
        if normalized["nww_tuning_override_enabled"]
        else int(normalized[f"{nww_prefix}_profile_patience"])
    )
    payload["nww_architecture"] = architecture

    family = wake_family_for(capabilities=capabilities, board=board)
    caps = capabilities if isinstance(capabilities, dict) else {}
    supports_oww = any(
        _boolean(caps.get(key), False)
        for key in ("openwakeword", "wake_detector_selection", "dual_wake_confirmation")
    )
    supports_nww = _boolean(caps.get("nanowakeword"), False)
    if family == "mww" or (mode in {"oww", "mww_oww"} and not supports_oww) or (
        mode in {"nww", "mww_nww"} and not supports_nww
    ):
        mode = "mww"
        payload["wake_mww_enabled"] = True
        for key in (
            "wake_oww_enabled",
            "wake_nww_enabled",
            "oww_wake_word",
            "oww_wake_word_url",
            "oww_model_revision",
            "oww_threshold",
            "oww_patience",
            "nww_wake_word",
            "nww_wake_word_url",
            "nww_model_revision",
            "nww_architecture",
            "nww_threshold",
            "nww_patience",
        ):
            payload.pop(key, None)
    else:
        payload["wake_mww_enabled"] = mode in {"mww", "mww_oww", "mww_nww"}
        payload["wake_oww_enabled"] = mode in {"oww", "mww_oww"}
        payload["wake_nww_enabled"] = mode in {"nww", "mww_nww"}
        if mode == "mww":
            for key in (
                "oww_wake_word",
                "oww_wake_word_url",
                "oww_model_revision",
                "oww_threshold",
                "oww_patience",
                "nww_wake_word",
                "nww_wake_word_url",
                "nww_model_revision",
                "nww_architecture",
                "nww_threshold",
                "nww_patience",
            ):
                payload.pop(key, None)
        elif mode in {"oww", "mww_oww"}:
            for key in (
                "nww_wake_word",
                "nww_wake_word_url",
                "nww_model_revision",
                "nww_architecture",
                "nww_threshold",
                "nww_patience",
            ):
                payload.pop(key, None)
            if mode == "oww":
                for key in ("wake_word", "wake_word_url", "wake_model_revision"):
                    payload.pop(key, None)
        else:
            companion_source = str(normalized.get("oww_wake_word") or "hey_tater")
            payload["nww_wake_word"] = companion_source
            payload["nww_wake_word_url"] = str(
                normalized.get("oww_wake_word_url") or ""
            )
            payload["nww_model_revision"] = str(
                normalized.get("nww_model_revision") or ""
            )
            for key in (
                "oww_wake_word",
                "oww_wake_word_url",
                "oww_model_revision",
                "oww_threshold",
                "oww_patience",
            ):
                payload.pop(key, None)
            if mode == "nww":
                for key in ("wake_word", "wake_word_url", "wake_model_revision"):
                    payload.pop(key, None)
    if (
        payload.get("wake_oww_enabled")
        and payload.get("oww_wake_word") == "custom_url"
        and payload.get("oww_wake_word_url")
    ):
        # Echo firmware treats one validated wake bundle as the authority for
        # the OWW half of both single and MWW+OWW modes.
        payload["oww_wake_word"] = "paired_bundle"
    return payload
