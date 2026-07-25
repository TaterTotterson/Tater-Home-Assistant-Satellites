"""Secure Wake Word Trainer pairing and publishing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .const import TRAINER_PAIRING_CODE_ALPHABET, TRAINER_PAIRING_TTL_SECONDS

if TYPE_CHECKING:
    from .manager import TaterSatelliteManager


def _text(value: Any, limit: int = 0) -> str:
    result = str(value or "").strip()
    return result[:limit] if limit else result


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _token_digest(value: Any) -> str:
    return hashlib.sha256(_text(value).encode("utf-8")).hexdigest()


def _code_digest(value: Any) -> str:
    normalized = "".join(ch for ch in _text(value).upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _http_base_url(value: Any, *, label: str) -> str:
    token = _text(value, 512).rstrip("/")
    parsed = urlparse(token)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must start with http:// or https://.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{label} must be a plain server address.")
    return token


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlparse(value)
    scheme = str(parsed.scheme or "").lower()
    host = str(parsed.hostname or "").lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, host, int(port)


class TrainerLinkManager:
    """Manage one securely linked microWakeWord trainer."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self._pairing: dict[str, Any] = {}

    def setup(self) -> None:
        """Initialize persisted trainer state."""
        value = self.manager.data.get("trainer_link")
        if not isinstance(value, dict):
            self.manager.data["trainer_link"] = {}

    def _link(self) -> dict[str, Any]:
        value = self.manager.data.get("trainer_link")
        return value if isinstance(value, dict) else {}

    def status(self) -> dict[str, Any]:
        """Return link metadata without credential material."""
        link = self._link()
        linked = bool(_text(link.get("token_hash")) and _text(link.get("trainer_id")))
        return {
            "linked": linked,
            "trainer_id": _text(link.get("trainer_id")),
            "trainer_name": _text(link.get("trainer_name")) or "Wake Word Trainer",
            "trainer_url": _text(link.get("trainer_url")),
            "publish_base_url": _text(link.get("publish_base_url")),
            "linked_at": _text(link.get("linked_at")),
            "last_publish_at": _text(link.get("last_publish_at")),
            "last_wake_word": _text(link.get("last_wake_word")),
            "last_wake_word_url": _text(link.get("last_wake_word_url")),
        }

    def _expire_pairing(self) -> None:
        if self._pairing and float(self._pairing.get("expires_at") or 0) <= time.time():
            self._pairing = {}

    def pairing_snapshot(self) -> dict[str, Any]:
        """Return the active admin-visible trainer pairing session."""
        self._expire_pairing()
        if not self._pairing:
            return {
                "active": False,
                "state": "idle",
                "display_code": "",
                "expires_at": 0,
                "expires_in_s": 0,
            }
        state = _text(self._pairing.get("state")).lower() or "waiting"
        expires_at = float(self._pairing.get("expires_at") or 0)
        return {
            "active": state == "waiting" and expires_at > time.time(),
            "pairing_id": _text(self._pairing.get("pairing_id")),
            "state": state,
            "linked": state == "linked",
            "display_code": (
                _text(self._pairing.get("display_code")) if state == "waiting" else ""
            ),
            "trainer_name": _text(self._pairing.get("trainer_name")),
            "linked_at": _text(self._pairing.get("linked_at")),
            "expires_at": expires_at,
            "expires_in_s": max(0, int(expires_at - time.time())),
        }

    def start_pairing(self) -> dict[str, Any]:
        """Create a short-lived, one-use pairing code."""
        raw_code = "".join(
            secrets.choice(TRAINER_PAIRING_CODE_ALPHABET) for _ in range(8)
        )
        now = time.time()
        self._pairing = {
            "pairing_id": secrets.token_urlsafe(18),
            "code_hash": _code_digest(raw_code),
            "display_code": f"{raw_code[:4]}-{raw_code[4:]}",
            "state": "waiting",
            "created_at": now,
            "expires_at": now + TRAINER_PAIRING_TTL_SECONDS,
            "trainer_name": "",
            "linked_at": "",
        }
        return {
            "ok": True,
            **self.pairing_snapshot(),
        }

    async def async_claim(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Exchange an active pairing code for a persistent trainer token."""
        self._expire_pairing()
        pairing = self._pairing
        supplied_hash = _code_digest(payload.get("pairing_code"))
        if (
            not pairing
            or _text(pairing.get("state")).lower() != "waiting"
            or not hmac.compare_digest(
                supplied_hash,
                _text(pairing.get("code_hash")),
            )
        ):
            raise ValueError("Pairing code is invalid or expired.")

        trainer_id = _text(payload.get("trainer_id"), 160)
        if not trainer_id:
            raise ValueError("Trainer identity is required.")
        trainer_url = _http_base_url(payload.get("trainer_url"), label="Trainer URL")
        publish_base_url = _http_base_url(
            payload.get("publish_base_url") or trainer_url,
            label="Trainer public URL",
        )
        trainer_name = _text(payload.get("trainer_name"), 120) or "Wake Word Trainer"
        link_token = secrets.token_urlsafe(32)
        linked_at = _iso_now()
        self.manager.data["trainer_link"] = {
            "token_hash": _token_digest(link_token),
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "trainer_url": trainer_url,
            "publish_base_url": publish_base_url,
            "linked_at": linked_at,
            "last_publish_at": "",
            "last_wake_word": "",
            "last_wake_word_url": "",
        }
        pairing.update(
            {
                "state": "linked",
                "display_code": "",
                "trainer_name": trainer_name,
                "linked_at": linked_at,
                "expires_at": max(
                    float(pairing.get("expires_at") or 0),
                    time.time() + 60,
                ),
            }
        )
        await self.manager.async_save()
        return {
            "ok": True,
            "linked": True,
            "token": link_token,
            "tater_name": "Home Assistant",
            "linked_at": linked_at,
        }

    def authorize(self, token: Any) -> dict[str, Any]:
        """Authorize a trainer credential and return its private record."""
        supplied = _text(token)
        link = self._link()
        expected = _text(link.get("token_hash"))
        if not supplied or not expected:
            raise PermissionError("Wake Word Trainer is not linked.")
        if not hmac.compare_digest(_token_digest(supplied), expected):
            raise PermissionError("Invalid Wake Word Trainer link token.")
        return link

    @staticmethod
    def validate_wake_word_url(value: Any, link: dict[str, Any]) -> str:
        """Allow only a trained JSON package served by the linked trainer."""
        url = _text(value, 1024)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Wake-word JSON URL must start with http:// or https://.")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Wake-word JSON URL is invalid.")
        if not parsed.path.startswith(
            "/api/trained_wake_words/"
        ) or not parsed.path.lower().endswith(".json"):
            raise ValueError(
                "Linked trainers may only publish their trained wake-word JSON packages."
            )
        publish_base_url = _text(link.get("publish_base_url"))
        if not publish_base_url or _origin(url) != _origin(publish_base_url):
            raise ValueError(
                "Wake-word JSON URL does not belong to the linked trainer."
            )
        return url

    async def async_publish(
        self,
        token: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish the trainer's current wake word to every satellite."""
        link = self.authorize(token)
        wake_word = _text(
            payload.get("wake_word_name") or payload.get("wake_word"),
            120,
        )
        wake_word_url = self.validate_wake_word_url(
            payload.get("wake_word_url"),
            link,
        )
        result = await self.manager.async_publish_trainer_wake_word(
            wake_word,
            wake_word_url,
        )
        link.update(
            {
                "last_publish_at": _iso_now(),
                "last_wake_word": wake_word,
                "last_wake_word_url": wake_word_url,
            }
        )
        await self.manager.async_save()
        return {
            "ok": True,
            "wake_word": wake_word,
            "wake_word_url": wake_word_url,
            **result,
            "trainer_link": self.status(),
        }

    async def async_unlink(
        self, token: Any | None = None, *, admin: bool = False
    ) -> dict[str, Any]:
        """Revoke the current trainer credential."""
        if not admin:
            self.authorize(token)
        self.manager.data["trainer_link"] = {}
        self._pairing = {}
        await self.manager.async_save()
        return {
            "ok": True,
            "message": "Wake Word Trainer unlinked.",
            **self.status(),
        }
