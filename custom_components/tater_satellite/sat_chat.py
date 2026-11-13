"""Low-latency Sat Chat relay for connected Tater satellites."""

from __future__ import annotations

import asyncio
import contextlib
import struct
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import SatelliteRuntime, TaterSatelliteManager

SAMPLE_RATE_HZ = 16_000
CHANNELS = 1
SAMPLE_FORMAT = "s16le"
VIDEO_FRAME_PREFIX = b"TSCV1"
H264_FRAME_PREFIX = b"TSCV2"
H264_HEADER_BYTES = 41
MAX_VIDEO_FRAME_BYTES = 2 * 1024 * 1024
MAX_SAT_CHAT_FRAME_BYTES = len(VIDEO_FRAME_PREFIX) + MAX_VIDEO_FRAME_BYTES
MAX_H264_RELAY_FRAMES = 32


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _valid_h264_frame(data: bytes, *, balanced: bool = False) -> bool:
    if not data.startswith(H264_FRAME_PREFIX) or not (
        H264_HEADER_BYTES + 5 <= len(data) <= H264_HEADER_BYTES + 1024 * 1024
    ):
        return False
    width, height, fps, _sequence, flags, pts, stream_id = struct.unpack_from("<IIIIIQQ", data, 5)
    payload = data[H264_HEADER_BYTES:]
    return (
        (width, height, fps) in ({(768, 432, 30), (640, 480, 30)} if balanced else {(1280, 720, 30), (1280, 960, 30)})
        and flags in (0, 1)
        and pts < 2**63
        and stream_id != 0
        and (payload.startswith(b"\0\0\1") or payload.startswith(b"\0\0\0\1"))
    )


def _h264_capable(runtime: SatelliteRuntime | None) -> bool:
    return (
        runtime is not None
        and _text(runtime.board).lower() in {"checkers", "cronos"}
        and _truthy(runtime.capabilities.get("sat_chat_h264"))
        and runtime.capabilities.get("sat_chat_h264_version") == 1
    )


def _enqueue_video_packet(relay: dict[str, Any], data: bytes) -> None:
    queue = relay["queue"]
    h264 = data.startswith(H264_FRAME_PREFIX)
    if relay.get("h264") != h264:
        relay["h264"] = h264
        relay["waiting_keyframe"] = h264
        while not queue.empty():
            queue.get_nowait()
    if not h264:
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(data)
        return
    keyframe = len(data) >= H264_HEADER_BYTES and struct.unpack_from("<I", data, 21)[0] == 1
    if relay.get("waiting_keyframe") and not keyframe:
        return
    if queue.full():
        # H.264 prediction requires the complete pending GOP. Arbitrarily
        # replacing one frame, as for JPEG, forces needless decoder resets.
        while not queue.empty():
            queue.get_nowait()
        relay["waiting_keyframe"] = True
        if not keyframe:
            return
    queue.put_nowait(data)
    relay["waiting_keyframe"] = False


def _h264_receive_max_height(runtime: SatelliteRuntime) -> int:
    # Cronos v1 was qualified for 960-line capture and 720p from the start.
    # An older Checkers v1 app needs an explicit receiver upgrade first.
    default = 960 if _text(runtime.board).lower() == "cronos" else 720
    maximum = runtime.capabilities.get("sat_chat_h264_receive_max_height")
    return maximum if type(maximum) is int and maximum in (720, 960) else default


def _h264_pair_compatible(caller: SatelliteRuntime, target: SatelliteRuntime) -> bool:
    if not _h264_capable(caller) or not _h264_capable(target):
        return False
    caller_height = 960 if _text(caller.board).lower() == "cronos" else 720
    target_height = 960 if _text(target.board).lower() == "cronos" else 720
    return (_h264_receive_max_height(caller) >= target_height
            and _h264_receive_max_height(target) >= caller_height)


def _video_receive_profile(runtime: SatelliteRuntime | None) -> str:
    board = _text(runtime.board if runtime is not None else "").lower().replace(
        "_", "-"
    )
    if board in {"checkers", "crown", "athena", "rook"}:
        return "echo-low"
    return ""


