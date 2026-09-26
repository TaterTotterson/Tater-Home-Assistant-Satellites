"""Push-to-talk intercom relay for connected Tater satellites."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import re
import secrets
import time
import wave
from collections import deque
from io import BytesIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

INTERCOM_EVENT = "tater_satellite_intercom"
INTERCOM_CAPTURE_SECONDS = 90
INTERCOM_CLIP_TTL_SECONDS = 5 * 60
INTERCOM_MAX_PCM_BYTES = 4 * 1024 * 1024
INTERCOM_MIN_AUDIO_SECONDS = 0.25
INTERCOM_WAKE_WORDS = {
    "broadcast intercom",
    "intercom broadcast",
    "push to intercom",
    "push to talk intercom",
    "tater broadcast intercom",
    "tater intercom broadcast",
}
INTERCOM_SOURCES = {
    "center_button_hold",
    "intercom",
    "intercom_hold",
    "push_to_intercom",
    "push_to_talk",
}
INTERCOM_DUCKING = {
    "target_percent": 20,
    "attack_ms": 150,
    "release_ms": 350,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _phrase(value: Any) -> str:
    token = re.sub(r"[^a-z0-9]+", " ", _text(value).lower())
    return re.sub(r"\s+", " ", token).strip()


def is_intercom_request(payload: dict[str, Any]) -> bool:
    """Return whether a firmware voice turn is a held-button broadcast."""
    wake_word = _phrase(payload.get("wake_word"))
    source = _text(payload.get("source")).lower().replace("-", "_")
    return wake_word in INTERCOM_WAKE_WORDS or source in INTERCOM_SOURCES


def _audio_format(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("audio_format")
    values = raw if isinstance(raw, dict) else {}
    return {
        "rate": max(8_000, min(48_000, _integer(values.get("rate"), 16_000))),
        "width": max(1, min(4, _integer(values.get("width"), 2))),
        "channels": max(1, min(8, _integer(values.get("channels"), 1))),
    }


def pcm_to_wav(pcm: bytes, audio_format: dict[str, Any]) -> bytes:
    """Wrap little-endian PCM in a standard WAV container."""
    rate = max(8_000, min(48_000, _integer(audio_format.get("rate"), 16_000)))
    width = max(1, min(4, _integer(audio_format.get("width"), 2)))
    channels = max(1, min(8, _integer(audio_format.get("channels"), 1)))
    align = width * channels
    usable = len(pcm) - (len(pcm) % align)
    if usable <= 0:
        return b""
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(width)
        wav_file.setframerate(rate)
        wav_file.writeframes(pcm[:usable])
    return output.getvalue()


class TaterIntercomCoordinator:
    """Capture one source microphone and fan its recording out to peers."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self.captures: dict[str, dict[str, Any]] = {}
        self.clips: dict[str, dict[str, Any]] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=25)

    def _fire(self, phase: str, values: dict[str, Any]) -> None:
        payload = {"phase": phase, **values}
        with contextlib.suppress(Exception):
            self.manager.hass.bus.async_fire(INTERCOM_EVENT, payload)

    def _prune_clips(self) -> None:
        now = time.time()
        for clip_id, row in tuple(self.clips.items()):
            if float(row.get("expires_at") or 0) <= now:
                self.clips.pop(clip_id, None)

    def start_capture(
        self, runtime: SatelliteRuntime, payload: dict[str, Any]
    ) -> tuple[bool, str]:
        """Open an in-memory microphone capture for a held button."""
        previous = self.captures.pop(runtime.device_id, None)
        if previous is not None:
            self._record(previous, "cancelled", error="replaced")

        audio_format = _audio_format(payload)
        bytes_per_second = (
            audio_format["rate"]
            * audio_format["width"]
            * audio_format["channels"]
        )
        capture = {
            "session_id": secrets.token_hex(12),
            "source_device_id": runtime.device_id,
            "source_name": runtime.name,
            "source_room": runtime.room,
            "audio_format": audio_format,
            "pcm": bytearray(),
            "started_at": time.time(),
            "max_bytes": min(
                INTERCOM_MAX_PCM_BYTES,
                bytes_per_second * INTERCOM_CAPTURE_SECONDS,
            ),
            "truncated": False,
        }
        self.captures[runtime.device_id] = capture
        runtime.intercom_session = {
            "active": True,
            "session_id": capture["session_id"],
            "started_at": capture["started_at"],
        }
        runtime.add_log(
            "info",
            "Push-to-talk intercom capture started",
            kind="intercom",
        )
        runtime.notify()
        self._fire(
            "started",
            {
                "session_id": capture["session_id"],
                "source_device_id": runtime.device_id,
                "source_name": runtime.name,
                "source_room": runtime.room,
            },
        )
        return True, ""

    def add_audio(self, runtime: SatelliteRuntime, data: bytes) -> bool:
        """Append PCM to an intercom capture and suppress Assist routing."""
        capture = self.captures.get(runtime.device_id)
        if not isinstance(capture, dict):
            return False
        pcm = capture["pcm"]
        remaining = max(0, int(capture["max_bytes"]) - len(pcm))
        if remaining:
            pcm.extend(bytes(data[:remaining]))
        if len(data) > remaining:
            capture["truncated"] = True
        return True

    def finish_capture(
        self, runtime: SatelliteRuntime, *, abort: bool
    ) -> dict[str, Any] | None:
        """Close a capture and return it for asynchronous broadcasting."""
        capture = self.captures.pop(runtime.device_id, None)
        if not isinstance(capture, dict):
            return None
        runtime.intercom_session = {}
        runtime.notify()
        capture["ended_at"] = time.time()
        capture["aborted"] = bool(abort)
        if abort:
            self._record(capture, "cancelled", error="aborted")
            runtime.add_log("info", "Push-to-talk intercom cancelled", kind="intercom")
        return capture

    def handle_disconnect(self, runtime: SatelliteRuntime) -> None:
        """Discard a partial recording when its source disconnects."""
        self.finish_capture(runtime, abort=True)

    async def async_shutdown(self) -> None:
        """Forget transient microphone audio and playback assets."""
        for runtime in tuple(self.manager.runtimes.values()):
            self.finish_capture(runtime, abort=True)
        self.captures.clear()
        self.clips.clear()

    def _duration(self, capture: dict[str, Any]) -> float:
        audio_format = capture["audio_format"]
        bytes_per_second = max(
            1,
            int(audio_format["rate"])
            * int(audio_format["width"])
            * int(audio_format["channels"]),
        )
        return len(capture["pcm"]) / bytes_per_second

    def _record(
        self,
        capture: dict[str, Any],
        phase: str,
        *,
        targets: list[SatelliteRuntime] | None = None,
        sent: list[SatelliteRuntime] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        target_rows = targets or []
        sent_rows = sent or []
        row = {
            "session_id": _text(capture.get("session_id")),
            "phase": phase,
            "source_device_id": _text(capture.get("source_device_id")),
            "source_name": _text(capture.get("source_name")),
            "source_room": _text(capture.get("source_room")),
            "duration_seconds": round(self._duration(capture), 3),
            "pcm_bytes": len(capture.get("pcm") or b""),
            "truncated": bool(capture.get("truncated")),
            "target_device_ids": [runtime.device_id for runtime in target_rows],
            "target_names": [runtime.name for runtime in target_rows],
            "sent_device_ids": [runtime.device_id for runtime in sent_rows],
            "sent_count": len(sent_rows),
            "error": error,
            "timestamp": time.time(),
        }
        self.history.appendleft(row)
        self._fire(phase, row)
        return row

    async def _send_clip(
        self,
        runtime: SatelliteRuntime,
        *,
        clip_id: str,
        token: str,
        overlay_id: str,
    ) -> bool:
        base_url = runtime.server_base_url or self.manager.public_base_url()
        url = (
            f"{base_url.rstrip('/')}/api/tater/satellite/v1/"
            f"intercom/{clip_id}.wav?token={token}"
        )
        if (
            runtime.media_session.get("active")
            and runtime.capabilities.get("tts_overlays")
        ):
            return await runtime.async_send(
                "audio.overlay.start",
                {
                    "overlay_id": overlay_id,
                    "group_id": _text(runtime.media_session.get("group_id")),
                    "foreground": {
                        "url": url,
                        "kind": "intercom",
                        "volume_percent": 100,
                    },
                    "ducking": dict(INTERCOM_DUCKING),
                },
            )
        return await runtime.async_send(
            "play.url",
            {
                "url": url,
                "tts_kind": "intercom",
                "ducking": dict(INTERCOM_DUCKING),
            },
        )

    async def async_broadcast(
        self, source: SatelliteRuntime, capture: dict[str, Any]
    ) -> dict[str, Any]:
        """Publish one finished held-button recording to every online peer."""
        if capture.get("aborted"):
            return self._record(capture, "cancelled", error="aborted")
        duration = self._duration(capture)
        if duration < INTERCOM_MIN_AUDIO_SECONDS:
            source.add_log(
                "warning",
                "Intercom recording was too short to broadcast",
                kind="intercom",
            )
            source.notify()
            return self._record(capture, "empty", error="recording_too_short")

        targets = [
            runtime
            for runtime in self.manager.runtimes.values()
            if runtime.device_id != source.device_id and runtime.connected
        ]
        if not targets:
            source.add_log(
                "warning",
                "Intercom has no other connected satellites",
                kind="intercom",
            )
            source.notify()
            return self._record(capture, "failed", error="no_targets")

        wav_bytes = pcm_to_wav(bytes(capture["pcm"]), capture["audio_format"])
        if not wav_bytes:
            return self._record(capture, "empty", error="invalid_audio")
        self._prune_clips()
        clip_id = secrets.token_hex(12)
        token = secrets.token_urlsafe(24)
        self.clips[clip_id] = {
            "token": token,
            "body": wav_bytes,
            "expires_at": time.time() + INTERCOM_CLIP_TTL_SECONDS,
        }
        overlay_id = f"intercom-{capture['session_id']}"
        results = await asyncio.gather(
            *(
                self._send_clip(
                    runtime,
                    clip_id=clip_id,
                    token=token,
                    overlay_id=overlay_id,
                )
                for runtime in targets
            ),
            return_exceptions=True,
        )
        sent = [
            runtime
            for runtime, result in zip(targets, results, strict=True)
            if result is True
        ]
        failed = [runtime.name for runtime in targets if runtime not in sent]
        phase = "broadcast" if sent else "failed"
        error = ", ".join(failed) if failed else ""
        row = self._record(
            capture,
            phase,
            targets=targets,
            sent=sent,
            error=error,
        )
        source.add_log(
            "info" if sent else "error",
            (
                f"Intercom broadcast sent to {len(sent)} satellite"
                f"{'s' if len(sent) != 1 else ''}"
                if sent
                else "Intercom broadcast failed"
            ),
            kind="intercom",
        )
        source.notify()
        for runtime in sent:
            runtime.add_log(
                "info",
                f"Intercom received from {source.name}",
                kind="intercom",
            )
            runtime.notify()
        _LOGGER.info(
            "Tater intercom source=%s targets=%s sent=%s duration=%.3f",
            source.device_id,
            len(targets),
            len(sent),
            duration,
        )
        return row

    def clip_bytes(self, clip_id: str, token: str) -> bytes | None:
        """Resolve an opaque, short-lived intercom WAV URL."""
        self._prune_clips()
        row = self.clips.get(_text(clip_id))
        if not isinstance(row, dict):
            return None
        expected = _text(row.get("token"))
        if not expected or not hmac.compare_digest(expected, _text(token)):
            return None
        body = row.get("body")
        return bytes(body) if isinstance(body, (bytes, bytearray)) else None

    def device_snapshot(self, runtime: SatelliteRuntime) -> dict[str, Any]:
        """Return capture state for one management-panel device row."""
        capture = self.captures.get(runtime.device_id)
        if not isinstance(capture, dict):
            return {"active": False}
        return {
            "active": True,
            "session_id": capture["session_id"],
            "started_at": capture["started_at"],
            "pcm_bytes": len(capture["pcm"]),
            "truncated": bool(capture["truncated"]),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return global intercom readiness and recent delivery history."""
        connected = [
            runtime
            for runtime in self.manager.runtimes.values()
            if runtime.connected
        ]
        return {
            "ready": len(connected) >= 2,
            "connected_count": len(connected),
            "connected_devices": [
                {"device_id": runtime.device_id, "name": runtime.name}
                for runtime in connected
            ],
            "active_count": len(self.captures),
            "recent": list(self.history),
            "event_type": INTERCOM_EVENT,
            "storage": "memory_only",
        }
