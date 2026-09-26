"""Tater firmware release discovery and artifact caching."""

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
    ECHO_FIRMWARE_MANIFEST_URL,
    ECHO_FIRMWARE_RELEASE_URL,
    FIRMWARE_DOWNLOAD_MAX_BYTES,
    FIRMWARE_REFRESH_SECONDS,
    LATEST_FIRMWARE_URL,
    THIRDREALITY_FIRMWARE_RELEASE_URL,
    THIRDREALITY_FIRMWARE_URL,
)

_LOGGER = logging.getLogger(__name__)
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:[-+.]([A-Za-z0-9_.-]+))?$")
USB_APP_PARTITION_SIZE = 0x300000
USB_APP_PARTITION_OFFSETS = {
    "8mb": (0x20000, 0x320000),
    "16mb": (0x20000, 0x320000, 0x620000),
}


def board_manifest_key(board: Any) -> str:
    """Map a firmware-reported board id to its release manifest key."""
    token = str(board or "").strip().lower()
    return BOARD_MANIFEST_KEYS.get(token, token.replace("-", "_"))


def display_version(value: Any) -> str:
    """Extract a friendly semantic version from a native firmware version."""
    token = str(value or "").strip()
    match = _VERSION.search(token)
    return match.group(0) if match else token


def usb_app_partition_offsets(flash_size: Any) -> tuple[int, ...]:
    """Return the native app slots that can be updated without erasing setup."""
    token = str(flash_size or "").strip().lower()
    offsets = USB_APP_PARTITION_OFFSETS.get(token)
    if offsets is None:
        raise ValueError(
            f"USB keep-settings updates do not support flash size {flash_size!r}"
        )
    return offsets


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


def normalize_echo_manifest(
    payload: dict[str, Any],
    *,
    source_url: str = ECHO_FIRMWARE_MANIFEST_URL,
) -> dict[str, Any]:
    """Convert the multi-target Echo release manifest to the shared catalog."""
    targets = payload.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("Tater Echo firmware manifest does not include targets")
    version = str(payload.get("version") or "").strip()
    if not _VERSION.search(version):
        raise ValueError("Tater Echo firmware manifest has an invalid version")

    devices: list[dict[str, Any]] = []
    for raw_key, raw_target in targets.items():
        key = board_manifest_key(raw_key)
        if not key or not isinstance(raw_target, dict):
            continue
        raw_artifacts = raw_target.get("artifacts")
        artifacts: dict[str, dict[str, Any]] = {}
        if isinstance(raw_artifacts, dict):
            for kind in ("factory", "ota"):
                raw_artifact = raw_artifacts.get(kind)
                if not isinstance(raw_artifact, dict):
                    continue
                name = str(raw_artifact.get("name") or "").strip()
                sha256 = str(raw_artifact.get("sha256") or "").strip().lower()
                try:
                    size_bytes = int(raw_artifact.get("size") or 0)
                except (TypeError, ValueError):
                    size_bytes = 0
                if (
                    not name
                    or Path(name).name != name
                    or _SHA256.fullmatch(sha256) is None
                    or size_bytes < 1
                ):
                    raise ValueError(
                        f"Tater Echo {key} {kind} artifact metadata is invalid"
                    )
                artifacts[kind] = {
                    "kind": kind,
                    "path": name,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                    "browser_flash_supported": False,
                }
        if not artifacts:
            continue
        devices.append(
            {
                "key": key,
                "label": str(
                    raw_target.get("display_name")
                    or BOARD_LABELS.get(key)
                    or key
                ),
                "board": str(raw_target.get("amazon_codename") or key),
                "firmware_version": version,
                "display_version": display_version(version),
                "flash_size": "",
                "artifacts": artifacts,
                "browser_usb_supported": False,
                "factory_install_external": True,
                "release_url": ECHO_FIRMWARE_RELEASE_URL,
                "_source_url": source_url,
            }
        )
    if not devices:
        raise ValueError("Tater Echo firmware manifest has no usable targets")
    return {
        "version": version,
        "display_version": display_version(version),
        "devices": devices,
        "_source_url": source_url,
    }


