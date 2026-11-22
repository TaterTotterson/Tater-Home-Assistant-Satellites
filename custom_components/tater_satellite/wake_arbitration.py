"""Bridge-side wake selection; independent of firmware and voice providers."""

from __future__ import annotations

import asyncio
from array import array
from collections import deque
from dataclasses import dataclass, field
import math
import re
import sys
import time
from typing import Any

DEFAULT_SETTINGS = {
    "enabled": True,
    "scope": "same_area",
    "selection": "strongest_audio",
    "window_ms": 900,
    "release_ms": 1500,
    "busy_timeout_s": 120,
}

SETTINGS_FIELDS = [
    {"key": "enabled", "label": "Choose one satellite per wake", "type": "boolean"},
    {
        "key": "scope",
        "label": "Compare satellites",
        "type": "select",
        "options": [
            {"value": "same_area", "label": "In the same room"},
            {"value": "global", "label": "Across the whole home"},
        ],
        "description": "Uses the room saved on each satellite. Satellites without a room are grouped together.",
    },
    {
        "key": "selection",
        "label": "Choose the winner",
        "type": "select",
        "options": [
            {"value": "strongest_audio", "label": "Strongest command audio"},
            {"value": "first_wake", "label": "First wake received"},
        ],
        "description": "Audio strength can vary with microphone gain. With no usable audio, the first wake wins.",
    },
    {
        "key": "window_ms",
        "label": "Selection window",
        "type": "duration_range",
        "min": 100,
        "max": 3000,
        "step": 100,
        "default": 900,
        "min_label": "faster response",
        "max_label": "more time to compare",
        "description": "Buffer command audio before starting STT. A longer window gives nearby satellites more time to join.",
    },
    {
        "key": "release_ms",
        "label": "Late-wake protection",
        "type": "duration_range",
        "min": 0,
        "max": 5000,
        "step": 100,
        "default": 1500,
        "min_label": "release immediately",
        "max_label": "longer protection",
        "description": "Keep other satellites quiet for this long after the reply finishes. The winning satellite can wake again immediately.",
    },
    {
        "key": "busy_timeout_s",
        "label": "Busy safety timeout (seconds)",
        "type": "number",
        "min": 5,
        "max": 300,
        "step": 1,
    },
]


def normalize_settings(values: Any, *, strict: bool = False) -> dict[str, Any]:
    """Validate host-only settings without accepting firmware settings."""
    result = dict(DEFAULT_SETTINGS)
    if not isinstance(values, dict):
        if strict:
            raise ValueError("Wake arbitration settings must be an object")
        return result
    for key, value in values.items():
        valid = False
        if key == "enabled":
            valid = isinstance(value, bool)
        elif key == "scope":
            valid = value in ("same_area", "global")
        elif key == "selection":
            valid = value in ("strongest_audio", "first_wake")
        elif key in ("window_ms", "release_ms", "busy_timeout_s"):
            low, high = {
                "window_ms": (100, 3000),
                "release_ms": (0, 5000),
                "busy_timeout_s": (5, 300),
            }[key]
            valid = (
                type(value) in (int, float)
                and math.isfinite(value)
                and value == int(value)
                and low <= value <= high
            )
        if not valid:
            if strict:
                raise ValueError(f"Invalid wake arbitration setting: {key}")
            continue
        result[key] = int(value) if key.endswith(("_ms", "_s")) else value
    return result


def _key(value: str) -> str:
    return re.sub(r"[\W_]+", " ", value.casefold()).strip()


@dataclass(eq=False)
class WakeCandidate:
    """One voice turn, with a bounded audio score and a selection future."""

    device_id: str
    name: str
    room: str
    phrase: str
    scope: str
    settings: dict[str, Any]
    started: float
    decision: asyncio.Future[bool]
    group: tuple[str, str] | None = None
    expires: float = 0.0
    selected: bool = False
    samples: int = 0
    energy: int = 0
    # Cap scoring independently of transport packet size and capture duration.
    sample_limit: int = 48000
    pcm: bool = True
    tail: bytes = b""

    @property
    def dbfs(self) -> float:
        if not self.samples or not self.energy:
            return -96.0
        return max(-96.0, 10 * math.log10(self.energy / self.samples / (32768**2)))

    def add_audio(self, data: bytes) -> None:
        if self.decision.done() or not self.pcm or self.samples >= self.sample_limit:
            return
        data = (self.tail + data)[: (self.sample_limit - self.samples) * 2]
        self.tail = data[len(data) - len(data) % 2 :] if len(data) % 2 else b""
        samples = array("h")
        samples.frombytes(data[: len(data) - len(data) % 2])
        if sys.byteorder != "little":
            samples.byteswap()
        self.energy += sum(sample * sample for sample in samples)
        self.samples += len(samples)


@dataclass
class _Group:
    candidates: list[WakeCandidate] = field(default_factory=list)
    timer: asyncio.TimerHandle | None = None


