"""Fast STT verification for local satellite wake-word detections."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import re
import time
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components import stt
from homeassistant.components.assist_pipeline import async_get_pipeline
from homeassistant.components.assist_pipeline.error import PipelineNotFound
from homeassistant.core import HomeAssistant

from .protocol import parse_wake_verifier_packet, text

DEFAULT_MATCH_THRESHOLD = 0.85
DEFAULT_TIMEOUT_MS = 500
_PCM_CHUNK_BYTES = 4096


class WakeVerifierUnavailable(Exception):
    """Signal that verification should safely fail open."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_phrase(value: Any) -> str:
    """Normalize a transcript or wake phrase for fuzzy matching."""
    token = text(value).replace("_", " ").replace("-", " ").lower()
    return " ".join(re.findall(r"[a-z0-9]+", token))


def transcript_match_score(transcript: Any, phrase: Any) -> float:
    """Return the best fuzzy match against neighboring transcript words."""
    target = normalize_phrase(phrase)
    words = normalize_phrase(transcript).split()
    target_words = target.split()
    if not target or not words:
        return 0.0
    max_words = max(1, len(target_words) + 1)
    candidates = [
        " ".join(words[start : start + size])
        for size in range(1, max_words + 1)
        for start in range(len(words) - size + 1)
    ]
    return max(
        difflib.SequenceMatcher(None, candidate, target).ratio()
        for candidate in candidates
    )


async def _pcm_stream(pcm: bytes) -> AsyncGenerator[bytes]:
    """Yield a finite PCM clip in provider-friendly chunks."""
    for offset in range(0, len(pcm), _PCM_CHUNK_BYTES):
        yield pcm[offset : offset + _PCM_CHUNK_BYTES]


async def _async_transcribe(
    hass: HomeAssistant,
    pcm: bytes,
    *,
    pipeline_id: str | None,
) -> tuple[str, str, str, str]:
    """Transcribe PCM with the STT engine selected by an Assist pipeline."""
    try:
        pipeline = async_get_pipeline(hass, pipeline_id=pipeline_id)
    except PipelineNotFound as err:
        raise WakeVerifierUnavailable("pipeline_missing_fail_open") from err
    if not pipeline.stt_engine:
        raise WakeVerifierUnavailable("pipeline_has_no_stt_fail_open")

    engine = stt.async_get_speech_to_text_engine(hass, pipeline.stt_engine)
    if engine is None:
        raise WakeVerifierUnavailable("stt_provider_missing_fail_open")

    metadata = stt.SpeechMetadata(
        language=pipeline.stt_language or pipeline.language or hass.config.language,
        format=stt.AudioFormats.WAV,
        codec=stt.AudioCodecs.PCM,
        bit_rate=stt.AudioBitRates.BITRATE_16,
        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
        channel=stt.AudioChannels.CHANNEL_MONO,
    )
    if not engine.check_metadata(metadata):
        raise WakeVerifierUnavailable("stt_metadata_unsupported_fail_open")

    result = await engine.async_process_audio_stream(metadata, _pcm_stream(pcm))
    transcript = text(result.text)
    if result.result != stt.SpeechResultState.SUCCESS or not transcript:
        raise WakeVerifierUnavailable("stt_no_text_fail_open")
    return transcript, pipeline.id, pipeline.name, pipeline.stt_engine


def unavailable_result(
    data: bytes,
    reason: str,
    *,
    phrase: str = "",
    mode: str = "off",
) -> dict[str, Any]:
    """Build a fail-open response without invoking an STT provider."""
    try:
        packet = parse_wake_verifier_packet(data)
    except ValueError:
        packet = {
            "request_id": 0,
            "sample_count": 0,
            "enforce": mode == "enforce",
            "pcm": b"",
        }
    return {
        "request_id": packet["request_id"],
        "accepted": True,
        "available": False,
        "enforce": bool(packet["enforce"]),
        "mode": mode,
        "phrase": normalize_phrase(phrase),
        "transcript": "",
        "score": 0.0,
        "stt_ms": 0.0,
        "total_ms": 0.0,
        "sample_count": packet["sample_count"],
        "audio_sha256": hashlib.sha256(packet["pcm"]).hexdigest(),
        "pipeline_id": "",
        "pipeline_name": "",
        "stt_engine": "",
        "reason": reason,
    }


async def async_verify_packet(
    hass: HomeAssistant,
    data: bytes,
    *,
    pipeline_id: str | None,
    phrase: str,
    mode: str,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Transcribe and score one firmware wake-verification packet."""
    started = time.perf_counter()
    try:
        packet = parse_wake_verifier_packet(data)
    except ValueError as err:
        return unavailable_result(
            data,
            f"invalid_packet_fail_open: {text(err)}",
            phrase=phrase,
            mode=mode,
        )

    normalized_phrase = normalize_phrase(phrase)
    if not normalized_phrase:
        return unavailable_result(
            data,
            "wake_phrase_unknown_fail_open",
            mode=mode,
        )

    threshold = max(0.5, min(1.0, float(threshold)))
    timeout_ms = max(100, min(2000, int(timeout_ms)))
    stt_started = time.perf_counter()
    try:
        transcript, used_pipeline_id, pipeline_name, engine_id = await asyncio.wait_for(
            _async_transcribe(hass, packet["pcm"], pipeline_id=pipeline_id),
            timeout=timeout_ms / 1000,
        )
        stt_ms = (time.perf_counter() - stt_started) * 1000
        score = transcript_match_score(transcript, normalized_phrase)
        accepted = score >= threshold
        available = True
        reason = "matched" if accepted else "transcript_mismatch"
    except TimeoutError:
        transcript = ""
        used_pipeline_id = pipeline_id or ""
        pipeline_name = ""
        engine_id = ""
        score = 0.0
        stt_ms = float(timeout_ms)
        accepted = True
        available = False
        reason = "server_timeout_fail_open"
    except WakeVerifierUnavailable as err:
        transcript = ""
        used_pipeline_id = pipeline_id or ""
        pipeline_name = ""
        engine_id = ""
        score = 0.0
        stt_ms = (time.perf_counter() - stt_started) * 1000
        accepted = True
        available = False
        reason = err.reason
    # A custom STT provider may raise its own exception type. Wake verification
    # must never make the satellite unusable when that provider fails.
    except Exception as err:  # noqa: BLE001
        transcript = ""
        used_pipeline_id = pipeline_id or ""
        pipeline_name = ""
        engine_id = ""
        score = 0.0
        stt_ms = (time.perf_counter() - stt_started) * 1000
        accepted = True
        available = False
        reason = f"verifier_error_fail_open: {type(err).__name__}"

    return {
        "request_id": packet["request_id"],
        "accepted": accepted,
        "available": available,
        "enforce": bool(packet["enforce"]),
        "mode": mode,
        "phrase": normalized_phrase,
        "threshold": round(threshold, 3),
        "transcript": transcript,
        "score": round(score, 4),
        "stt_ms": round(stt_ms, 1),
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
        "sample_count": packet["sample_count"],
        "audio_sha256": hashlib.sha256(packet["pcm"]).hexdigest(),
        "pipeline_id": used_pipeline_id,
        "pipeline_name": pipeline_name,
        "stt_engine": engine_id,
        "reason": reason,
    }