def normalize_thirdreality_manifest(
    payload: dict[str, Any],
    *,
    source_url: str = THIRDREALITY_FIRMWARE_URL,
) -> dict[str, Any]:
    """Validate and annotate the ThirdReality release manifest."""
    raw_devices = payload.get("devices")
    if not isinstance(raw_devices, list):
        raise ValueError("Tater ThirdReality manifest does not include devices")
    version = str(payload.get("version") or "").strip()
    if not _VERSION.search(version):
        raise ValueError("Tater ThirdReality manifest has an invalid version")

    devices: list[dict[str, Any]] = []
    for raw_device in raw_devices:
        if not isinstance(raw_device, dict):
            continue
        key = board_manifest_key(raw_device.get("key") or raw_device.get("board"))
        if not key:
            continue
        raw_artifacts = raw_device.get("artifacts")
        artifacts: dict[str, dict[str, Any]] = {}
        if isinstance(raw_artifacts, dict):
            for kind in ("factory", "ota"):
                raw_artifact = raw_artifacts.get(kind)
                if not isinstance(raw_artifact, dict):
                    continue
                path = str(raw_artifact.get("path") or "").strip()
                sha256 = str(raw_artifact.get("sha256") or "").strip().lower()
                try:
                    size_bytes = int(raw_artifact.get("size_bytes") or 0)
                except (TypeError, ValueError):
                    size_bytes = 0
                if (
                    not path
                    or _SHA256.fullmatch(sha256) is None
                    or size_bytes < 1
                ):
                    raise ValueError(
                        f"Tater ThirdReality {key} {kind} artifact metadata is invalid"
                    )
                artifact = dict(raw_artifact)
                artifact.update(
                    {
                        "kind": kind,
                        "path": path,
                        "sha256": sha256,
                        "size_bytes": size_bytes,
                        "browser_flash_supported": False,
                    }
                )
                artifacts[kind] = artifact
        if not artifacts:
            continue
        device = dict(raw_device)
        device.update(
            {
                "key": key,
                "board": str(raw_device.get("board") or key),
                "label": str(
                    raw_device.get("label") or BOARD_LABELS.get(key) or key
                ),
                "firmware_version": str(
                    raw_device.get("firmware_version")
                    or f"tater-thirdreality-{version}"
                ),
                "display_version": str(
                    raw_device.get("display_version") or display_version(version)
                ),
                "artifacts": artifacts,
                "browser_usb_supported": False,
                "factory_install_external": True,
                "release_url": THIRDREALITY_FIRMWARE_RELEASE_URL,
                "_source_url": source_url,
            }
        )
        devices.append(device)
    if not devices:
        raise ValueError("Tater ThirdReality manifest has no usable targets")
    manifest = dict(payload)
    manifest.update(
        {
            "version": version,
            "display_version": str(
                payload.get("display_version") or display_version(version)
            ),
            "devices": devices,
            "_source_url": source_url,
        }
    )
    return manifest


@dataclass(slots=True)
class SignedArtifact:
    """A temporary public firmware artifact."""

    token: str
    path: Path
    filename: str
    expires_at: float
    sha256: str
    size_bytes: int
    content_type: str = "application/octet-stream"


