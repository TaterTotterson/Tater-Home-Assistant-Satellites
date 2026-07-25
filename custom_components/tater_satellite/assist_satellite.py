"""Assist satellite entity for Tater Native firmware."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components import assist_satellite, tts
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    PipelineStage,
)
from homeassistant.components.intent import (
    TimerEventType,
    TimerInfo,
    async_register_timer_handler,
)
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

_EVENT_NAMES = {
    PipelineEventType.RUN_START: "RUN_START",
    PipelineEventType.RUN_END: "RUN_END",
    PipelineEventType.WAKE_WORD_START: "WAKE_WORD_START",
    PipelineEventType.WAKE_WORD_END: "WAKE_WORD_END",
    PipelineEventType.STT_START: "STT_START",
    PipelineEventType.STT_VAD_START: "STT_VAD_START",
    PipelineEventType.STT_VAD_END: "STT_VAD_END",
    PipelineEventType.STT_END: "STT_END",
    PipelineEventType.INTENT_START: "INTENT_START",
    PipelineEventType.INTENT_PROGRESS: "INTENT_PROGRESS",
    PipelineEventType.INTENT_END: "INTENT_END",
    PipelineEventType.TTS_START: "TTS_START",
    PipelineEventType.TTS_END: "TTS_END",
    PipelineEventType.ERROR: "ERROR",
}

_STATE_BY_EVENT = {
    "STT_START": "listening",
    "STT_VAD_START": "listening",
    "STT_VAD_END": "thinking",
    "STT_END": "thinking",
    "INTENT_START": "thinking",
    "INTENT_PROGRESS": "thinking",
    "INTENT_END": "thinking",
    "TTS_START": "speaking",
    "TTS_END": "speaking",
}


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up dynamically discovered Tater Assist satellites."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "assist_satellite",
        lambda runtime: [TaterAssistSatellite(runtime)],
        async_add_entities,
    )


class TaterAssistSatellite(assist_satellite.AssistSatelliteEntity):
    """A Tater Native satellite connected directly to Home Assistant."""

    entity_description = assist_satellite.AssistSatelliteEntityDescription(
        key="assist_satellite",
        name="Voice Assistant",
    )
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        assist_satellite.AssistSatelliteEntityFeature.ANNOUNCE
        | assist_satellite.AssistSatelliteEntityFeature.START_CONVERSATION
    )

    def __init__(self, runtime: SatelliteRuntime) -> None:
        self.runtime = runtime
        self.manager = runtime.manager
        self.config_entry = runtime.manager.entry
        self._attr_unique_id = f"{runtime.device_id}_assist_satellite"
        self._attr_name = "Voice Assistant"
        self._bridge_task: asyncio.Task[None] | None = None
        self._attr_tts_options = {
            tts.ATTR_PREFERRED_FORMAT: "wav",
            tts.ATTR_PREFERRED_SAMPLE_RATE: 16000,
            tts.ATTR_PREFERRED_SAMPLE_CHANNELS: 1,
            tts.ATTR_PREFERRED_SAMPLE_BYTES: 2,
        }
        runtime.assist_entity = self
        runtime.manager.attach_entity(runtime, self)

    @property
    def available(self) -> bool:
        """Return whether the satellite is online."""
        return self.runtime.connected

    @property
    def device_info(self):
        """Return device registry metadata."""
        from homeassistant.helpers.device_registry import DeviceInfo

        from .const import DOMAIN

        return DeviceInfo(
            identifiers={(DOMAIN, self.runtime.device_id)},
            name=self.runtime.name,
            manufacturer="Tater",
            model=self.runtime.board or "Native Satellite",
            sw_version=self.runtime.firmware_version or None,
            suggested_area=self.runtime.room or None,
        )

    @property
    def pipeline_entity_id(self) -> str | None:
        """Return the per-satellite Assist pipeline selector."""
        return self.runtime.pipeline_entity_id or None

    @property
    def vad_sensitivity_entity_id(self) -> str | None:
        """Return the per-satellite VAD selector."""
        return self.runtime.vad_entity_id or None

    @callback
    def async_get_configuration(
        self,
    ) -> assist_satellite.AssistSatelliteConfiguration:
        """Return available local wake words."""
        assets = self.manager.data.get("assets", {})
        available = [
            assist_satellite.AssistSatelliteWakeWord(
                id="hey_tater",
                wake_word="Hey Tater",
                trained_languages=["en"],
            )
        ]
        if isinstance(assets, dict):
            available.extend(
                assist_satellite.AssistSatelliteWakeWord(
                    id=asset_id,
                    wake_word=str(row.get("label") or "Custom wake word"),
                    trained_languages=["en"],
                )
                for asset_id, row in assets.items()
                if isinstance(row, dict) and row.get("kind") == "wake_model"
            )
        settings = self.runtime.effective_settings()
        active: list[str] = []
        if settings.get("wake_engine") == "micro_wake_word":
            asset_id = str(settings.get("wake_model_asset_id") or "")
            if settings.get("wake_word") == "custom_url" and asset_id:
                active = [asset_id]
            elif settings.get("wake_word") == "custom_url" and settings.get(
                "wake_word_url"
            ):
                available.append(
                    assist_satellite.AssistSatelliteWakeWord(
                        id="custom_url",
                        wake_word="External custom wake model",
                        trained_languages=["en"],
                    )
                )
                active = ["custom_url"]
            else:
                active = ["hey_tater"]
        return assist_satellite.AssistSatelliteConfiguration(
            available_wake_words=available,
            active_wake_words=active,
            max_active_wake_words=1,
        )

    async def async_set_configuration(
        self, config: assist_satellite.AssistSatelliteConfiguration
    ) -> None:
        """Set the active on-device wake model."""
        if not config.active_wake_words:
            await self.manager.async_set_device_settings(
                self.runtime.device_id, {"wake_engine": "off"}
            )
            return
        wake_id = config.active_wake_words[0]
        if wake_id == "hey_tater":
            values = {
                "wake_engine": "micro_wake_word",
                "wake_word": "hey_tater",
                "wake_model_asset_id": "",
                "wake_word_url": "",
            }
        elif wake_id == "custom_url":
            current = self.runtime.effective_settings()
            if not current.get("wake_word_url"):
                raise ValueError("External custom wake URL is missing")
            values = {
                "wake_engine": "micro_wake_word",
                "wake_word": "custom_url",
                "wake_model_asset_id": "",
            }
        else:
            asset = self.manager.data.get("assets", {}).get(wake_id)
            if not isinstance(asset, dict) or asset.get("kind") != "wake_model":
                raise ValueError("Wake model is no longer available")
            values = {
                "wake_engine": "micro_wake_word",
                "wake_word": "custom_url",
                "wake_model_asset_id": wake_id,
            }
        await self.manager.async_set_device_settings(self.runtime.device_id, values)

    async def async_added_to_hass(self) -> None:
        """Register device timers when the entity is added."""
        await super().async_added_to_hass()
        if self.registry_entry is not None and self.registry_entry.device_id:
            self.async_on_remove(
                async_register_timer_handler(
                    self.hass,
                    self.registry_entry.device_id,
                    self._handle_timer_event,
                )
            )

    async def async_will_remove_from_hass(self) -> None:
        """Stop an active pipeline."""
        await self.async_device_voice_stop({"abort": True})
        if self.runtime.assist_entity is self:
            self.runtime.assist_entity = None
        await super().async_will_remove_from_hass()

    async def _audio_stream(self) -> AsyncGenerator[bytes]:
        while True:
            data = await self.runtime.audio_queue.get()
            if data is None:
                break
            yield data

    async def _run_pipeline(self, wake_word: str, conversation_id: str) -> None:
        if conversation_id:
            self._conversation_id = conversation_id
        try:
            await self.async_accept_pipeline_from_satellite(
                audio_stream=self._audio_stream(),
                start_stage=PipelineStage.STT,
                end_stage=PipelineStage.TTS,
                wake_word_phrase=wake_word or None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.exception("Assist pipeline failed for %s", self.runtime.device_id)
            await self.runtime.async_send(
                "voice.event",
                {
                    "event": "ERROR",
                    "data": {
                        "code": "pipeline_error",
                        "message": str(err) or type(err).__name__,
                    },
                },
            )
            await self.runtime.async_send("state", {"state": "error"})
        finally:
            self._bridge_task = None

    async def async_device_voice_start(self, payload: dict[str, Any]) -> bool:
        """Start an Assist run requested by firmware."""
        await self.async_device_voice_stop({"abort": True})
        self.runtime.reset_audio()
        wake_word = str(
            payload.get("wake_word") or payload.get("wake_word_phrase") or ""
        ).replace("_", " ")
        conversation_id = str(
            payload.get("conversation_id") or payload.get("conversation") or ""
        )
        self._bridge_task = self.config_entry.async_create_background_task(
            self.hass,
            self._run_pipeline(wake_word, conversation_id),
            f"tater_satellite_pipeline_{self.runtime.device_id}",
        )
        return True

    def device_audio(self, data: bytes) -> None:
        """Accept a PCM audio chunk from firmware."""
        self.runtime.add_audio(data)

    async def async_device_voice_stop(self, payload: dict[str, Any]) -> None:
        """Stop or finalize a firmware-requested Assist run."""
        abort = bool(payload.get("abort"))
        self.runtime.finish_audio()
        if abort:
            with contextlib.suppress(Exception):
                await self._cancel_running_pipeline()
            if self._bridge_task is not None:
                self._bridge_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._bridge_task
                self._bridge_task = None

    @callback
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Translate Home Assistant pipeline events to firmware commands."""
        event_name = _EVENT_NAMES.get(event.type)
        if not event_name:
            return
        source = event.data if isinstance(event.data, dict) else {}
        data: dict[str, Any] = {}
        if event.type is PipelineEventType.STT_END:
            output = source.get("stt_output")
            if isinstance(output, dict):
                data["text"] = str(output.get("text") or "")
        elif event.type is PipelineEventType.INTENT_PROGRESS:
            if source.get("tts_start_streaming"):
                data["tts_start_streaming"] = "1"
        elif event.type is PipelineEventType.INTENT_END:
            output = source.get("intent_output")
            if isinstance(output, dict):
                response = output.get("response")
                speech = (
                    response.get("speech")
                    if isinstance(response, dict)
                    and isinstance(response.get("speech"), dict)
                    else {}
                )
                plain = (
                    speech.get("plain") if isinstance(speech.get("plain"), dict) else {}
                )
                data = {
                    "conversation_id": str(output.get("conversation_id") or ""),
                    "continue_conversation": bool(output.get("continue_conversation")),
                    "speech": str(plain.get("speech") or ""),
                }
        elif event.type is PipelineEventType.TTS_START:
            data["text"] = str(source.get("tts_input") or "")
        elif event.type is PipelineEventType.TTS_END:
            output = source.get("tts_output")
            if isinstance(output, dict) and output.get("url"):
                data["url"] = async_process_play_media_url(
                    self.hass, str(output["url"])
                )
        elif event.type is PipelineEventType.ERROR:
            data = {
                "code": str(source.get("code") or "pipeline_error"),
                "message": str(source.get("message") or "Voice pipeline failed"),
            }

        self.hass.async_create_task(
            self._async_forward_pipeline_event(event_name, data),
            f"tater_satellite_event_{event_name.lower()}",
        )

    async def _async_forward_pipeline_event(
        self, event_name: str, data: dict[str, Any]
    ) -> None:
        await self.runtime.async_send(
            "voice.event", {"event": event_name, "data": data}
        )
        state = _STATE_BY_EVENT.get(event_name)
        if state:
            await self.runtime.async_send(
                "state", {"state": state, "event": event_name}
            )
        if event_name == "STT_VAD_END":
            self.runtime.finish_audio()
        if event_name == "TTS_END" and data.get("url"):
            await self.runtime.async_send(
                "play.url",
                {"url": data["url"], "tts_kind": "response"},
            )

    async def _play_announcement_parts(
        self,
        announcement: assist_satellite.AssistSatelliteAnnouncement,
        *,
        continue_after: bool,
    ) -> None:
        if announcement.preannounce_media_id:
            await self.runtime.async_play_url(
                announcement.preannounce_media_id,
                tts_kind="announcement",
            )
        if continue_after:
            conversation_id = self._conversation_id or ""
            await self.runtime.async_send(
                "voice.event",
                {
                    "event": "INTENT_END",
                    "data": {
                        "conversation_id": conversation_id,
                        "continue_conversation": True,
                    },
                },
            )
        await self.runtime.async_play_url(
            announcement.media_id,
            tts_kind="announcement",
        )

    async def async_announce(
        self, announcement: assist_satellite.AssistSatelliteAnnouncement
    ) -> None:
        """Play an Assist announcement on the satellite."""
        await self._play_announcement_parts(announcement, continue_after=False)

    async def async_start_conversation(
        self, start_announcement: assist_satellite.AssistSatelliteAnnouncement
    ) -> None:
        """Play a prompt and reopen the firmware microphone."""
        await self._play_announcement_parts(start_announcement, continue_after=True)

    @callback
    def _handle_timer_event(self, event_type: TimerEventType, timer: TimerInfo) -> None:
        """Forward Home Assistant timer changes to the device."""
        if event_type in {TimerEventType.STARTED, TimerEventType.UPDATED}:
            if timer.is_active:
                command = "timer.arm"
                payload = {
                    "id": timer.id,
                    "label": timer.name,
                    "remaining_s": timer.seconds_left,
                    "duration_s": timer.created_seconds,
                }
            else:
                command = "timer.clear"
                payload = {"id": timer.id}
        elif event_type is TimerEventType.FINISHED:
            command = "timer.alarm"
            payload = {"id": timer.id, "label": timer.name}
        else:
            command = "timer.clear"
            payload = {"id": timer.id}
        self.hass.async_create_task(
            self.runtime.async_send(command, payload),
            f"tater_satellite_timer_{self.runtime.device_id}",
        )
