"""Constants for the Tater Satellite integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "tater_satellite"
NAME: Final = "Tater Satellite"

PLATFORMS: Final = (
    Platform.ASSIST_SATELLITE,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
    Platform.UPDATE,
)

DATA_MANAGER: Final = "manager"
DATA_PANEL_REGISTERED: Final = "panel_registered"

PANEL_URL_PATH: Final = "tater-satellites"
PANEL_ELEMENT: Final = "tater-satellite-panel"
PANEL_STATIC_URL: Final = "/tater_satellite_frontend"

SATELLITE_WS_PATH: Final = "/api/tater/satellite/v1/ws"
API_BASE_PATH: Final = "/api/tater/satellite/v1"

PROTOCOL_VERSION: Final = 1
STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = "tater_satellite"

PAIRING_CODE_TTL_SECONDS: Final = 10 * 60
PAIRING_MAX_FAILED_ATTEMPTS: Final = 5
TRAINER_PAIRING_TTL_SECONDS: Final = 10 * 60
TRAINER_PAIRING_CODE_ALPHABET: Final = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
TRAINER_LINK_HEADER: Final = "X-Tater-Trainer-Token"
DEVICE_STALE_SECONDS: Final = 90
MAX_AUDIO_QUEUE_CHUNKS: Final = 256
MAX_TEXT_MESSAGE_BYTES: Final = 64 * 1024

LATEST_FIRMWARE_URL: Final = (
    "https://github.com/TaterTotterson/"
    "Tater-Native-Firmware/releases/latest/download/latest.json"
)
ECHO_FIRMWARE_MANIFEST_URL: Final = (
    "https://github.com/TaterTotterson/"
    "Tater-Echo-Firmware/releases/latest/download/firmware-manifest.json"
)
ECHO_FIRMWARE_RELEASE_URL: Final = (
    "https://github.com/TaterTotterson/Tater-Echo-Firmware/releases/latest"
)
THIRDREALITY_FIRMWARE_URL: Final = (
    "https://github.com/TaterTotterson/"
    "Tater-ThirdReality-Voice-Firmware/releases/latest/download/latest.json"
)
THIRDREALITY_FIRMWARE_RELEASE_URL: Final = (
    "https://github.com/TaterTotterson/"
    "Tater-ThirdReality-Voice-Firmware/releases/latest"
)
FIRMWARE_REFRESH_SECONDS: Final = 15 * 60
FIRMWARE_DOWNLOAD_MAX_BYTES: Final = 192 * 1024 * 1024

BOARD_MANIFEST_KEYS: Final = {
    "biscuit": "biscuit",
    "echo-dot-2": "biscuit",
    "echo_dot_2": "biscuit",
    "checkers": "checkers",
    "echo-show-5": "checkers",
    "echo_show_5": "checkers",
    "echo-show-5-1st-gen": "checkers",
    "echo_show_5_1st_gen": "checkers",
    "radar": "radar",
    "echo-2": "radar",
    "echo_2": "radar",
    "echo-2nd-gen": "radar",
    "echo_2nd_gen": "radar",
    "crown": "crown",
    "echo-show-8": "crown",
    "echo_show_8": "crown",
    "echo-show-8-1st-gen": "crown",
    "echo_show_8_1st_gen": "crown",
    "athena": "athena",
    "a8h3n2": "athena",
    "echo-show-8-2nd-gen": "athena",
    "echo_show_8_2nd_gen": "athena",
    "rook": "rook",
    "echo-spot": "rook",
    "echo_spot": "rook",
    "echo-spot-1st-gen": "rook",
    "echo_spot_1st_gen": "rook",
    "thirdreality-s420": "thirdreality_s420",
    "thirdreality_s420": "thirdreality_s420",
    "third-reality-s420": "thirdreality_s420",
    "s420": "thirdreality_s420",
    "voice-pe": "voicepe",
    "voicepe": "voicepe",
    "satellite1": "satellite1",
    "sat1": "satellite1",
    "satellite1-beta-rev41": "satellite1_beta_rev41",
    "satellite1_beta_rev41": "satellite1_beta_rev41",
    "sat1-beta-rev41": "satellite1_beta_rev41",
    "respeaker-xvf3800": "respeaker_xvf3800",
    "respeaker_xvf3800": "respeaker_xvf3800",
    "s3-box": "s3_box",
    "s3_box": "s3_box",
    "s3box": "s3_box",
}

BOARD_LABELS: Final = {
    "biscuit": "Echo Dot 2 (Biscuit)",
    "checkers": "Echo Show 5 1st Gen (Checkers)",
    "radar": "Echo 2nd Gen (Radar)",
    "crown": "Echo Show 8 1st Gen (Crown)",
    "athena": "Echo Show 8 2nd Gen (Athena)",
    "rook": "Echo Spot 1st Gen (Rook)",
    "thirdreality_s420": "ThirdReality Voice & Music Assistant (S420)",
    "voicepe": "Voice PE",
    "satellite1": "Satellite1",
    "satellite1_beta_rev41": "Satellite1 Beta.1 / rev4.1",
    "respeaker_xvf3800": "ReSpeaker XVF3800",
    "s3_box": "ESP32-S3-BOX-3",
}
