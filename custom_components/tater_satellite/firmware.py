"""Tater Native firmware release discovery and artifact caching."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    BOARD_LABELS,
    BOARD_MANIFEST_KEYS,
    FIRMWARE_DOWNLOAD_MAX_BYTES,
    FIRMWARE_REFRESH_SECONDS,
    LATEST_FIRMWARE_URL,
)

_LOGGER = logging.getLogger(__name__)
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:[-+.]([A-Za-z0-9_.-]+))?$")


def board_manifest_key(board: Any) -> str:
    """Map a firmware-reported board id to its release manifest key."""
    token = str(board or "").strip().lower()
    return BOARD_MANIFEST_KEYS.get(token, token.replace("-", "_"))


def display_version(value: Any) -> str:
    """Extract a friendly semantic version from a native firmware version."""
    token = str(value or "").strip()
    match = _VERSION.search(token)
    return match.group(0) if match else token


def version_tuple(value: Any) -> tuple[int, int, int, int, str]:
    """Return a comparable native firmware version tuple."""
    match = _VERSION.search(str(value or "").strip())
    if not match:
        return (0, 0, 0, 0, "")
    prerelease = match.group(4) or ""
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        0 if prerelease else 1,
        prerelease,
    )


@dataclass(slots=True)
class SignedArtifact:
    """A temporary public firmware artifact."""

    token: str
    path: Path
    filename: str
    expires_at: float
    content_type: str = "application/octet-stream"


class FirmwareCatalog:
    """Load release metadata, verify downloads, and issue short-lived URLs."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._root = Path(hass.config.path("tater_satellite", "firmware"))
        self._latest: dict[str, Any] = {}
        self._manifest: dict[str, Any] = {}
        self._last_refresh = 0.0
        self._refresh_lock = asyncio.Lock()
        self._download_lock = asyncio.Lock()
        self._signed: dict[str, SignedArtifact] = {}
        self.last_error = ""

    async def async_setup(self) -> None:
        """Create the cache directory."""
        await self.hass.async_add_executor_job(self._root.mkdir, 0o755, True, True)

    async def _async_json(self, url: str) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        async with session.get(url, timeout=30) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        if not isinstance(data, dict):
            raise ValueError(  # noqa: TRY004
                f"Firmware JSON at {url} is not an object"
            )
        return data

    async def async_refresh(self, *, force: bool = False) -> dict[str, Any]:
        """Refresh the latest release and its manifest."""
        if (
            not force
            and self._manifest
            and (time.monotonic() - self._last_refresh) < FIRMWARE_REFRESH_SECONDS
        ):
            return self.snapshot()

        async with self._refresh_lock:
            if (
                not force
                and self._manifest
                and (time.monotonic() - self._last_refresh) < FIRMWARE_REFRESH_SECONDS
            ):
                return self.snapshot()
            try:
                latest = await self._async_json(LATEST_FIRMWARE_URL)
                manifest_ref = str(latest.get("manifest") or "").strip()
                if not manifest_ref:
                    raise ValueError("latest.json does not include a manifest")
                manifest_url = urljoin(LATEST_FIRMWARE_URL, manifest_ref)
                manifest = await self._async_json(manifest_url)
                if not isinstance(manifest.get("devices"), list):
                    raise ValueError(  # noqa: TRY004
                        "Firmware manifest does not include devices"
                    )
            except Exception as err:
                self.last_error = str(err) or type(err).__name__
                _LOGGER.warning("Unable to refresh Tater firmware catalog: %s", err)
                if not self._manifest:
                    raise
            else:
                self._latest = latest
                self._manifest = manifest
                self._manifest["_source_url"] = manifest_url
                self._last_refresh = time.monotonic()
                self.last_error = ""
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        """Return public catalog metadata."""
        devices: dict[str, Any] = {}
        for row in self._manifest.get("devices", []):
            if not isinstance(row, dict):
                continue
            key = board_manifest_key(row.get("key") or row.get("board"))
            if not key:
                continue
            artifacts = row.get("artifacts")
            devices[key] = {
                "key": key,
                "label": str(row.get("label") or BOARD_LABELS.get(key) or key),
                "board": str(row.get("board") or ""),
                "firmware_version": str(row.get("firmware_version") or ""),
                "display_version": str(
                    row.get("display_version")
                    or display_version(row.get("firmware_version"))
                ),
                "flash_size": str(row.get("flash_size") or ""),
                "xmos_firmware": (
                    dict(row["xmos_firmware"])
                    if isinstance(row.get("xmos_firmware"), dict)
                    else {}
                ),
                "has_ota": isinstance(artifacts, dict)
                and isinstance(artifacts.get("ota"), dict),
                "has_factory": isinstance(artifacts, dict)
                and isinstance(artifacts.get("factory"), dict),
            }
        return {
            "available": bool(devices),
            "version": str(
                self._manifest.get("version") or self._latest.get("version") or ""
            ),
            "display_version": str(
                self._manifest.get("display_version")
                or self._latest.get("display_version")
                or ""
            ),
            "latest_url": LATEST_FIRMWARE_URL,
            "manifest_url": str(self._manifest.get("_source_url") or ""),
            "devices": devices,
            "last_error": self.last_error,
        }

    def info_for_board(self, board: Any) -> dict[str, Any]:
        """Return update metadata for one board."""
        key = board_manifest_key(board)
        public = self.snapshot().get("devices", {}).get(key)
        return (
            dict(public)
            if isinstance(public, dict)
            else {
                "key": key,
                "label": BOARD_LABELS.get(key, key or "Unknown board"),
                "has_ota": False,
                "has_factory": False,
            }
        )

    def _device_row(self, board: Any) -> dict[str, Any]:
        key = board_manifest_key(board)
        for row in self._manifest.get("devices", []):
            if not isinstance(row, dict):
                continue
            if board_manifest_key(row.get("key") or row.get("board")) == key:
                return row
        raise KeyError(f"No released firmware is available for {board}")

    def _artifact_row(self, board: Any, kind: str) -> dict[str, Any]:
        device = self._device_row(board)
        artifacts = device.get("artifacts")
        row = artifacts.get(kind) if isinstance(artifacts, dict) else None
        if not isinstance(row, dict) or not str(row.get("path") or "").strip():
            raise KeyError(f"No {kind} firmware is available for {board}")
        return row

    async def _async_download(
        self, board: Any, kind: str
    ) -> tuple[Path, dict[str, Any]]:
        row = self._artifact_row(board, kind)
        url = urljoin(
            str(self._manifest.get("_source_url") or LATEST_FIRMWARE_URL),
            str(row["path"]),
        )
        filename = _SAFE_FILENAME.sub("_", Path(str(row["path"])).name)
        if not filename:
            filename = f"{board_manifest_key(board)}-{kind}.bin"
        expected_sha = str(row.get("sha256") or "").strip().lower()
        expected_size = int(row.get("size_bytes") or 0)
        target = self._root / filename

        def valid() -> bool:
            if not target.is_file():
                return False
            if expected_size and target.stat().st_size != expected_size:
                return False
            if expected_sha:
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                return digest == expected_sha
            return True

        if await self.hass.async_add_executor_job(valid):
            return target, row

        async with self._download_lock:
            if await self.hass.async_add_executor_job(valid):
                return target, row
            session = async_get_clientsession(self.hass)
            async with session.get(url, timeout=120) as response:
                response.raise_for_status()
                content_length = int(response.headers.get("Content-Length") or 0)
                if content_length > FIRMWARE_DOWNLOAD_MAX_BYTES:
                    raise ValueError("Firmware artifact is larger than expected")
                data = await response.read()
            if len(data) > FIRMWARE_DOWNLOAD_MAX_BYTES:
                raise ValueError("Firmware artifact is larger than expected")
            if expected_size and len(data) != expected_size:
                raise ValueError(
                    f"Firmware size mismatch: expected {expected_size}, got {len(data)}"
                )
            digest = hashlib.sha256(data).hexdigest()
            if expected_sha and digest != expected_sha:
                raise ValueError("Firmware SHA-256 verification failed")
            temporary = target.with_suffix(target.suffix + ".tmp")

            def write() -> None:
                self._root.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(data)
                temporary.replace(target)

            await self.hass.async_add_executor_job(write)
        return target, row

    def _prune_signed(self) -> None:
        now = time.time()
        for token, artifact in tuple(self._signed.items()):
            if artifact.expires_at <= now or not artifact.path.is_file():
                self._signed.pop(token, None)

    async def async_prepare(
        self,
        board: Any,
        kind: str,
        *,
        ttl_seconds: int = 60 * 60,
    ) -> SignedArtifact:
        """Download, validate, and sign an artifact for device/browser access."""
        await self.async_refresh()
        path, _row = await self._async_download(board, kind)
        self._prune_signed()
        token = secrets.token_urlsafe(24)
        signed = SignedArtifact(
            token=token,
            path=path,
            filename=path.name,
            expires_at=time.time() + max(300, ttl_seconds),
        )
        self._signed[token] = signed
        return signed

    def signed_artifact(self, token: str, filename: str) -> SignedArtifact | None:
        """Resolve a signed artifact."""
        self._prune_signed()
        row = self._signed.get(str(token or ""))
        if row is None or row.filename != Path(filename).name:
            return None
        return row

    async def async_web_install_manifest(
        self, board: Any, base_url: str
    ) -> tuple[dict[str, Any], SignedArtifact]:
        """Prepare an ESP Web Tools manifest for a merged factory image."""
        signed = await self.async_prepare(board, "factory")
        info = self.info_for_board(board)
        binary_url = (
            f"{base_url}/api/tater/satellite/v1/firmware/file/"
            f"{signed.filename}?token={signed.token}"
        )
        manifest = {
            "name": f"Tater Native - {info.get('label') or board}",
            "version": info.get("display_version") or "latest",
            "new_install_prompt_erase": True,
            "builds": [
                {
                    "chipFamily": "ESP32-S3",
                    "parts": [{"path": binary_url, "offset": 0}],
                }
            ],
        }
        return manifest, signed
