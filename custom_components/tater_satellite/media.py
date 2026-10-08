"""Sendspin music playback, stereo pairs, and groups for Tater satellites."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

STEREO_PREFIX = "stereo:"
SENDSPIN_PORT = 8928


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, minimum: int, maximum: int, default: int = 0) -> int:
    return max(minimum, min(maximum, _integer(value, default)))


def _pair_id(value: Any) -> str:
    token = _text(value).lower()
    if token.startswith(STEREO_PREFIX):
        token = token[len(STEREO_PREFIX) :]
    return "".join(ch for ch in token if ch.isalnum() or ch in {"-", "_"})[:64]


class TaterMediaCoordinator:
    """Coordinate Home Assistant media players through one Sendspin timeline."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self.sessions: dict[str, dict[str, Any]] = {}
        self.entities: dict[str, Any] = {}
        self.dynamic_groups: dict[str, list[str]] = {}
        self._pair_factory: Callable[[dict[str, Any]], Any] | None = None
        self._pair_adder: Callable[[list[Any]], None] | None = None

    def setup(self) -> None:
        """Normalize stored stereo-pair records."""
        raw = self.manager.data.setdefault("stereo_pairs", {})
        if not isinstance(raw, dict):
            raw = {}
        normalized: dict[str, dict[str, Any]] = {}
        for raw_id, value in raw.items():
            if not isinstance(value, dict):
                continue
            pair_id = _pair_id(value.get("id") or raw_id)
            left = _text(value.get("left_device_id"))
            right = _text(value.get("right_device_id"))
            if not pair_id or not left or not right or left == right:
                continue
            normalized[pair_id] = self._normalize_pair(value, pair_id)
        self.manager.data["stereo_pairs"] = normalized

    async def async_shutdown(self) -> None:
        """Stop every coordinator-owned Sendspin stream."""
        for group_id in list(self.sessions):
            await self._stop_group(group_id, reason="bridge_shutdown")
        self.sessions.clear()

    @staticmethod
    def _normalize_pair(value: dict[str, Any], pair_id: str) -> dict[str, Any]:
        return {
            "id": pair_id,
            "target": f"{STEREO_PREFIX}{pair_id}",
            "name": _text(value.get("name"))[:80] or "Tater Stereo Pair",
            "left_device_id": _text(value.get("left_device_id")),
            "right_device_id": _text(value.get("right_device_id")),
            "left_delay_ms": _clamp(value.get("left_delay_ms"), 0, 250),
            "right_delay_ms": _clamp(value.get("right_delay_ms"), 0, 250),
            "left_volume_percent": _clamp(
                value.get("left_volume_percent"), 0, 100, 100
            ),
            "right_volume_percent": _clamp(
                value.get("right_volume_percent"), 0, 100, 100
            ),
        }

    @staticmethod
    def _supports_sendspin(
        runtime: SatelliteRuntime, *, channel_selection: bool = False
    ) -> bool:
        caps = runtime.capabilities
        supported = bool(
            caps.get("sendspin_player")
            and _integer(caps.get("sendspin_version"), 0) >= 1
        )
        if channel_selection:
            supported = supported and bool(
                caps.get("sendspin_output_channel_selection")
            )
        return supported

    def output_channel_mode(self, device_id: str) -> str:
        """Return the persistent Sendspin output route for one satellite."""
        for pair in self.list_pairs():
            if pair["left_device_id"] == device_id:
                return "left"
            if pair["right_device_id"] == device_id:
                return "right"
        return "stereo"

    async def _push_output_modes(self, device_ids: set[str]) -> None:
        """Apply changed pair channel assignments to connected firmware."""
        push = getattr(self.manager, "async_push_settings", None)
        if not callable(push):
            return
        connected = [
            runtime
            for device_id in sorted(device_ids)
            if (runtime := self.manager.runtimes.get(device_id)) is not None
            and runtime.connected
        ]
        if not connected:
            return
        results = await asyncio.gather(
            *(push(runtime) for runtime in connected), return_exceptions=True
        )
        failed = [
            runtime.name
            for runtime, result in zip(connected, results, strict=True)
            if result is not True
        ]
        if failed:
            raise RuntimeError(
                "Stereo pair was saved, but its Sendspin channel could not be "
                "sent to: " + ", ".join(failed)
            )

    def list_pairs(self) -> list[dict[str, Any]]:
        """Return saved stereo pairs with live Sendspin readiness."""
        pairs = self.manager.data.get("stereo_pairs")
        if not isinstance(pairs, dict):
            return []
        rows: list[dict[str, Any]] = []
        for value in pairs.values():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            members = [row["left_device_id"], row["right_device_id"]]
            row["ready"] = all(
                (runtime := self.manager.runtimes.get(device_id)) is not None
                and runtime.connected
                and self._supports_sendspin(runtime, channel_selection=True)
                and bool(runtime.remote)
                for device_id in members
            )
            row["members"] = [
                {
                    "device_id": device_id,
                    "name": (
                        self.manager.runtimes[device_id].name
                        if device_id in self.manager.runtimes
                        else device_id
                    ),
                    "connected": bool(
                        device_id in self.manager.runtimes
                        and self.manager.runtimes[device_id].connected
                    ),
                }
                for device_id in members
            ]
            rows.append(row)
        return sorted(rows, key=lambda row: _text(row.get("name")).lower())

    def get_pair(self, target_or_id: str) -> dict[str, Any]:
        """Resolve a saved stereo pair."""
        pairs = self.manager.data.get("stereo_pairs")
        row = pairs.get(_pair_id(target_or_id)) if isinstance(pairs, dict) else None
        return dict(row) if isinstance(row, dict) else {}

    async def async_save_pair(
        self, values: dict[str, Any], pair_id: str = ""
    ) -> dict[str, Any]:
        """Create or update a stereo pair and push its Sendspin channel modes."""
        normalized_id = _pair_id(pair_id) or secrets.token_hex(6)
        row = self._normalize_pair(values, normalized_id)
        left = row["left_device_id"]
        right = row["right_device_id"]
        if left not in self.manager.runtimes or right not in self.manager.runtimes:
            raise ValueError("Choose two paired Tater satellites")
        if left == right:
            raise ValueError("Left and right satellites must be different")
        for existing in self.list_pairs():
            if existing["id"] == normalized_id:
                continue
            occupied = {
                existing["left_device_id"],
                existing["right_device_id"],
            }
            if left in occupied or right in occupied:
                raise ValueError(
                    "Each satellite can belong to only one saved stereo pair"
                )
        pairs = self.manager.data.setdefault("stereo_pairs", {})
        previous = pairs.get(normalized_id)
        affected = {left, right}
        if isinstance(previous, dict):
            affected.update(
                {
                    _text(previous.get("left_device_id")),
                    _text(previous.get("right_device_id")),
                }
            )
        pairs[normalized_id] = row
        await self.manager.async_save()
        await self._push_output_modes({value for value in affected if value})
        target = row["target"]
        entity = self.entities.get(target)
        if entity is not None and hasattr(entity, "update_pair"):
            entity.update_pair(row)
        elif self._pair_factory is not None and self._pair_adder is not None:
            self._pair_adder([self._pair_factory(row)])
        return dict(row)

    async def async_remove_pair(self, pair_id: str) -> bool:
        """Remove a saved pair and return its members to stereo output."""
        pairs = self.manager.data.get("stereo_pairs")
        token = _pair_id(pair_id)
        if not isinstance(pairs, dict) or token not in pairs:
            raise KeyError("Stereo pair not found")
        pair = dict(pairs[token])
        target = f"{STEREO_PREFIX}{token}"
        with contextlib.suppress(Exception):
            await self.async_stop(target)
        pairs.pop(token)
        self._remove_target_from_groups(target)
        await self.manager.async_save()
        await self._push_output_modes(
            {pair["left_device_id"], pair["right_device_id"]}
        )
        entity = self.entities.get(target)
        if entity is not None and getattr(entity, "hass", None) is not None:
            await entity.async_remove(force_remove=True)
            if getattr(entity, "registry_entry", None) is not None:
                from homeassistant.helpers import entity_registry

                entity_registry.async_get(self.manager.hass).async_remove(
                    entity.entity_id
                )
        return True

    def register_entity(self, target: str, entity: Any) -> None:
        """Track a media-player entity for grouping and state refreshes."""
        self.entities[target] = entity

    def register_pair_platform(
        self,
        factory: Callable[[dict[str, Any]], Any],
        add_entities: Callable[[list[Any]], None],
    ) -> None:
        """Register the virtual-pair entity factory and add saved pairs."""
        self._pair_factory = factory
        self._pair_adder = add_entities
        pairs = [factory(pair) for pair in self.list_pairs()]
        if pairs:
            add_entities(pairs)

    def unregister_entity(self, target: str, entity: Any) -> None:
        if self.entities.get(target) is entity:
            self.entities.pop(target, None)

    def notify(self) -> None:
        """Refresh all media-player entities."""
        for entity in tuple(self.entities.values()):
            if getattr(entity, "hass", None) is not None:
                with contextlib.suppress(Exception):
                    entity.async_write_ha_state()

    def target_from_entity_id(self, entity_id: str) -> str:
        for target, entity in self.entities.items():
            if getattr(entity, "entity_id", "") == entity_id:
                return target
        return ""

    def _remove_target_from_groups(self, target: str) -> None:
        for leader, members in list(self.dynamic_groups.items()):
            if leader == target:
                self.dynamic_groups.pop(leader, None)
                continue
            if target in members:
                next_members = [member for member in members if member != target]
                if len(next_members) < 2:
                    self.dynamic_groups.pop(leader, None)
                else:
                    self.dynamic_groups[leader] = next_members

    def group_for_target(self, target: str) -> list[str]:
        for leader, members in self.dynamic_groups.items():
            if target == leader or target in members:
                return list(members)
        return [target]

    def group_entity_ids(self, target: str) -> list[str] | None:
        targets = self.group_for_target(target)
        if len(targets) < 2:
            return None
        entity_ids = [
            getattr(self.entities.get(item), "entity_id", "") for item in targets
        ]
        return [entity_id for entity_id in entity_ids if entity_id]

    async def async_join(self, leader: str, member_entity_ids: list[str]) -> None:
        """Create a Sendspin-synchronized group from Home Assistant entities."""
        members = [leader]
        for entity_id in member_entity_ids:
            target = self.target_from_entity_id(entity_id)
            if not target:
                raise ValueError(f"{entity_id} is not a Tater media player")
            if target not in members:
                members.append(target)
        if len(members) < 2:
            return
        physical: set[str] = set()
        for target in members:
            for route in self._routes_for_target(target):
                device_id = route["device_id"]
                if device_id in physical:
                    raise ValueError(
                        "A satellite cannot appear twice in one audio group"
                    )
                physical.add(device_id)
        for target in members:
            self._remove_target_from_groups(target)
        self.dynamic_groups[leader] = members
        self.notify()

    async def async_unjoin(self, target: str) -> None:
        """Remove one logical player from its synchronized group."""
        self._remove_target_from_groups(target)
        self.notify()

    def _routes_for_target(self, target: str) -> list[dict[str, Any]]:
        if target.startswith(STEREO_PREFIX):
            pair = self.get_pair(target)
            if not pair:
                raise ValueError("Stereo pair no longer exists")
            return [
                {
                    "device_id": pair["left_device_id"],
                    "channel": "left",
                    "delay_ms": pair["left_delay_ms"],
                    "trim_percent": pair["left_volume_percent"],
                },
                {
                    "device_id": pair["right_device_id"],
                    "channel": "right",
                    "delay_ms": pair["right_delay_ms"],
                    "trim_percent": pair["right_volume_percent"],
                },
            ]
        if target not in self.manager.runtimes:
            raise ValueError("Tater media player no longer exists")
        return [
            {
                "device_id": target,
                "channel": "stereo",
                "delay_ms": 0,
                "trim_percent": 100,
            }
        ]

    def _play_routes(self, target: str) -> tuple[list[str], list[dict[str, Any]]]:
        targets = self.group_for_target(target)
        routes: list[dict[str, Any]] = []
        for item in targets:
            routes.extend(self._routes_for_target(item))
        # A standalone speaker in a multi-room group gets a mono fold-down.
        # Saved stereo pairs keep their persistent left/right output modes.
        if len(targets) > 1:
            for route in routes:
                if route["channel"] == "stereo":
                    route["channel"] = "mono"
        return targets, routes

    def _ffmpeg_binary(self) -> str:
        from homeassistant.components.ffmpeg import get_ffmpeg_manager

        return _text(get_ffmpeg_manager(self.manager.hass).binary)

    def _new_stream(
        self,
        session: dict[str, Any],
        routes: list[dict[str, Any]],
        runtimes: dict[str, SatelliteRuntime],
    ) -> Any:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        from .sendspin import SendspinStream

        targets = [
            {
                **route,
                "host": runtimes[route["device_id"]].remote,
                "port": SENDSPIN_PORT,
            }
            for route in routes
        ]

        async def finished(error: str) -> None:
            await self._stream_finished(session["group_id"], error)

        return SendspinStream(
            async_get_clientsession(self.manager.hass),
            self._ffmpeg_binary(),
            session["media_url"],
            targets,
            group_id=session["group_id"],
            group_name=session["title"] or "Tater Audio",
            start_position_seconds=session["start_position_seconds"],
            duration_seconds=session["duration"],
            on_finished=finished,
        )

    async def async_play(
        self,
        target: str,
        media_url: str,
        *,
        content_type: str = "music",
        title: str = "",
        artist: str = "",
        album: str = "",
        image_url: str = "",
        duration: float | None = None,
        position_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Start one Sendspin timeline for a player, pair, or group."""
        if not _text(media_url):
            raise ValueError("A playable media URL is required")
        targets, routes = self._play_routes(target)
        runtimes: dict[str, SatelliteRuntime] = {}
        for route in routes:
            runtime = self.manager.runtimes.get(route["device_id"])
            if runtime is None or not runtime.connected:
                raise RuntimeError(
                    f"{runtime.name if runtime else route['device_id']} is offline"
                )
            if not self._supports_sendspin(
                runtime, channel_selection=route["channel"] in {"left", "right"}
            ):
                raise RuntimeError(
                    f"Update {runtime.name} firmware to enable Sendspin audio"
                )
            if not _text(runtime.remote):
                raise RuntimeError(
                    f"{runtime.name} has no reachable Sendspin address"
                )
            runtimes[runtime.device_id] = runtime

        overlapping = {
            _text(runtime.media_session.get("group_id"))
            for runtime in runtimes.values()
            if isinstance(runtime.media_session, dict)
            and runtime.media_session.get("active")
        }
        for group_id in overlapping:
            if group_id:
                await self._stop_group(group_id, reason="replaced")

        group_id = secrets.token_hex(6)
        try:
            normalized_duration = (
                max(0.0, float(duration)) if duration is not None else None
            )
        except (TypeError, ValueError):
            normalized_duration = None
        session: dict[str, Any] = {
            "group_id": group_id,
            "leader_target": target,
            "targets": targets,
            "routes": routes,
            "members": list(runtimes),
            "media_url": media_url,
            "content_type": _text(content_type) or "music",
            "title": _text(title),
            "artist": _text(artist),
            "album": _text(album),
            "image_url": _text(image_url),
            "duration": normalized_duration,
            "start_position_seconds": max(0.0, float(position_seconds or 0)),
            "state": "buffering",
        }
        self.sessions[group_id] = session
        for route in routes:
            runtime = runtimes[route["device_id"]]
            runtime.media_session = {
                "active": True,
                "state": "buffering",
                "group_id": group_id,
                "channel": route["channel"],
                "transport": "sendspin",
            }
        self.notify()

        try:
            stream = self._new_stream(session, routes, runtimes)
            session["stream"] = stream
            task = self.manager.entry.async_create_background_task(
                self.manager.hass,
                stream.run(),
                f"tater_sendspin_{group_id}",
            )
            stream.bind_task(task)
            await stream.wait_started()
        except Exception:
            await self._stop_group(group_id, reason="start_failed")
            raise

        if group_id not in self.sessions:
            raise RuntimeError("Sendspin playback ended before it could start")
        session["state"] = "playing"
        for runtime in runtimes.values():
            runtime.media_session["state"] = "playing"
        self.notify()
        return session

    async def _stream_finished(self, group_id: str, error: str) -> None:
        session = self.sessions.pop(group_id, None)
        if not isinstance(session, dict):
            return
        for device_id in session.get("members") or []:
            runtime = self.manager.runtimes.get(device_id)
            if runtime is None:
                continue
            if _text(runtime.media_session.get("group_id")) == group_id:
                runtime.media_session = {}
            if error:
                runtime.last_error = error
        self.notify()

    async def _stop_group(self, group_id: str, *, reason: str) -> None:
        del reason
        session = self.sessions.pop(group_id, None)
        if not isinstance(session, dict):
            return
        stream = session.get("stream")
        if stream is not None:
            await stream.stop()
        for device_id in session.get("members") or []:
            runtime = self.manager.runtimes.get(device_id)
            if (
                runtime is not None
                and _text(runtime.media_session.get("group_id")) == group_id
            ):
                runtime.media_session = {}
        self.notify()

    async def async_stop(self, target: str) -> None:
        """Stop the Sendspin session controlled by a logical player."""
        session = self.session_for_target(target)
        if session:
            await self._stop_group(_text(session.get("group_id")), reason="user_stop")

    async def async_seek(self, target: str, position: float) -> None:
        """Restart an active Sendspin source at a requested position."""
        session = dict(self.session_for_target(target))
        if not session:
            raise RuntimeError("No active media session to seek")
        await self.async_play(
            target,
            _text(session.get("media_url")),
            content_type=_text(session.get("content_type")),
            title=_text(session.get("title")),
            artist=_text(session.get("artist")),
            album=_text(session.get("album")),
            image_url=_text(session.get("image_url")),
            duration=session.get("duration"),
            position_seconds=max(0.0, float(position)),
        )

    def session_for_target(self, target: str) -> dict[str, Any]:
        targets = set(self.group_for_target(target))
        for session in reversed(list(self.sessions.values())):
            if targets.intersection(session.get("targets") or []) or target in set(
                session.get("members") or []
            ):
                return session
        return {}

    def media_position(self, target: str) -> float | None:
        """Return the source position derived from the Sendspin timeline."""
        session = self.session_for_target(target)
        if not session:
            return None
        stream = session.get("stream")
        if stream is None:
            return float(session.get("start_position_seconds") or 0)
        return float(stream.position_seconds())

    def volume_percent(self, target: str) -> int:
        routes = self._routes_for_target(target)
        volumes = [
            _clamp(
                self.manager.runtimes[route["device_id"]]
                .effective_settings()
                .get("volume_percent"),
                0,
                100,
                80,
            )
            for route in routes
            if route["device_id"] in self.manager.runtimes
        ]
        return round(sum(volumes) / len(volumes)) if volumes else 0

    def muted(self, target: str) -> bool:
        routes = self._routes_for_target(target)
        return bool(routes) and all(
            bool(
                self.manager.runtimes[route["device_id"]]
                .effective_settings()
                .get("muted")
            )
            for route in routes
            if route["device_id"] in self.manager.runtimes
        )

    async def async_set_volume(self, target: str, volume_percent: int) -> None:
        """Set the satellites' one device volume, including during Sendspin."""
        volume = _clamp(volume_percent, 0, 100)
        session = self.session_for_target(target)
        routes = (
            list(session.get("routes") or [])
            if session
            else self._routes_for_target(target)
        )
        device_ids = list(
            dict.fromkeys(_text(route.get("device_id")) for route in routes)
        )
        await asyncio.gather(
            *(
                self.manager.async_set_device_settings(
                    device_id, {"volume_percent": volume}
                )
                for device_id in device_ids
                if device_id
            )
        )
        self.notify()

    async def async_set_muted(self, target: str, muted: bool) -> None:
        await asyncio.gather(
            *(
                self.manager.async_set_device_settings(
                    route["device_id"], {"muted": bool(muted)}
                )
                for route in self._routes_for_target(target)
            )
        )
        self.notify()

    def handle_message(
        self, runtime: SatelliteRuntime, kind: str, payload: dict[str, Any]
    ) -> bool:
        """Sendspin lifecycle travels on its own socket, not the Tater control link."""
        del runtime, kind, payload
        return False

    async def async_handle_disconnect(self, runtime: SatelliteRuntime) -> None:
        """Abort a Sendspin group when one selected satellite disconnects."""
        group_id = _text(runtime.media_session.get("group_id"))
        if group_id in self.sessions:
            await self._stop_group(group_id, reason="member_disconnected")
