"""Synchronized music playback for Tater satellites."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

STEREO_PREFIX = "stereo:"
CLOCK_PROBE_COUNT = 5
START_LEAD_MS = 750
CLOCK_REFRESH_SECONDS = 60.0
ADJUST_INTERVAL_SECONDS = 2.0
ADJUST_THRESHOLD_FRAMES = 48
ADJUST_MAX_FRAMES = 96
ADJUST_SETTLE_MS = 4000
STARTUP_SECONDS = 10.0
STARTUP_THRESHOLD_FRAMES = 24
STARTUP_MAX_FRAMES = 240
STARTUP_SETTLE_MS = 2000
PHASE_EMA_ALPHA = 0.25
PHASE_STABLE_SAMPLES = 2
OUTPUT_LATENCY_MAX_FRAMES = 24_000
OUTPUT_GUARD_MS = 250


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, minimum: int, maximum: int, default: int = 0) -> int:
    return max(minimum, min(maximum, _integer(value, default)))


def _monotonic_us() -> int:
    return time.monotonic_ns() // 1000


def _pair_id(value: Any) -> str:
    token = _text(value).lower()
    if token.startswith(STEREO_PREFIX):
        token = token[len(STEREO_PREFIX) :]
    return "".join(ch for ch in token if ch.isalnum() or ch in {"-", "_"})[:64]


class TaterMediaCoordinator:
    """Coordinate persistent URL playback across firmware render clocks."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self.sessions: dict[str, dict[str, Any]] = {}
        self.sync_tasks: dict[str, asyncio.Task[None]] = {}
        self.entities: dict[str, Any] = {}
        self.dynamic_groups: dict[str, list[str]] = {}
        self._pair_factory: Callable[[dict[str, Any]], Any] | None = None
        self._pair_adder: Callable[[list[Any]], None] | None = None
        self._shared_media_store: Any = None

    def _shared_store(self):
        if self._shared_media_store is None:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            from .shared_media import SharedMediaStore

            self._shared_media_store = SharedMediaStore(
                async_get_clientsession(self.manager.hass),
                Path(self.manager.hass.config.path("tater_satellite", "media_relay")),
            )
        return self._shared_media_store

    async def _create_shared_relay(
        self, source_url: str, duration: float | None, reuse_relay_id: str
    ):
        store = self._shared_store()
        if reuse_relay_id:
            relay = await store.reuse(reuse_relay_id, source_url)
            if relay is not None:
                return relay
        filename = Path(unquote(urlsplit(source_url).path)).name or "media.bin"
        return await store.create(source_url, filename, duration)

    async def async_shared_relay(self, relay_id: str, token: str):
        """Resolve a signed firmware media request without exposing the source URL."""
        if self._shared_media_store is None:
            return None
        return await self._shared_media_store.get(relay_id, token)

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
        """Stop coordinator-owned tasks and fail outstanding requests."""
        for group_id in list(self.sessions):
            await self._stop_group(group_id, reason="bridge_shutdown")
        tasks = list(self.sync_tasks.values())
        self.sync_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.sessions.clear()
        if self._shared_media_store is not None:
            await self._shared_media_store.close()
            self._shared_media_store = None

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

    def list_pairs(self) -> list[dict[str, Any]]:
        """Return saved stereo pairs with live readiness."""
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
                and self._supports_synchronized_media(runtime)
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
        """Create or update a stereo pair."""
        normalized_id = _pair_id(pair_id) or secrets.token_hex(6)
        row = self._normalize_pair(values, normalized_id)
        if not row["name"]:
            raise ValueError("Stereo pair name is required")
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
        pairs[normalized_id] = row
        await self.manager.async_save()
        target = row["target"]
        entity = self.entities.get(target)
        if entity is not None and hasattr(entity, "update_pair"):
            entity.update_pair(row)
        elif self._pair_factory is not None and self._pair_adder is not None:
            self._pair_adder([self._pair_factory(row)])
        return dict(row)

    async def async_remove_pair(self, pair_id: str) -> bool:
        """Remove a saved stereo pair."""
        pairs = self.manager.data.get("stereo_pairs")
        token = _pair_id(pair_id)
        if not isinstance(pairs, dict) or token not in pairs:
            raise KeyError("Stereo pair not found")
        target = f"{STEREO_PREFIX}{token}"
        with contextlib.suppress(Exception):
            await self.async_stop(target)
        pairs.pop(token)
        self._remove_target_from_groups(target)
        await self.manager.async_save()
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
        """Create a synchronized mono group from Home Assistant entities."""
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
        # Standalone satellites reproduce both channels. Satellites added to a
        # multi-room group use mono while explicit stereo pairs retain L/R.
        if len(targets) > 1:
            for route in routes:
                if route["channel"] == "stereo":
                    route["channel"] = "mono"
        return targets, routes

    @staticmethod
    def _supports_synchronized_media(runtime: SatelliteRuntime) -> bool:
        caps = runtime.capabilities
        return bool(
            caps.get("synchronized_media_sessions")
            and caps.get("media_playhead_telemetry")
            and caps.get("media_drift_correction")
            and _integer(caps.get("audio_session_version"), 0) >= 2
        )

    async def _clock_probe(self, runtime: SatelliteRuntime) -> dict[str, Any]:
        best: dict[str, Any] = {}
        for _index in range(CLOCK_PROBE_COUNT):
            server_send_us = _monotonic_us()
            try:
                result = await runtime.async_request(
                    "audio.clock.sync",
                    {"server_send_us": server_send_us},
                    timeout=2.0,
                )
            except (RuntimeError, TimeoutError):
                continue
            server_receive_us = _monotonic_us()
            satellite_receive_us = _integer(result.get("satellite_receive_us"))
            satellite_send_us = _integer(result.get("satellite_send_us"))
            if (
                not result.get("ok")
                or satellite_receive_us <= 0
                or satellite_send_us < satellite_receive_us
            ):
                continue
            processing_us = satellite_send_us - satellite_receive_us
            round_trip_us = max(
                0, server_receive_us - server_send_us - processing_us
            )
            sample = {
                "device_id": runtime.device_id,
                "offset_us": round(
                    (
                        (satellite_receive_us - server_send_us)
                        + (satellite_send_us - server_receive_us)
                    )
                    / 2
                ),
                "round_trip_us": round_trip_us,
            }
            if not best or round_trip_us < _integer(best.get("round_trip_us")):
                best = sample
            await asyncio.sleep(0)
        if not best:
            raise RuntimeError(
                f"Could not synchronize the playback clock for {runtime.name}"
            )
        return best

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
        reuse_relay_id: str = "",
    ) -> dict[str, Any]:
        """Prepare and start one clock-synchronized media session."""
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
            if not self._supports_synchronized_media(runtime):
                raise RuntimeError(
                    f"Update {runtime.name} firmware to enable Tater Audio"
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
                await self._stop_group(
                    group_id, reason="replaced", keep_relay_id=reuse_relay_id
                )

        relay = None
        if len(routes) > 1:
            if not media_url.lower().startswith(("http://", "https://")):
                raise ValueError("Synchronized group playback requires an HTTP media URL")
            relay = await self._create_shared_relay(media_url, duration, reuse_relay_id)

        session_id = secrets.token_hex(12)
        group_id = secrets.token_hex(6)
        base_volume = self.volume_percent(target)
        start_position_ms = max(0, round(float(position_seconds or 0) * 1000))
        session = {
            "group_id": group_id,
            "session_id": session_id,
            "leader_target": target,
            "targets": targets,
            "routes": routes,
            "members": list(runtimes),
            "media_url": media_url,
            "shared_relay_id": relay.id if relay is not None else "",
            "content_type": _text(content_type) or "music",
            "title": _text(title),
            "artist": _text(artist),
            "album": _text(album),
            "image_url": _text(image_url),
            "duration": duration,
            "volume_percent": base_volume,
            "start_position_ms": start_position_ms,
            "state": "buffering",
            "created_us": _monotonic_us(),
            "playheads": {},
            "pending_rejoin": {},
            "finished": set(),
            "phase_ema": {},
            "phase_direction": {},
            "phase_stable": {},
            "clock_offsets_us": {},
            "clock_round_trip_us": {},
            "clock_sync_us": 0,
            "last_adjust_us": 0,
            "actual_starts_us": {},
            "startup_realign_scheduled": False,
        }
        self.sessions[group_id] = session
        for route in routes:
            runtime = runtimes[route["device_id"]]
            runtime.media_session = {
                "active": True,
                "state": "buffering",
                "session_id": session_id,
                "group_id": group_id,
                "channel": route["channel"],
            }
        self.notify()

        try:
            clocks = await asyncio.gather(
                *(self._clock_probe(runtime) for runtime in runtimes.values())
            )
            clock_by_id = {row["device_id"]: row for row in clocks}
            session["clock_offsets_us"] = {
                device_id: _integer(row.get("offset_us"))
                for device_id, row in clock_by_id.items()
            }
            session["clock_round_trip_us"] = {
                device_id: _integer(row.get("round_trip_us"))
                for device_id, row in clock_by_id.items()
            }
            session["clock_sync_us"] = _monotonic_us()

            async def prepare(route: dict[str, Any]) -> dict[str, Any]:
                runtime = runtimes[route["device_id"]]
                volume = round(base_volume * route["trim_percent"] / 100)
                result = await runtime.async_request(
                    "media.session.prepare",
                    {
                        "session_id": session_id,
                        "group_id": group_id,
                        "media": {
                            "url": (
                                relay.url_for(
                                    runtime.server_base_url
                                    or self.manager.public_base_url()
                                )
                                if relay is not None
                                else media_url
                            ),
                            "volume_percent": volume,
                            "start_position_ms": start_position_ms,
                            "loop": False,
                            "content_type": session["content_type"],
                            "title": session["title"],
                            "artist": session["artist"],
                            "album": session["album"],
                        },
                        "routing": {"channel": route["channel"]},
                    },
                    timeout=min(60.0, max(15.0, 8.0 + start_position_ms / 15000)),
                )
                if not result.get("ok"):
                    raise RuntimeError(
                        _text(result.get("error"))
                        or f"{runtime.name} could not prepare the audio"
                    )
                return result

            prepared = await asyncio.gather(*(prepare(route) for route in routes))
            prepared_by_id = {
                route["device_id"]: result
                for route, result in zip(routes, prepared, strict=True)
            }
            latency_us: dict[str, int] = {}
            sample_rates: dict[str, int] = {}
            for device_id, runtime in runtimes.items():
                result = prepared_by_id[device_id]
                sample_rate = max(
                    1,
                    _integer(
                        result.get("sample_rate_hz"),
                        _integer(
                            runtime.capabilities.get("media_sample_rate_hz"), 48000
                        ),
                    ),
                )
                latency_frames = _clamp(
                    result.get("output_latency_frames"),
                    0,
                    OUTPUT_LATENCY_MAX_FRAMES,
                    _integer(
                        runtime.capabilities.get("media_output_latency_frames"), 0
                    ),
                )
                sample_rates[device_id] = sample_rate
                latency_us[device_id] = round(latency_frames * 1_000_000 / sample_rate)
            lead_ms = max(
                START_LEAD_MS,
                max(latency_us.values(), default=0) // 1000 + OUTPUT_GUARD_MS,
            )
            start_server_us = _monotonic_us() + lead_ms * 1000
            session["audible_start_server_us"] = start_server_us
            session["sample_rates"] = sample_rates
            session["latency_us"] = latency_us
            session["startup_realign_supported"] = all(
                runtime.capabilities.get("media_startup_realign")
                for runtime in runtimes.values()
            )
            session["start_position_frames"] = {
                device_id: round(start_position_ms * rate / 1000)
                for device_id, rate in sample_rates.items()
            }

            async def commit(route: dict[str, Any]) -> dict[str, Any]:
                runtime = runtimes[route["device_id"]]
                audible_at_us = (
                    start_server_us
                    + clock_by_id[runtime.device_id]["offset_us"]
                    + route["delay_ms"] * 1000
                )
                result = await runtime.async_request(
                    "media.session.commit",
                    {
                        "session_id": session_id,
                        "group_id": group_id,
                        "start_at_us": audible_at_us - latency_us[runtime.device_id],
                        "audible_start_at_us": audible_at_us,
                    },
                    timeout=3.0,
                )
                if not result.get("ok"):
                    raise RuntimeError(
                        _text(result.get("error"))
                        or f"{runtime.name} rejected synchronized playback"
                    )
                return result

            await asyncio.gather(*(commit(route) for route in routes))
        except Exception:
            await self._stop_group(group_id, reason="start_failed")
            raise

        task = self.manager.entry.async_create_background_task(
            self.manager.hass,
            self._sync_loop(group_id),
            f"tater_media_sync_{group_id}",
        )
        self.sync_tasks[group_id] = task
        self.notify()
        return session

    async def _stop_group(
        self, group_id: str, *, reason: str, keep_relay_id: str = ""
    ) -> None:
        session = self.sessions.pop(group_id, None)
        task = self.sync_tasks.pop(group_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        if not isinstance(session, dict):
            return
        session_id = _text(session.get("session_id"))
        members = list(session.get("members") or [])
        await asyncio.gather(
            *(
                runtime.async_send(
                    "media.session.stop",
                    {"session_id": session_id, "reason": reason},
                )
                for device_id in members
                if (runtime := self.manager.runtimes.get(device_id)) is not None
                and runtime.connected
            ),
            return_exceptions=True,
        )
        for device_id in members:
            runtime = self.manager.runtimes.get(device_id)
            if (
                runtime is not None
                and _text(runtime.media_session.get("session_id")) == session_id
            ):
                runtime.media_session = {}
        relay_id = _text(session.get("shared_relay_id"))
        if (
            relay_id
            and relay_id != keep_relay_id
            and self._shared_media_store is not None
        ):
            await self._shared_media_store.release(relay_id)
        self.notify()

    async def async_stop(self, target: str) -> None:
        """Stop the session controlled by a logical player."""
        session = self.session_for_target(target)
        if session:
            await self._stop_group(_text(session.get("group_id")), reason="user_stop")

    async def async_seek(self, target: str, position: float) -> None:
        """Restart an active URL session at a requested position."""
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
            reuse_relay_id=_text(session.get("shared_relay_id")),
        )

    def session_for_target(self, target: str) -> dict[str, Any]:
        targets = set(self.group_for_target(target))
        for session in reversed(list(self.sessions.values())):
            if targets.intersection(session.get("targets") or []) or target in set(
                session.get("members") or []
            ):
                return session
        return {}

    def volume_percent(self, target: str) -> int:
        session = self.session_for_target(target)
        if session:
            return _clamp(session.get("volume_percent"), 0, 100, 80)
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
        volume = _clamp(volume_percent, 0, 100)
        session = self.session_for_target(target)
        if session:
            session_id = _text(session.get("session_id"))
            routes = list(session.get("routes") or [])
            results = await asyncio.gather(
                *(
                    self.manager.runtimes[route["device_id"]].async_request(
                        "media.session.volume",
                        {
                            "session_id": session_id,
                            "volume_percent": round(
                                volume * route["trim_percent"] / 100
                            ),
                        },
                        timeout=2.0,
                    )
                    for route in routes
                )
            )
            if not all(result.get("ok") for result in results):
                raise RuntimeError("One or more satellites rejected the volume change")
            session["volume_percent"] = volume
        else:
            await asyncio.gather(
                *(
                    self.manager.async_set_device_settings(
                        route["device_id"], {"volume_percent": volume}
                    )
                    for route in self._routes_for_target(target)
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
        """Record firmware media lifecycle and playhead messages."""
        if kind not in {
            "media.session.started",
            "media.session.playhead",
            "media.session.finished",
        }:
            return False
        group_id = _text(payload.get("group_id")) or _text(
            runtime.media_session.get("group_id")
        )
        session = self.sessions.get(group_id)
        if kind == "media.session.started":
            runtime.media_session = {
                **runtime.media_session,
                **payload,
                "active": True,
                "state": "playing",
            }
            if session is not None:
                session["state"] = "playing"
                session["actual_starts_us"][runtime.device_id] = _integer(
                    payload.get("actual_start_us")
                )
                if (
                    session.get("startup_realign_supported")
                    and not session.get("startup_realign_scheduled")
                    and all(
                        _integer(session["actual_starts_us"].get(device_id)) > 0
                        for device_id in session["members"]
                    )
                ):
                    session["startup_realign_scheduled"] = True
                    self.manager.entry.async_create_background_task(
                        self.manager.hass,
                        self._realign_startup(group_id),
                        f"tater_media_startup_realign_{group_id}",
                    )
        elif kind == "media.session.playhead":
            previous = (
                session["playheads"].get(runtime.device_id, {})
                if session is not None
                else {}
            )
            runtime.media_session = {
                **runtime.media_session,
                "active": True,
                "state": "playing",
                "playhead": dict(payload),
                "playhead_received_us": _monotonic_us(),
            }
            if session is not None:
                session["playheads"][runtime.device_id] = dict(payload)
                stereo_members = {
                    route["device_id"]
                    for route in session["routes"]
                    if route["channel"] in {"left", "right"}
                }
                if runtime.device_id in stereo_members and (
                    (previous.get("rebuffering") and not payload.get("rebuffering"))
                    or _integer(payload.get("rejoin_count"))
                    > _integer(previous.get("rejoin_count"))
                    or _integer(payload.get("rejoin_frames"))
                    > _integer(previous.get("rejoin_frames"))
                ):
                    session["pending_rejoin"][runtime.device_id] = True
        else:
            runtime.media_session = {
                **runtime.media_session,
                "active": False,
                "state": "idle",
                "ok": bool(payload.get("ok", True)),
            }
            if session is not None:
                session["finished"].add(runtime.device_id)
                if set(session["finished"]) >= set(session["members"]):
                    self.sessions.pop(group_id, None)
                    task = self.sync_tasks.pop(group_id, None)
                    if task is not None:
                        task.cancel()
                    relay_id = _text(session.get("shared_relay_id"))
                    if relay_id and self._shared_media_store is not None:
                        self.manager.entry.async_create_background_task(
                            self.manager.hass,
                            self._shared_media_store.release(relay_id),
                            f"tater_media_relay_release_{relay_id[:8]}",
                        )
        self.notify()
        return True

    async def _realign_startup(self, group_id: str) -> None:
        """Jump a renderer forward after an unusually late audible start."""
        session = self.sessions.get(group_id)
        if not isinstance(session, dict):
            return
        route_by_id = {route["device_id"]: route for route in session["routes"]}
        normalized: dict[str, int] = {}
        for device_id in session["members"]:
            normalized[device_id] = (
                _integer(session["actual_starts_us"].get(device_id))
                - _integer(session["clock_offsets_us"].get(device_id))
                + _integer(session["latency_us"].get(device_id))
                - route_by_id[device_id]["delay_ms"] * 1000
            )
        reference = min(normalized, key=lambda device_id: normalized[device_id])
        reference_us = normalized[reference]
        for device_id, actual_us in normalized.items():
            late_us = actual_us - reference_us
            if late_us < 40_000:
                continue
            runtime = self.manager.runtimes.get(device_id)
            if runtime is None or not runtime.connected:
                continue
            correction = round(
                min(2_000_000, late_us)
                * session["sample_rates"][device_id]
                / 1_000_000
            )
            with contextlib.suppress(Exception):
                await runtime.async_request(
                    "media.session.adjust",
                    {
                        "session_id": session["session_id"],
                        "group_id": group_id,
                        "correction_frames": correction,
                        "mode": "jump",
                        "settle_ms": 0,
                        "reference_selector": reference,
                        "reason": "startup_realign",
                    },
                    timeout=2.0,
                )

    async def async_handle_disconnect(self, runtime: SatelliteRuntime) -> None:
        """Abort a synchronized group when one renderer disappears."""
        group_id = _text(runtime.media_session.get("group_id"))
        if group_id in self.sessions:
            await self._stop_group(group_id, reason="member_disconnected")

    async def _refresh_clocks(self, session: dict[str, Any]) -> None:
        samples = await asyncio.gather(
            *(
                self._clock_probe(self.manager.runtimes[device_id])
                for device_id in session["members"]
            ),
            return_exceptions=True,
        )
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            device_id = sample["device_id"]
            session["clock_offsets_us"][device_id] = sample["offset_us"]
            session["clock_round_trip_us"][device_id] = sample["round_trip_us"]
        session["clock_sync_us"] = _monotonic_us()

    async def _sync_loop(self, group_id: str) -> None:
        try:
            while (session := self.sessions.get(group_id)) is not None:
                await asyncio.sleep(ADJUST_INTERVAL_SECONDS)
                now_us = _monotonic_us()
                if (
                    now_us - session["clock_sync_us"]
                    >= CLOCK_REFRESH_SECONDS * 1_000_000
                ):
                    await self._refresh_clocks(session)
                playheads = session["playheads"]
                if any(device_id not in playheads for device_id in session["members"]):
                    continue
                startup = (
                    now_us - session["audible_start_server_us"]
                    < STARTUP_SECONDS * 1_000_000
                )
                threshold = (
                    STARTUP_THRESHOLD_FRAMES if startup else ADJUST_THRESHOLD_FRAMES
                )
                maximum = STARTUP_MAX_FRAMES if startup else ADJUST_MAX_FRAMES
                settle_ms = STARTUP_SETTLE_MS if startup else ADJUST_SETTLE_MS
                route_by_id = {route["device_id"]: route for route in session["routes"]}
                adjustments: list[tuple[str, int, str]] = []
                for device_id in session["members"]:
                    row = playheads[device_id]
                    if row.get("rebuffering") or "rendered_frames" not in row:
                        continue
                    sample_rate = max(1, _integer(row.get("sample_rate_hz"), 48000))
                    satellite_time_us = _integer(row.get("satellite_time_us"))
                    event_server_us = satellite_time_us - _integer(
                        session["clock_offsets_us"].get(device_id)
                    )
                    member_start_us = (
                        session["audible_start_server_us"]
                        + route_by_id[device_id]["delay_ms"] * 1000
                    )
                    expected = session["start_position_frames"][device_id] + max(
                        0, event_server_us - member_start_us
                    ) * sample_rate / 1_000_000
                    error = expected - _integer(row.get("rendered_frames"))
                    if device_id in session["pending_rejoin"]:
                        # Wait until the decoder has recovered, then make only
                        # one bounded catch-up jump for this rejoin event.
                        if error > 480:
                            adjustments.append(
                                (device_id, min(24_000, round(error)), "jump")
                            )
                            continue
                        session["pending_rejoin"].pop(device_id, None)
                    previous = float(session["phase_ema"].get(device_id, error))
                    smoothed = (
                        (1 - PHASE_EMA_ALPHA) * previous + PHASE_EMA_ALPHA * error
                    )
                    session["phase_ema"][device_id] = smoothed
                    direction = 1 if smoothed > 0 else -1
                    if abs(smoothed) < threshold:
                        session["phase_direction"][device_id] = 0
                        session["phase_stable"][device_id] = 0
                        continue
                    stable = (
                        _integer(session["phase_stable"].get(device_id)) + 1
                        if session["phase_direction"].get(device_id) == direction
                        else 1
                    )
                    session["phase_direction"][device_id] = direction
                    session["phase_stable"][device_id] = stable
                    if stable >= PHASE_STABLE_SAMPLES:
                        adjustments.append(
                            (
                                device_id,
                                max(-maximum, min(maximum, round(smoothed))),
                                "slew",
                            )
                        )
                for device_id, correction, correction_mode in adjustments:
                    runtime = self.manager.runtimes.get(device_id)
                    if runtime is None or not runtime.connected:
                        continue
                    with contextlib.suppress(Exception):
                        result = await runtime.async_request(
                            "media.session.adjust",
                            {
                                "session_id": session["session_id"],
                                "group_id": group_id,
                                "correction_frames": correction,
                                "mode": (
                                    "jump"
                                    if correction_mode == "jump"
                                    else (
                                        "slew"
                                        if runtime.capabilities.get("media_rate_slew")
                                        else "legacy"
                                    )
                                ),
                                "settle_ms": settle_ms,
                                "reference_selector": "home-assistant:audible-timeline",
                            },
                            timeout=2.0,
                        )
                        if result.get("ok"):
                            session["phase_stable"][device_id] = 0
                            if correction_mode == "jump":
                                session["pending_rejoin"].pop(device_id, None)
                if adjustments:
                    session["last_adjust_us"] = now_us
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Tater synchronized playback monitor failed")
        finally:
            if self.sync_tasks.get(group_id) is asyncio.current_task():
                self.sync_tasks.pop(group_id, None)
