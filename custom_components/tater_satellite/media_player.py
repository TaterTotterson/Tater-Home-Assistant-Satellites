"""Media-player entities for Sendspin Tater Audio playback."""

from __future__ import annotations

from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    async_process_play_media_url,
)
from homeassistant.components.media_player.browse_media import BrowseMedia
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager

_FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.GROUPING
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up physical and saved stereo Tater players."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "media_player",
        lambda runtime: [TaterSatelliteMediaPlayer(runtime)],
        async_add_entities,
    )
    manager.media.register_pair_platform(
        lambda pair: TaterStereoMediaPlayer(manager, pair), async_add_entities
    )


class _TaterMediaPlayerMixin(MediaPlayerEntity):
    """Shared Home Assistant media-player behavior."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = _FEATURES
    _attr_should_poll = False
    target: str
    manager: TaterSatelliteManager

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.manager.media.register_entity(self.target, self)

    async def async_will_remove_from_hass(self) -> None:
        self.manager.media.unregister_entity(self.target, self)
        await super().async_will_remove_from_hass()

    @property
    def state(self) -> MediaPlayerState:
        session = self.manager.media.session_for_target(self.target)
        if session.get("state") == "buffering":
            return MediaPlayerState.BUFFERING
        if session:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float:
        return self.manager.media.volume_percent(self.target) / 100

    @property
    def is_volume_muted(self) -> bool:
        return self.manager.media.muted(self.target)

    @property
    def group_members(self) -> list[str] | None:
        return self.manager.media.group_entity_ids(self.target)

    def _session(self) -> dict[str, Any]:
        return self.manager.media.session_for_target(self.target)

    @property
    def media_content_id(self) -> str | None:
        return str(self._session().get("media_url") or "") or None

    @property
    def media_content_type(self) -> str | None:
        return str(self._session().get("content_type") or "") or None

    @property
    def media_title(self) -> str | None:
        return str(self._session().get("title") or "") or None

    @property
    def media_artist(self) -> str | None:
        return str(self._session().get("artist") or "") or None

    @property
    def media_album_name(self) -> str | None:
        return str(self._session().get("album") or "") or None

    @property
    def media_image_url(self) -> str | None:
        return str(self._session().get("image_url") or "") or None

    @property
    def media_duration(self) -> float | None:
        value = self._session().get("duration")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def media_position(self) -> float | None:
        return self.manager.media.media_position(self.target)

    @property
    def media_position_updated_at(self):
        return dt_util.utcnow() if self._session().get("state") == "playing" else None

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        enqueue: MediaPlayerEnqueue | None = None,
        announce: bool | None = None,
        **kwargs: Any,
    ) -> None:
        del enqueue, announce
        if media_source.is_media_source_id(media_id):
            play_item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            media_id = play_item.url
            media_type = MediaType.MUSIC
        media_url = async_process_play_media_url(self.hass, media_id)
        extra = kwargs.get("extra") if isinstance(kwargs.get("extra"), dict) else {}

        def metadata(key: str) -> Any:
            return extra.get(key, kwargs.get(key))

        await self.manager.media.async_play(
            self.target,
            media_url,
            content_type=str(media_type or MediaType.MUSIC),
            title=str(metadata("title") or metadata("media_title") or ""),
            artist=str(metadata("artist") or metadata("media_artist") or ""),
            album=str(
                metadata("album")
                or metadata("album_name")
                or metadata("media_album_name")
                or ""
            ),
            image_url=str(
                metadata("image_url")
                or metadata("media_image_url")
                or metadata("thumbnail")
                or ""
            ),
            duration=metadata("duration") or metadata("media_duration"),
        )

    async def async_media_stop(self) -> None:
        await self.manager.media.async_stop(self.target)

    async def async_media_seek(self, position: float) -> None:
        await self.manager.media.async_seek(self.target, position)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.manager.media.async_set_volume(
            self.target, round(max(0.0, min(1.0, volume)) * 100)
        )

    async def async_mute_volume(self, mute: bool) -> None:
        await self.manager.media.async_set_muted(self.target, mute)

    async def async_join_players(self, group_members: list[str]) -> None:
        await self.manager.media.async_join(self.target, group_members)

    async def async_unjoin_player(self) -> None:
        await self.manager.media.async_unjoin(self.target)


class TaterSatelliteMediaPlayer(
    _TaterMediaPlayerMixin, TaterSatelliteEntity
):
    """A physical satellite speaker."""

    _attr_name = "Media Player"
    _attr_has_entity_name = True

    def __init__(self, runtime: SatelliteRuntime) -> None:
        TaterSatelliteEntity.__init__(self, runtime, "media_player")
        self.runtime = runtime
        self.manager = runtime.manager
        self.target = runtime.device_id

    @property
    def available(self) -> bool:
        return (
            self.runtime.connected
            and self.runtime.capabilities.get("speaker", True) is not False
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self._session()
        return {
            **TaterSatelliteEntity.extra_state_attributes.fget(self),
            "tater_audio": True,
            "sendspin_version": self.runtime.capabilities.get("sendspin_version"),
            "media_transport": "sendspin",
            "media_group_id": session.get("group_id"),
            "media_channel": self.runtime.media_session.get("channel"),
        }


class TaterStereoMediaPlayer(_TaterMediaPlayerMixin):
    """A saved left/right Tater satellite pair."""

    _attr_has_entity_name = False

    def __init__(self, manager: TaterSatelliteManager, pair: dict[str, Any]) -> None:
        self.manager = manager
        self.pair = dict(pair)
        self.target = str(pair["target"])
        self._attr_unique_id = f"stereo_pair_{pair['id']}"
        self._attr_name = str(pair["name"])

    def update_pair(self, pair: dict[str, Any]) -> None:
        """Apply an edited pair without reloading the integration."""
        self.pair = dict(pair)
        self._attr_name = str(pair["name"])
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        for device_id in (
            self.pair["left_device_id"],
            self.pair["right_device_id"],
        ):
            runtime = self.manager.runtimes.get(device_id)
            if (
                runtime is None
                or not runtime.connected
                or not self.manager.media._supports_sendspin(
                    runtime, channel_selection=True
                )
                or not runtime.remote
            ):
                return False
        return True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.target)},
            name=str(self.pair["name"]),
            manufacturer="Tater",
            model="Sendspin Stereo Pair",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self._session()
        return {
            "tater_audio": True,
            "left_device_id": self.pair["left_device_id"],
            "right_device_id": self.pair["right_device_id"],
            "left_delay_ms": self.pair["left_delay_ms"],
            "right_delay_ms": self.pair["right_delay_ms"],
            "media_transport": "sendspin",
            "media_group_id": session.get("group_id"),
        }