class FirmwareCatalog:
    """Load release metadata, verify downloads, and issue short-lived URLs."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._root = Path(hass.config.path("tater_satellite", "firmware"))
        self._latest: dict[str, Any] = {}
        self._manifest: dict[str, Any] = {}
        self._source_latest: dict[str, dict[str, Any]] = {}
        self._source_manifests: dict[str, dict[str, Any]] = {}
        self._source_errors: dict[str, str] = {}
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

    async def _async_native_catalog(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load and annotate the Tater Native release catalog."""
        latest = await self._async_json(LATEST_FIRMWARE_URL)
        manifest_ref = str(latest.get("manifest") or "").strip()
        if not manifest_ref:
            raise ValueError("latest.json does not include a manifest")
        manifest_url = urljoin(LATEST_FIRMWARE_URL, manifest_ref)
        raw_manifest = await self._async_json(manifest_url)
        raw_devices = raw_manifest.get("devices")
        if not isinstance(raw_devices, list):
            raise ValueError("Firmware manifest does not include devices")
        devices: list[dict[str, Any]] = []
        for raw_device in raw_devices:
            if not isinstance(raw_device, dict):
                continue
            device = dict(raw_device)
            device["_source_url"] = manifest_url
            device["release_url"] = LATEST_FIRMWARE_URL
            device["browser_usb_supported"] = True
            devices.append(device)
        manifest = dict(raw_manifest)
        manifest["devices"] = devices
        manifest["_source_url"] = manifest_url
        return latest, manifest

    async def _async_echo_catalog(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load the combined Biscuit and Checkers Echo release catalog."""
        raw_manifest = await self._async_json(ECHO_FIRMWARE_MANIFEST_URL)
        manifest = normalize_echo_manifest(
            raw_manifest,
            source_url=ECHO_FIRMWARE_MANIFEST_URL,
        )
        return {"version": manifest.get("version")}, manifest

    async def _async_thirdreality_catalog(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load the ThirdReality S420 release catalog."""
        latest = await self._async_json(THIRDREALITY_FIRMWARE_URL)
        manifest_ref = str(latest.get("manifest") or "").strip()
        if not manifest_ref:
            raise ValueError("ThirdReality latest.json does not include a manifest")
        manifest_url = urljoin(THIRDREALITY_FIRMWARE_URL, manifest_ref)
        raw_manifest = await self._async_json(manifest_url)
        manifest = normalize_thirdreality_manifest(
            raw_manifest,
            source_url=manifest_url,
        )
        return latest, manifest

    async def async_refresh(self, *, force: bool = False) -> dict[str, Any]:
        """Refresh all Tater firmware releases into one board-aware catalog."""
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
            source_names = ("native", "echo", "thirdreality")
            results = await asyncio.gather(
                self._async_native_catalog(),
                self._async_echo_catalog(),
                self._async_thirdreality_catalog(),
                return_exceptions=True,
            )
            refreshed = False
            errors: dict[str, str] = {}
            for source_name, result in zip(source_names, results, strict=True):
                if isinstance(result, BaseException):
                    errors[source_name] = str(result) or type(result).__name__
                    _LOGGER.warning(
                        "Unable to refresh Tater %s firmware catalog: %s",
                        source_name,
                        result,
                    )
                    continue
                latest, manifest = result
                self._source_latest[source_name] = latest
                self._source_manifests[source_name] = manifest
                refreshed = True

            if not self._source_manifests:
                self.last_error = "; ".join(
                    f"{name}: {message}" for name, message in errors.items()
                )
                raise RuntimeError(
                    self.last_error or "No Tater firmware catalog is available"
                )

            devices: list[dict[str, Any]] = []
            versions: list[str] = []
            display_versions: list[str] = []
            for manifest in self._source_manifests.values():
                devices.extend(
                    dict(row)
                    for row in manifest.get("devices", [])
                    if isinstance(row, dict)
                )
                version = str(manifest.get("version") or "").strip()
                shown = str(manifest.get("display_version") or "").strip()
                if version and version not in versions:
                    versions.append(version)
                if shown and shown not in display_versions:
                    display_versions.append(shown)
            self._manifest = {
                "version": versions[0] if len(versions) == 1 else "Multiple releases",
                "display_version": (
                    display_versions[0]
                    if len(display_versions) == 1
                    else "Multiple releases"
                ),
                "devices": devices,
                "_source_url": LATEST_FIRMWARE_URL,
            }
            self._latest = dict(self._source_latest.get("native") or {})
            self._source_errors = errors
            if refreshed:
                self._last_refresh = time.monotonic()
            self.last_error = "" if refreshed else "; ".join(errors.values())
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
                "browser_usb_supported": bool(
                    row.get("browser_usb_supported", True)
                ),
                "factory_install_external": bool(
                    row.get("factory_install_external", False)
                ),
                "release_url": str(row.get("release_url") or LATEST_FIRMWARE_URL),
                "manifest_url": str(row.get("_source_url") or ""),
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
            "source_errors": dict(self._source_errors),
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
        result = dict(row)
        result["_source_url"] = str(
            row.get("_source_url") or device.get("_source_url") or ""
        )
        return result

    async def _async_download(
        self, board: Any, kind: str
    ) -> tuple[Path, dict[str, Any]]:
        row = self._artifact_row(board, kind)
        url = urljoin(
            str(row.get("_source_url") or LATEST_FIRMWARE_URL),
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
        path, row = await self._async_download(board, kind)
        self._prune_signed()
        token = secrets.token_urlsafe(24)
        sha256 = str(row.get("sha256") or "").strip().lower()
        if _SHA256.fullmatch(sha256) is None:
            sha256 = await self.hass.async_add_executor_job(
                lambda: hashlib.sha256(path.read_bytes()).hexdigest()
            )
        signed = SignedArtifact(
            token=token,
            path=path,
            filename=path.name,
            expires_at=time.time() + max(300, ttl_seconds),
            sha256=sha256,
            size_bytes=path.stat().st_size,
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
        self,
        board: Any,
        base_url: str,
        flash_kind: str = "factory",
    ) -> tuple[dict[str, Any], SignedArtifact]:
        """Prepare an ESP Web Tools manifest for factory or app-only USB flash."""
        kind = str(flash_kind or "factory").strip().lower()
        if kind not in {"factory", "ota"}:
            raise ValueError(f"Unsupported USB flash type: {flash_kind!r}")
        info = self.info_for_board(board)
        if not bool(info.get("browser_usb_supported", True)):
            label = info.get("label") or board
            raise ValueError(
                f"Browser USB flashing is not supported for {label}; "
                "use its model-specific factory installer"
            )
        signed = await self.async_prepare(board, kind)
        artifact = self._artifact_row(board, kind)
        flash_size = str(artifact.get("flash_size") or info.get("flash_size") or "")
        if kind == "ota" and signed.path.stat().st_size > USB_APP_PARTITION_SIZE:
            raise ValueError(
                "The OTA image is too large for the satellite app partition"
            )
        binary_url = (
            f"{base_url}/api/tater/satellite/v1/firmware/file/"
            f"{signed.filename}?token={signed.token}"
        )
        offsets = (
            (0,)
            if kind == "factory"
            else usb_app_partition_offsets(flash_size)
        )
        manifest = {
            "name": (
                f"Tater Native Factory - {info.get('label') or board}"
                if kind == "factory"
                else f"Tater Native OTA Update - {info.get('label') or board}"
            ),
            "version": info.get("display_version") or "latest",
            "new_install_prompt_erase": kind == "factory",
            "builds": [
                {
                    "chipFamily": "ESP32-S3",
                    "parts": [
                        {"path": binary_url, "offset": offset}
                        for offset in offsets
                    ],
                }
            ],
        }
        return manifest, signed
