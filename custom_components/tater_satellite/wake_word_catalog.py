"""Official Tater wake-word catalog discovery and selection."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

CATALOG_REPOSITORY_URL = "https://github.com/TaterTotterson/Tater-Wake-Words"
CATALOG_MANIFEST_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/wake_word_manifest.json"
)

_LOGGER = logging.getLogger(__name__)
_REMOTE_TIMEOUT_SECONDS = 8
_CACHE_TTL_SECONDS = 10 * 60
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_SOURCE_PATTERN = re.compile(
    r"^microWakeWordsV(?P<version>[0-9]+)$", re.IGNORECASE
)
_CATALOG_PATH_PATTERN = re.compile(
    r"^/TaterTotterson/Tater-Wake-Words/main/"
    r"microWakeWordsV[0-9]+/[^/]+\.json$",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_catalog_url(value: Any) -> bool:
    """Return whether a URL belongs to the official versioned catalog."""
    token = _text(value)
    if not token:
        return False
    try:
        parsed = urlparse(token)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "raw.githubusercontent.com"
        and bool(_CATALOG_PATH_PATTERN.fullmatch(parsed.path))
    )


def require_catalog_url(value: Any, *, minimum_version: int = 1) -> str:
    """Return a validated official catalog URL."""
    token = _text(value)
    if not is_catalog_url(token):
        raise ValueError("Select a wake word from the official Tater catalog.")
    match = re.search(r"/microWakeWordsV([0-9]+)/", urlparse(token).path, re.I)
    version = int(match.group(1)) if match else 0
    if version < minimum_version:
        raise ValueError(
            f"This wake engine requires a V{minimum_version}-or-newer "
            "Tater wake bundle."
        )
    return token


def resolve_wake_word_source_values(
    values: dict[str, Any],
    *,
    allow_catalog_only: bool = False,
) -> dict[str, Any]:
    """Translate the panel-only catalog source into firmware settings."""
    resolved = dict(values or {})
    source = _text(resolved.get("wake_word")).lower().replace("-", "_")
    catalog_url = _text(resolved.get("wake_word_catalog_url"))
    if source == "catalog" or (allow_catalog_only and not source and catalog_url):
        resolved["wake_word"] = "custom_url"
        resolved["wake_word_url"] = require_catalog_url(
            catalog_url
        )
        resolved["wake_model_asset_id"] = ""
    resolved.pop("wake_word_catalog_url", None)
    companion_source = _text(resolved.get("oww_wake_word")).lower().replace(
        "-", "_"
    )
    companion_catalog_url = _text(resolved.get("oww_wake_word_catalog_url"))
    if companion_source == "catalog" or (
        allow_catalog_only and not companion_source and companion_catalog_url
    ):
        mode = _text(resolved.get("wake_detector_mode")).lower()
        minimum_version = 8 if mode in {"nww", "mww_nww"} else 7
        resolved["oww_wake_word"] = "custom_url"
        resolved["oww_wake_word_url"] = require_catalog_url(
            companion_catalog_url,
            minimum_version=minimum_version,
        )
    resolved.pop("oww_wake_word_catalog_url", None)
    return resolved


def _source_version(source: Any) -> tuple[int, str]:
    token = _text(source)
    match = _SOURCE_PATTERN.fullmatch(token)
    if not match:
        return 999, token or "Catalog"
    version = int(match.group("version"))
    return version, f"V{version}"


def _raw_url(path: Any) -> str:
    token = _text(path).lstrip("/")
    if not token:
        return ""
    return (
        "https://raw.githubusercontent.com/TaterTotterson/"
        f"Tater-Wake-Words/main/{token}"
    )


def entries_from_manifest(payload: Any) -> list[dict[str, Any]]:
    """Normalize supported catalog manifest layouts."""
    rows: list[Any] = []
    if isinstance(payload, list):
        rows = list(payload)
    elif isinstance(payload, dict):
        for key in ("entries", "wake_words", "words", "models", "items"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = list(candidate)
                break

    entries: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = _text(
            row.get("source") or row.get("source_label") or row.get("folder")
        )
        version, version_label = _source_version(source)
        url = _text(
            row.get("url") or row.get("download_url") or row.get("json_url")
        ) or _raw_url(row.get("path"))
        if not is_catalog_url(url):
            continue
        bundle_url = _text(row.get("bundle_url")) or _raw_url(
            row.get("bundle_path")
        )
        if not is_catalog_url(bundle_url):
            bundle_url = ""
        raw_engines = row.get("available_engines")
        engines = {
            _text(value).lower().replace("-", "_")
            for value in raw_engines
        } if isinstance(raw_engines, list) else set()
        if row.get("dual_model") or row.get("open_wake_word"):
            engines.add("open_wake_word")
        architectures = row.get("nanowakeword_architectures")
        if isinstance(architectures, list) and architectures:
            engines.add("nano_wake_word")
        if row.get("nano_model"):
            engines.add("nano_wake_word")
        slug = _text(row.get("slug") or row.get("name") or row.get("key"))
        label = _text(row.get("label") or row.get("title"))
        if not label:
            filename = url.rsplit("/", 1)[-1].removesuffix(".json")
            label = (slug or filename).replace("_", " ").title()
        entries[url] = {
            "id": _text(row.get("id")) or f"{source}:{slug}",
            "slug": slug,
            "label": label,
            "url": url,
            "bundle_url": bundle_url,
            "available_engines": sorted(engines),
            "nanowakeword_architectures": sorted(
                {
                    _text(value).lower()
                    for value in (architectures or [])
                    if _text(value).lower() in {"cnn", "gru"}
                }
            ),
            "source": source,
            "version": version,
            "version_label": version_label,
        }

    return sorted(
        entries.values(),
        key=lambda row: (
            int(row.get("version") or 999),
            _text(row.get("label")).casefold(),
            _text(row.get("slug")).casefold(),
        ),
    )


class WakeWordCatalog:
    """Fetch and cache official wake-word choices without blocking HA."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._entries: list[dict[str, Any]] = []
        self._last_refresh = 0.0
        self._refresh_lock = asyncio.Lock()
        self.last_error = ""

    async def _async_fetch(self) -> list[dict[str, Any]]:
        async def _read_manifest() -> bytearray:
            async with self._session.get(
                CATALOG_MANIFEST_URL,
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                while len(raw) <= _MAX_MANIFEST_BYTES:
                    chunk = await response.content.read(
                        min(64 * 1024, _MAX_MANIFEST_BYTES + 1 - len(raw))
                    )
                    if not chunk:
                        break
                    raw.extend(chunk)
            return raw

        raw = await asyncio.wait_for(
            _read_manifest(),
            timeout=_REMOTE_TIMEOUT_SECONDS,
        )
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ValueError("Wake word catalog manifest is too large.")
        entries = entries_from_manifest(json.loads(raw.decode("utf-8")))
        if not entries:
            raise ValueError("Wake word catalog contains no usable models.")
        return entries

    async def async_refresh(self, *, force: bool = False) -> dict[str, Any]:
        """Refresh catalog entries, retaining stale entries after failures."""
        if (
            not force
            and self._entries
            and time.monotonic() - self._last_refresh < _CACHE_TTL_SECONDS
        ):
            return self.snapshot()

        async with self._refresh_lock:
            if (
                not force
                and self._entries
                and time.monotonic() - self._last_refresh < _CACHE_TTL_SECONDS
            ):
                return self.snapshot()
            try:
                entries = await self._async_fetch()
            except Exception as err:  # noqa: BLE001
                detail = str(err).strip() or type(err).__name__
                self.last_error = (
                    "Could not refresh the Tater wake-word catalog: "
                    f"{detail}."
                )
                _LOGGER.warning("%s", self.last_error)
            else:
                self._entries = entries
                self._last_refresh = time.monotonic()
                self.last_error = ""
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        """Return the compact catalog payload used by the settings panel."""
        versions = sorted(
            {
                int(row.get("version") or 0)
                for row in self._entries
                if int(row.get("version") or 0) < 999
            }
        )
        oww_rows = [
            row
            for row in self._entries
            if int(row.get("version") or 0) >= 7
            and _text(row.get("bundle_url"))
            and "open_wake_word" in set(row.get("available_engines") or [])
        ]
        nww_rows = [
            row
            for row in self._entries
            if int(row.get("version") or 0) >= 8
            and _text(row.get("bundle_url"))
            and "nano_wake_word" in set(row.get("available_engines") or [])
        ]

        def _bundle_options(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    "value": _text(row.get("bundle_url")),
                    "label": (
                        f"{_text(row.get('label'))} "
                        f"[{_text(row.get('version_label'))}]"
                    ),
                    "architectures": list(
                        row.get("nanowakeword_architectures") or []
                    ),
                }
                for row in rows
            ]

        return {
            "options": [
                {
                    "value": _text(row.get("url")),
                    "label": (
                        f"{_text(row.get('label'))} "
                        f"[{_text(row.get('version_label'))}]"
                    ),
                }
                for row in self._entries
                if _text(row.get("url"))
            ],
            "oww_options": _bundle_options(oww_rows),
            "nww_options": _bundle_options(nww_rows),
            "count": len(self._entries),
            "versions": versions,
            "warning": self.last_error,
            "manifest_url": CATALOG_MANIFEST_URL,
            "repository_url": CATALOG_REPOSITORY_URL,
        }