class TaterSatChatCoordinator:
    """Route transient Sat Chat call state and media between native sockets."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self._lock = asyncio.Lock()
        self._calls: dict[str, dict[str, Any]] = {}
        self._endpoint_calls: dict[str, str] = {}
        self._video_relays: dict[tuple[str, str], dict[str, Any]] = {}
        self._shutting_down = False

    def _participant(
        self, device_id: str, runtime: SatelliteRuntime | None
    ) -> dict[str, Any] | None:
        if runtime is None or not runtime.connected:
            return None
        capabilities = runtime.capabilities
        if not _truthy(capabilities.get("sat_chat_audio")):
            return None
        return {
            "id": device_id,
            "selector": device_id,
            "name": runtime.name,
            "room": runtime.room,
            "board": _text(runtime.board).lower().replace("_", "-"),
            "connected": True,
            "audio": True,
            "video": _truthy(capabilities.get("sat_chat_video")),
            "can_initiate": _truthy(
                capabilities.get("sat_chat_can_initiate")
            ),
            "can_end": _truthy(capabilities.get("sat_chat_can_end")),
            "has_ui": _truthy(capabilities.get("sat_chat_ui")),
            "busy": device_id in self._endpoint_calls,
        }

    @staticmethod
    def _public_call(call: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(call, dict):
            return {}
        return {
            key: value
            for key, value in call.items()
            if not str(key).startswith("_")
        }

    def _endpoint_call(self, call: dict[str, Any], endpoint: str) -> dict[str, Any]:
        public = self._public_call(call)
        caller = _text(call.get("caller"))
        target = _text(call.get("target"))
        peer = target if endpoint == caller else caller
        profiles = call.get("_video_profiles")
        if isinstance(profiles, dict):
            profile = _text(profiles.get(peer))
            if profile:
                public["video_send_profile"] = profile
        return public

    async def async_directory(self, viewer: str) -> dict[str, Any]:
        """Return the connected Sat Chat peers and the viewer's active call."""
        viewer_token = _text(viewer)
        async with self._lock:
            participants = [
                participant
                for device_id, runtime in self.manager.runtimes.items()
                if device_id != viewer_token
                if (participant := self._participant(device_id, runtime)) is not None
            ]
            participants.sort(
                key=lambda row: (
                    _text(row.get("room")).lower(),
                    _text(row.get("name")).lower(),
                )
            )
            call_id = self._endpoint_calls.get(viewer_token, "")
            active_call = self._calls.get(call_id)
            call = (
                self._endpoint_call(active_call, viewer_token)
                if isinstance(active_call, dict)
                else {}
            )
        return {
            "ok": True,
            "protocol": 1,
            "participant_count": len(participants),
            "participants": participants,
            "call": call,
            "media": {
                "audio": True,
                "video": True,
                "video_format": "jpeg",
                "sample_rate_hz": SAMPLE_RATE_HZ,
                "channels": CHANNELS,
                "sample_format": SAMPLE_FORMAT,
            },
        }

    async def async_refresh_directories(self) -> None:
        """Push current peer and busy state to each capable display."""
        if self._shutting_down:
            return
        targets = [
            runtime
            for runtime in tuple(self.manager.runtimes.values())
            if self._participant(runtime.device_id, runtime) is not None
        ]
        for runtime in targets:
            await runtime.async_send(
                "sat_chat.directory",
                await self.async_directory(runtime.device_id),
            )

    async def async_start(
        self, caller: SatelliteRuntime, target: str, *, mode: str = "audio"
    ) -> dict[str, Any]:
        """Start one immediately active satellite-to-satellite call."""
        caller_id = caller.device_id
        target_id = _text(target)
        requested_mode = _text(mode).lower() or "audio"
        if not target_id or target_id == caller_id:
            raise ValueError("A different Sat Chat target is required.")
        if requested_mode not in {"audio", "video"}:
            raise ValueError("Sat Chat mode must be audio or video.")

        target_runtime = self.manager.runtimes.get(target_id)
        caller_participant = self._participant(caller_id, caller)
        target_participant = self._participant(target_id, target_runtime)
        if caller_participant is None:
            raise RuntimeError(
                "The calling satellite is not connected or does not support Sat Chat."
            )
        if not bool(caller_participant.get("can_initiate")):
            raise PermissionError("This satellite cannot start Sat Chat calls.")
        if target_participant is None or target_runtime is None:
            raise RuntimeError(
                "The target satellite is not connected or does not support Sat Chat."
            )
        if requested_mode == "video" and not bool(target_participant.get("video")):
            raise ValueError(
                "That satellite does not currently support Sat Chat video."
            )
        if requested_mode == "video" and not bool(caller_participant.get("video")):
            raise ValueError(
                "The calling satellite does not currently support Sat Chat video."
            )

        now = time.time()
        call_id = uuid.uuid4().hex
        call = {
            "id": call_id,
            "state": "active",
            "mode": requested_mode,
            "caller": caller_id,
            "caller_name": caller.name,
            "target": target_id,
            "target_name": target_runtime.name,
            "created_ts": now,
            "started_ts": now,
            "updated_ts": now,
            "_video_profiles": {
                caller_id: _video_receive_profile(caller),
                target_id: _video_receive_profile(target_runtime),
            },
        }
        if (_h264_capable(caller) and _h264_capable(target_runtime)
                and _truthy(caller.capabilities.get("sat_chat_h264_balanced"))
                and _truthy(target_runtime.capabilities.get("sat_chat_h264_balanced"))):
            call["_video_profiles"] = {caller_id: "echo-h264-balanced", target_id: "echo-h264-balanced"}
        elif _h264_pair_compatible(caller, target_runtime):
            call["_video_profiles"] = {caller_id: "echo-h264", target_id: "echo-h264"}
        async with self._lock:
            if caller_id in self._endpoint_calls or target_id in self._endpoint_calls:
                raise RuntimeError(
                    "One of these Sat Chat participants is already busy."
                )
            self._calls[call_id] = call
            self._endpoint_calls[caller_id] = call_id
            self._endpoint_calls[target_id] = call_id

        target_sent = await target_runtime.async_send(
            "sat_chat.started", self._endpoint_call(call, target_id)
        )
        caller_sent = await caller.async_send(
            "sat_chat.started", self._endpoint_call(call, caller_id)
        )
        if not target_sent or not caller_sent:
            await self.async_end(
                call_id=call_id,
                actor=caller_id,
                reason="peer_disconnected",
                force=True,
            )
            raise RuntimeError("Unable to reach both Sat Chat participants.")
        await self.async_refresh_directories()
        return {"ok": True, "call": self._public_call(call)}

    async def async_end(
        self,
        *,
        call_id: str = "",
        actor: str = "",
        reason: str = "ended",
        force: bool = False,
    ) -> dict[str, Any]:
        """End a call and notify both endpoints."""
        call_token = _text(call_id)
        actor_token = _text(actor)
        video_tasks: list[asyncio.Task[Any]] = []
        async with self._lock:
            if not call_token and actor_token:
                call_token = self._endpoint_calls.get(actor_token, "")
            call = self._calls.get(call_token)
            if not isinstance(call, dict):
                return {"ok": True, "ended": False}
            endpoints = {_text(call.get("caller")), _text(call.get("target"))}
            if not force and actor_token not in endpoints:
                raise PermissionError("Only a Sat Chat participant can end this call.")
            actor_runtime = self.manager.runtimes.get(actor_token)
            actor_participant = self._participant(actor_token, actor_runtime)
            if (
                not force
                and actor_participant is not None
                and not bool(actor_participant.get("can_end"))
            ):
                raise PermissionError("This satellite cannot end Sat Chat calls.")

            ended_ts = time.time()
            call["state"] = "ended"
            call["reason"] = _text(reason) or "ended"
            call["ended_ts"] = ended_ts
            call["updated_ts"] = ended_ts
            public = self._public_call(call)
            self._calls.pop(call_token, None)
            for endpoint in endpoints:
                if self._endpoint_calls.get(endpoint) == call_token:
                    self._endpoint_calls.pop(endpoint, None)
            for key, relay in tuple(self._video_relays.items()):
                if key[0] != call_token:
                    continue
                self._video_relays.pop(key, None)
                task = relay.get("task") if isinstance(relay, dict) else None
                if isinstance(task, asyncio.Task):
                    video_tasks.append(task)

        current_task = asyncio.current_task()
        cancelled_tasks = [task for task in video_tasks if task is not current_task]
        for task in cancelled_tasks:
            task.cancel()
        if cancelled_tasks:
            await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        for endpoint in endpoints:
            runtime = self.manager.runtimes.get(endpoint)
            if runtime is not None:
                await runtime.async_send("sat_chat.ended", public)
        await self.async_refresh_directories()
        return {"ok": True, "ended": True, "call": public}

    async def async_handle_disconnect(self, runtime: SatelliteRuntime) -> None:
        """End the runtime's active call and refresh peer availability."""
        if self._shutting_down:
            return
        async with self._lock:
            call_id = self._endpoint_calls.get(runtime.device_id, "")
        if call_id:
            await self.async_end(
                call_id=call_id,
                actor=runtime.device_id,
                reason="disconnected",
                force=True,
            )
        else:
            await self.async_refresh_directories()

    async def async_route_binary(
        self, source: SatelliteRuntime, data: bytes
    ) -> bool:
        """Route call PCM or tagged JPEG/H.264 without entering Assist."""
        if not data:
            return False
        source_id = source.device_id
        async with self._lock:
            call_id = self._endpoint_calls.get(source_id, "")
            call = self._calls.get(call_id)
            if not isinstance(call, dict) or call.get("state") != "active":
                # Late/reserved video is never Assist microphone PCM.
                return data.startswith(b"TSCV")
            caller = _text(call.get("caller"))
            target = _text(call.get("target"))
            peer_id = target if source_id == caller else caller
            mode = _text(call.get("mode")).lower() or "audio"
            profiles = call.get("_video_profiles", {})
            video_profile = profiles.get(peer_id) if isinstance(profiles, dict) else ""
            h264_negotiated = video_profile in {"echo-h264", "echo-h264-balanced"}

        if data.startswith(H264_FRAME_PREFIX):
            if mode == "video" and h264_negotiated and _valid_h264_frame(data, balanced=video_profile == "echo-h264-balanced"):
                await self._async_queue_video_frame(call_id, source_id, peer_id, bytes(data))
            return True
        if data.startswith(b"TSCV") and not data.startswith(VIDEO_FRAME_PREFIX):
            return True
        if data.startswith(VIDEO_FRAME_PREFIX):
            jpeg = data[len(VIDEO_FRAME_PREFIX) :]
            if (
                mode != "video"
                or len(jpeg) < 4
                or len(jpeg) > MAX_VIDEO_FRAME_BYTES
                or not jpeg.startswith(b"\xff\xd8")
            ):
                # It belongs to Sat Chat even when invalid; never leak a tagged
                # frame into wake verification or the Assist microphone.
                return True
            await self._async_queue_video_frame(
                call_id, source_id, peer_id, bytes(data)
            )
            return True

        peer = self.manager.runtimes.get(peer_id)
        if peer is None or not await peer.async_send_bytes(data):
            await self.async_end(
                call_id=call_id,
                actor=source_id,
                reason="peer_disconnected",
                force=True,
            )
        return True

    async def _async_queue_video_frame(
        self, call_id: str, source: str, peer: str, data: bytes
    ) -> None:
        key = (_text(call_id), _text(peer))
        async with self._lock:
            relay = self._video_relays.get(key)
            task = relay.get("task") if isinstance(relay, dict) else None
            if (
                not isinstance(relay, dict)
                or not isinstance(task, asyncio.Task)
                or task.done()
            ):
                queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MAX_H264_RELAY_FRAMES)
                task = asyncio.create_task(
                    self._async_video_relay_worker(key, source, peer, queue),
                    name=f"tater_sat_chat_video_{peer}",
                )
                relay = {"queue": queue, "task": task}
                self._video_relays[key] = relay
            _enqueue_video_packet(relay, data)

    async def _async_video_relay_worker(
        self,
        key: tuple[str, str],
        source: str,
        peer: str,
        queue: asyncio.Queue[bytes],
    ) -> None:
        try:
            while True:
                frame = await queue.get()
                runtime = self.manager.runtimes.get(peer)
                if runtime is None or not await runtime.async_send_bytes(frame):
                    raise ConnectionError("Sat Chat video peer disconnected")
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.async_end(
                call_id=key[0],
                actor=source,
                reason="peer_disconnected",
                force=True,
            )
        finally:
            async with self._lock:
                relay = self._video_relays.get(key)
                if (
                    isinstance(relay, dict)
                    and relay.get("task") is asyncio.current_task()
                ):
                    self._video_relays.pop(key, None)

    async def async_handle_message(
        self,
        runtime: SatelliteRuntime,
        message_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Handle one firmware Sat Chat control message."""
        if message_type == "sat_chat.start":
            return await self.async_start(
                runtime,
                _text(payload.get("target")),
                mode=_text(payload.get("mode")) or "audio",
            )
        if message_type == "sat_chat.end":
            return await self.async_end(
                call_id=_text(payload.get("call_id") or payload.get("id")),
                actor=runtime.device_id,
            )
        return None

    def snapshot(self) -> dict[str, Any]:
        """Return non-media diagnostics for the management panel payload."""
        return {
            "active_calls": [
                self._public_call(call) for call in self._calls.values()
            ],
            "active_call_count": len(self._calls),
        }

    async def async_shutdown(self) -> None:
        """Discard transient calls and cancel best-effort video workers."""
        self._shutting_down = True
        async with self._lock:
            tasks = [
                relay.get("task")
                for relay in self._video_relays.values()
                if isinstance(relay, dict)
            ]
            self._video_relays.clear()
            self._calls.clear()
            self._endpoint_calls.clear()
        running = [task for task in tasks if isinstance(task, asyncio.Task)]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