class WakeArbitrator:
    """Collect simultaneous wakes and hold the winner through response playback."""

    def __init__(self) -> None:
        self._groups: dict[tuple[str, str], _Group] = {}
        self._turns: dict[str, WakeCandidate] = {}
        self._claims: dict[str, WakeCandidate] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=30)

    def _prune(self, now: float) -> None:
        for scope, candidate in list(self._claims.items()):
            if candidate.expires <= now:
                del self._claims[scope]

    def begin(
        self,
        device_id: str,
        name: str,
        room: str,
        phrase: str,
        settings: dict[str, Any],
        audio_format: dict[str, Any],
    ) -> WakeCandidate:
        """Register synchronously so the transport can acknowledge immediately."""
        loop = asyncio.get_running_loop()
        now = loop.time()
        self._prune(now)
        previous = self._turns.get(device_id)
        if previous is not None:
            self.cancel(previous)
        settings = normalize_settings(settings)
        scope = (
            "global"
            if settings["scope"] == "global"
            else f"room:{_key(room) or 'unknown'}"
        )
        candidate = WakeCandidate(
            device_id, name, room, phrase, scope, settings, now, loop.create_future()
        )
        # All supported satellites use signed little-endian 16-bit PCM. Unknown
        # formats still participate using the deterministic first-wake fallback.
        candidate.pcm = (
            str(audio_format.get("format", "pcm")).lower()
            in {"pcm", "s16le", "pcm_s16le"}
            and audio_format.get("width", audio_format.get("sample_width", 2)) == 2
        )
        self._turns[device_id] = candidate
        claim = self._claims.get(scope)
        if not settings["enabled"] or not _key(phrase):
            candidate.selected = True
            candidate.decision.set_result(True)
            if settings["enabled"] and (claim is None or claim.device_id == device_id):
                self._claim(candidate)
        elif claim is not None:
            accepted = claim.device_id == device_id
            candidate.selected = accepted
            candidate.decision.set_result(accepted)
            if accepted:
                self._claim(candidate)
            else:
                self._record(claim, [candidate], "busy")
        else:
            key = (scope, _key(phrase))
            candidate.group = key
            group = self._groups.get(key)
            if group is None:
                group = self._groups[key] = _Group()
                group.timer = loop.call_later(
                    settings["window_ms"] / 1000, self._resolve, key
                )
            group.candidates.append(candidate)
        return candidate

    def _claim(self, candidate: WakeCandidate) -> None:
        candidate.expires = (
            asyncio.get_running_loop().time() + candidate.settings["busy_timeout_s"]
        )
        self._claims[candidate.scope] = candidate

    def _resolve(self, key: tuple[str, str]) -> None:
        group = self._groups.pop(key, None)
        if group is None:
            return
        candidates = [
            c
            for c in group.candidates
            if self._turns.get(c.device_id) is c and not c.decision.done()
        ]
        if not candidates:
            return
        self._prune(asyncio.get_running_loop().time())
        winner = self._claims.get(key[0])
        reason = "busy"
        if winner is None:
            # Compare RMS over post-boundary command audio, with an earlier wake
            # breaking ties. Never consume or trim the actual STT audio queue.
            first = candidates[0]
            winner = (
                max(candidates, key=lambda c: (c.dbfs, -c.started))
                if first.settings["selection"] == "strongest_audio"
                else first
            )
            reason = first.settings["selection"]
            winner.selected = True
            self._claim(winner)
        self._record(winner, candidates, reason)
        for candidate in candidates:
            candidate.decision.set_result(candidate is winner)

    def _record(
        self, winner: WakeCandidate, candidates: list[WakeCandidate], reason: str
    ) -> None:
        self._history.appendleft(
            {
                "timestamp": time.time(),
                "winner_id": winner.device_id,
                "winner": winner.name,
                "room": winner.room,
                "phrase": candidates[0].phrase,
                "reason": reason,
                "candidates": [
                    {
                        "device_id": c.device_id,
                        "name": c.name,
                        "audio_dbfs": round(c.dbfs, 1) if c.samples else None,
                        "selected": c is winner,
                    }
                    for c in candidates
                ],
            }
        )

    def release(self, candidate: WakeCandidate) -> None:
        """Release after playback, retaining a short guard against late wakes."""
        if self._claims.get(candidate.scope) is candidate:
            candidate.expires = min(
                candidate.expires,
                asyncio.get_running_loop().time()
                + candidate.settings["release_ms"] / 1000,
            )
        if self._turns.get(candidate.device_id) is candidate:
            del self._turns[candidate.device_id]

    def cancel(self, candidate: WakeCandidate) -> None:
        """Remove a disconnected/aborted turn without disturbing a newer turn."""
        if self._turns.get(candidate.device_id) is candidate:
            del self._turns[candidate.device_id]
        if self._claims.get(candidate.scope) is candidate:
            del self._claims[candidate.scope]
        group = self._groups.get(candidate.group)
        if group is not None:
            group.candidates = [c for c in group.candidates if c is not candidate]
            if not group.candidates:
                if group.timer is not None:
                    group.timer.cancel()
                self._groups.pop(candidate.group, None)
        if not candidate.decision.done():
            candidate.decision.set_result(False)

    def snapshot(self) -> dict[str, Any]:
        self._prune(asyncio.get_running_loop().time())
        return {
            "pending": len(self._groups),
            "busy": len(self._claims),
            "history": list(self._history),
        }

    def shutdown(self) -> None:
        for candidate in list(self._turns.values()):
            self.cancel(candidate)
        self._claims.clear()
