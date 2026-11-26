"""HTTP and WebSocket views for Tater satellites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.exceptions import Unauthorized

from .const import (
    API_BASE_PATH,
    DATA_MANAGER,
    DOMAIN,
    SATELLITE_WS_PATH,
    TRAINER_LINK_HEADER,
)
from .manager import TaterSatelliteManager
from .dashboard_studio import StudioConflict


def _require_admin(request: web.Request) -> None:
    """Restrict management APIs to the same administrators as the panel."""
    user = request.get("hass_user")
    if user is None or not user.is_admin:
        raise Unauthorized()


def _manager(request: web.Request) -> TaterSatelliteManager:
    hass = request.app["hass"]
    manager = hass.data.get(DOMAIN, {}).get(DATA_MANAGER)
    if not isinstance(manager, TaterSatelliteManager):
        raise web.HTTPServiceUnavailable(
            text="Tater Satellite integration is not configured"
        )
    return manager


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception as err:
        raise web.HTTPBadRequest(text="Request body must be JSON") from err
    if not isinstance(value, dict):
        raise web.HTTPBadRequest(text="Request body must be an object")
    return value


class SatelliteWebSocketView(HomeAssistantView):
    """Firmware-facing WebSocket endpoint."""

    url = SATELLITE_WS_PATH
    name = "api:tater_satellite:websocket"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Accept a native firmware connection."""
        return await _manager(request).async_handle_websocket(request)


class ManageView(HomeAssistantView):
    """Return management panel state."""

    url = f"{API_BASE_PATH}/manage"
    name = "api:tater_satellite:manage"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return current settings and devices."""
        _require_admin(request)
        return self.json(_manager(request).snapshot())


class PairingView(HomeAssistantView):
    """Start a satellite pairing session."""

    url = f"{API_BASE_PATH}/pairing"
    name = "api:tater_satellite:pairing"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Generate a pairing code."""
        _require_admin(request)
        return self.json(_manager(request).start_pairing())


class BluetoothScanView(HomeAssistantView):
    """Explicit time-limited satellite discovery; never started by reading state."""

    url = f"{API_BASE_PATH}/bluetooth/scan"
    name = "api:tater_satellite:bluetooth_scan"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        _require_admin(request)
        body = await _json_body(request)
        try:
            return self.json(await _manager(request).bluetooth.async_scan(
                str(body.get("satellite_id") or ""), body.get("duration_s", 15), stop=body.get("stop") is True,
            ))
        except (ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err


class BluetoothPairView(HomeAssistantView):
    """Pair a Bluetooth peripheral through a satellite."""

    url = f"{API_BASE_PATH}/bluetooth/pair"
    name = "api:tater_satellite:bluetooth_pair"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Connect and bond using the peripheral's six-digit PIN."""
        _require_admin(request)
        body = await _json_body(request)
        try:
            device = await _manager(request).bluetooth.async_pair(
                body.get("address"),
                body.get("pin"),
                str(body.get("satellite_id") or ""),
            )
        except (KeyError, ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "device": device})


class BluetoothUnpairView(HomeAssistantView):
    """Remove a Bluetooth bond from a satellite."""

    url = f"{API_BASE_PATH}/bluetooth/unpair"
    name = "api:tater_satellite:bluetooth_unpair"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Forget a paired Bluetooth peripheral."""
        _require_admin(request)
        body = await _json_body(request)
        try:
            await _manager(request).bluetooth.async_unpair(
                body.get("address"),
                str(body.get("satellite_id") or ""),
            )
        except (KeyError, ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True})


class GlobalSettingsView(HomeAssistantView):
    """Manage global satellite defaults."""

    url = f"{API_BASE_PATH}/settings/global"
    name = "api:tater_satellite:settings_global"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save global settings."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).async_set_global_settings(values)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class TaterAssistantSettingsView(HomeAssistantView):
    """Manage the complete mini-Tater voice pipeline."""

    url = f"{API_BASE_PATH}/tater/settings"
    name = "api:tater_satellite:tater_settings"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save provider, home-control, and Hydra settings."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).tater_assistant.async_update_settings(values)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class VisionSettingsView(HomeAssistantView):
    """Save the shared Vision model without changing the voice pipeline."""

    url = f"{API_BASE_PATH}/vision/settings"
    name = "api:tater_satellite:vision_settings"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings", body)
        if not isinstance(values, dict):
            raise web.HTTPBadRequest(text="Vision settings must be an object")
        settings = {key: value for key, value in values.items() if key in {
            "vision_provider", "vision_base_url", "vision_model", "vision_api_key",
        }}
        try:
            saved = await _manager(request).tater_assistant.async_update_settings(settings)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class DoorbellsView(HomeAssistantView):
    """Save an explicitly configured doorbell in either assistant mode."""

    url = f"{API_BASE_PATH}/doorbell/doorbells"
    name = "api:tater_satellite:doorbells"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        _require_admin(request)
        body = await _json_body(request)
        try:
            saved = await _manager(request).doorbell.async_save_doorbell(
                body.get("doorbell"), str(body.get("id") or "")
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "doorbell": saved})


class DoorbellView(HomeAssistantView):
    url = f"{API_BASE_PATH}/doorbell/doorbells/{{doorbell_id}}"
    name = "api:tater_satellite:doorbell"
    requires_auth = True

    async def delete(self, request: web.Request, doorbell_id: str) -> web.Response:
        _require_admin(request)
        try:
            await _manager(request).doorbell.async_delete_doorbell(doorbell_id)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True})


class DoorbellTestView(HomeAssistantView):
    url = f"{API_BASE_PATH}/doorbell/doorbells/{{doorbell_id}}/test"
    name = "api:tater_satellite:doorbell_test"
    requires_auth = True

    async def post(self, request: web.Request, doorbell_id: str) -> web.Response:
        _require_admin(request)
        try:
            result = await _manager(request).doorbell.async_test(doorbell_id)
        except (KeyError, ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": result["status"] == "sent", "event": result})


class AwarenessMonitorsView(HomeAssistantView):
    """Create or update a camera monitor in either assistant mode."""

    url = f"{API_BASE_PATH}/awareness/monitors"
    name = "api:tater_satellite:awareness_monitors"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        _require_admin(request)
        body = await _json_body(request)
        try:
            saved = await _manager(request).awareness.async_save_monitor(
                body.get("monitor"), str(body.get("id") or "")
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "monitor": saved})


class AwarenessMonitorView(HomeAssistantView):
    url = f"{API_BASE_PATH}/awareness/monitors/{{monitor_id}}"
    name = "api:tater_satellite:awareness_monitor"
    requires_auth = True

    async def delete(self, request: web.Request, monitor_id: str) -> web.Response:
        _require_admin(request)
        try:
            await _manager(request).awareness.async_delete_monitor(monitor_id)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True})


class AwarenessTestView(HomeAssistantView):
    url = f"{API_BASE_PATH}/awareness/monitors/{{monitor_id}}/test"
    name = "api:tater_satellite:awareness_test"
    requires_auth = True

    async def post(self, request: web.Request, monitor_id: str) -> web.Response:
        _require_admin(request)
        try:
            result = await _manager(request).awareness.async_test(monitor_id)
        except (KeyError, ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": result["status"] == "sent", "event": result})


class AwarenessImageView(HomeAssistantView):
    """Serve retained snapshots through authenticated or signed HA requests."""

    url = f"{API_BASE_PATH}/awareness/images/{{event_id}}"
    name = "api:tater_satellite:awareness_image"
    requires_auth = True

    async def get(self, request: web.Request, event_id: str) -> web.Response:
        _require_admin(request)
        image = await _manager(request).awareness.async_image(event_id)
        if image is None:
            raise web.HTTPNotFound(text="This Awareness image has expired")
        data, mime = image
        return web.Response(body=data, content_type=mime, headers={"Cache-Control": "private, no-store"})


class TaterAssistantTestView(HomeAssistantView):
    """Run one mini-Tater text or image conversation for setup testing."""

    url = f"{API_BASE_PATH}/tater/test"
    name = "api:tater_satellite:tater_test"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Send a test message through Vision and Hydra without STT or TTS."""
        _require_admin(request)
        body = await _json_body(request)
        text = str(body.get("text") or "").strip()
        images = body.get("images")
        if not text and not images:
            raise web.HTTPBadRequest(text="Enter a test message or attach an image")
        try:
            result = await _manager(request).tater_assistant.async_process_text(
                text,
                conversation_id=str(body.get("conversation_id") or "tater-panel-test"),
                device_id="management-panel",
                images=images,
            )
        except (KeyError, ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, **result})


class DashboardStudioView(HomeAssistantView):
    """Admin-only design workspace, separate from satellite chat."""

    url = f"{API_BASE_PATH}/dashboard-studio"
    name = "api:tater_satellite:dashboard_studio"
    requires_auth = True

    @staticmethod
    def _user(request):
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            raise web.HTTPForbidden(text="Dashboard Studio requires an administrator")
        return user

    async def get(self, request):
        _require_admin(request)
        user = self._user(request)
        try:
            return self.json(await _manager(request).dashboard_studio.snapshot(user))
        except (ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err

    async def post(self, request):
        _require_admin(request)
        user = self._user(request)
        body = await _json_body(request)
        studio = _manager(request).dashboard_studio
        workspace_id = str(body.get("workspace_id") or "")
        revision = body.get("revision")
        try:
            action = body.get("action")
            if action == "settings":
                settings = await studio.save_settings(user, body.get("settings"))
                return self.json({"ok": True, "settings": settings})
            if action == "open":
                result = await studio.open(
                    user, workspace_id=workspace_id, url_path=body.get("url_path"),
                    title=str(body.get("title") or ""),
                )
            elif action == "chat":
                result = await studio.chat(
                    user, workspace_id, revision, body.get("text"),
                    visual_style=body.get("visual_style"), theme=body.get("theme"),
                    layout=body.get("layout"), allow_custom=body.get("allow_custom"),
                    focus=body.get("focus"),
                )
            elif action == "concept":
                result = await studio.concept(user, workspace_id, revision, body.get("index"),
                    body.get("text"), visual_style=body.get("visual_style"),
                    theme=body.get("theme"), allow_custom=body.get("allow_custom"))
            elif action == "choose_concept":
                result = await studio.choose_concept(user, workspace_id, revision, body.get("concept_id"))
            elif action == "apply":
                result = await studio.apply(user, workspace_id, revision)
            elif action in {"undo_draft", "undo_apply"}:
                result = await studio.undo(user, workspace_id, revision, applied=action == "undo_apply")
            elif action == "remove":
                await studio.remove(user, workspace_id, revision)
                return self.json({"ok": True})
            else:
                raise ValueError("Choose a Dashboard Studio action.")
        except StudioConflict as err:
            raise web.HTTPConflict(text=str(err)) from err
        except PermissionError as err:
            raise web.HTTPForbidden(text=str(err)) from err
        except (KeyError, ValueError, RuntimeError, TimeoutError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "workspace": result})


class TaterHydraClearView(HomeAssistantView):
    """Clear mini-Tater Hydra records selected by the administrator."""

    url = f"{API_BASE_PATH}/tater/hydra/clear"
    name = "api:tater_satellite:tater_hydra_clear"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Clear ledger entries, conversation history, or both."""
        _require_admin(request)
        body = await _json_body(request)
        return self.json(
            await _manager(request).tater_assistant.async_clear_hydra(
                ledger=bool(body.get("ledger", True)),
                conversations=bool(body.get("conversations", False)),
            )
        )


class TaterSpeechAudioView(HomeAssistantView):
    """Serve a short-lived synthesized Tater response to a satellite."""

    url = f"{API_BASE_PATH}/tater/audio/{{clip_id}}"
    name = "api:tater_satellite:tater_audio"
    requires_auth = False

    async def get(self, request: web.Request, clip_id: str) -> web.Response:
        """Return generated speech by its unguessable, expiring identifier."""
        clip = _manager(request).tater_assistant.clip(clip_id)
        if clip is None:
            raise web.HTTPNotFound(text="Tater speech clip expired")
        content_type, data = clip
        return web.Response(
            body=data,
            content_type=content_type,
            headers={"Cache-Control": "private, max-age=300"},
        )


class TrainerSettingsView(HomeAssistantView):
    """Manage trainer feedback settings."""

    url = f"{API_BASE_PATH}/settings/trainer"
    name = "api:tater_satellite:settings_trainer"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save trainer settings."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).async_set_trainer_settings(values)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class WakeArbitrationSettingsView(HomeAssistantView):
    """Manage bridge-side wake selection in either assistant mode."""

    url = f"{API_BASE_PATH}/settings/arbitration"
    name = "api:tater_satellite:settings_arbitration"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Persist host settings; no firmware update or settings push needed."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings", body)
        try:
            saved = await _manager(request).async_set_wake_arbitration_settings(values)
        except (ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class WakeVerifierSettingsView(HomeAssistantView):
    """Manage STT wake-check settings."""

    url = f"{API_BASE_PATH}/settings/verifier"
    name = "api:tater_satellite:settings_verifier"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save STT wake-check settings."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).async_set_wake_verifier_settings(values)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class WakeFamilySettingsView(HomeAssistantView):
    """Keep the former family endpoint available for older clients."""

    url = f"{API_BASE_PATH}/settings/wake-family/{{family}}"
    name = "api:tater_satellite:settings_wake_family"
    requires_auth = True

    async def post(self, request: web.Request, family: str) -> web.Response:
        """Save the shared wake profile through a legacy family route."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).async_set_wake_family_settings(
                family,
                values,
                allow_catalog_only=True,
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "family": family, "settings": saved})


class SharedWakeSettingsView(HomeAssistantView):
    """Manage the one wake profile shared by every satellite."""

    url = f"{API_BASE_PATH}/settings/wake"
    name = "api:tater_satellite:settings_wake"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save the shared MWW, OWW-where-supported, or Dual wake profile."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).async_set_shared_wake_settings(values)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "settings": saved})


class DeviceSettingsView(HomeAssistantView):
    """Manage per-satellite overrides."""

    url = f"{API_BASE_PATH}/settings/device/{{device_id}}"
    name = "api:tater_satellite:settings_device"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Save per-device settings."""
        _require_admin(request)
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = {}
        try:
            device = await _manager(request).async_set_device_settings(
                device_id,
                values,
                pipeline_id=(
                    str(body.get("pipeline_id") or "")
                    if "pipeline_id" in body
                    else None
                ),
                vad_sensitivity=(
                    str(body.get("vad_sensitivity") or "default")
                    if "vad_sensitivity" in body
                    else None
                ),
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "device": device})


class DeviceIdentityView(HomeAssistantView):
    """Save the name and room onto a connected satellite."""

    url = f"{API_BASE_PATH}/settings/device/{{device_id}}/identity"
    name = "api:tater_satellite:device_identity"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Wait for persistent firmware confirmation before reporting success."""
        _require_admin(request)
        body = await _json_body(request)
        try:
            device = await _manager(request).async_set_device_identity(device_id, body)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "device": device})


class DeviceSettingsResetView(HomeAssistantView):
    """Reset per-satellite overrides."""

    url = f"{API_BASE_PATH}/settings/device/{{device_id}}/reset"
    name = "api:tater_satellite:settings_device_reset"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Reset overrides."""
        _require_admin(request)
        try:
            device = await _manager(request).async_reset_device_settings(device_id)
        except (KeyError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "device": device})


class TrainerPairingView(HomeAssistantView):
    """Start secure Wake Word Trainer pairing."""

    url = f"{API_BASE_PATH}/trainer/pairing"
    name = "api:tater_satellite:trainer_pairing"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Generate a one-use trainer pairing code."""
        _require_admin(request)
        return self.json(_manager(request).trainer.start_pairing())


class TrainerAdminUnlinkView(HomeAssistantView):
    """Revoke the linked trainer from the management panel."""

    url = f"{API_BASE_PATH}/trainer/manage/unlink"
    name = "api:tater_satellite:trainer_admin_unlink"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Unlink the trainer as a Home Assistant administrator."""
        _require_admin(request)
        return self.json(await _manager(request).trainer.async_unlink(admin=True))


class TrainerClaimView(HomeAssistantView):
    """Compatibility endpoint used by both Wake Word Trainer variants."""

    url = f"{API_BASE_PATH}/trainer/link/claim"
    name = "api:tater_satellite:trainer_claim"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Exchange a short pairing code for a persistent trainer credential."""
        try:
            result = await _manager(request).trainer.async_claim(
                await _json_body(request)
            )
        except ValueError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=401)
        return self.json(result)


class TrainerPublishView(HomeAssistantView):
    """Accept an authenticated wake-word publication from the trainer."""

    url = f"{API_BASE_PATH}/trainer/wake-word"
    name = "api:tater_satellite:trainer_publish"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Publish a new wake-word package to all satellites."""
        try:
            result = await _manager(request).trainer.async_publish(
                request.headers.get(TRAINER_LINK_HEADER),
                await _json_body(request),
            )
        except PermissionError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=401)
        except ValueError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=400)
        except RuntimeError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=409)
        return self.json(result)


class TrainerRemoteUnlinkView(HomeAssistantView):
    """Allow the authenticated trainer to revoke its own link."""

    url = f"{API_BASE_PATH}/trainer/link/unlink"
    name = "api:tater_satellite:trainer_remote_unlink"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Unlink the calling trainer."""
        try:
            result = await _manager(request).trainer.async_unlink(
                request.headers.get(TRAINER_LINK_HEADER)
            )
        except PermissionError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=401)
        return self.json(result)


class AssetUploadView(HomeAssistantView):
    """Upload custom wake models and sounds."""

    url = f"{API_BASE_PATH}/assets"
    name = "api:tater_satellite:assets"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Store a validated custom wake asset."""
        _require_admin(request)
        body = await _json_body(request)
        try:
            asset = await _manager(request).async_upload_asset(
                str(body.get("kind") or ""),
                str(body.get("filename") or ""),
                str(body.get("label") or ""),
                str(body.get("data_b64") or ""),
            )
        except (ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "asset": asset})


class AssetFileView(HomeAssistantView):
    """Serve a wake asset to paired firmware using an opaque URL."""

    url = f"{API_BASE_PATH}/assets/{{asset_id}}/{{filename}}"
    name = "api:tater_satellite:asset_file"
    requires_auth = False

    async def get(
        self, request: web.Request, asset_id: str, filename: str
    ) -> web.StreamResponse:
        """Serve an uploaded wake model manifest/model or WAV."""
        resolved = _manager(request).asset_file(
            asset_id, filename, str(request.query.get("token") or "")
        )
        if resolved is None:
            raise web.HTTPNotFound()
        path, content_type = resolved
        return web.FileResponse(
            path,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "private, max-age=300",
            },
        )


class WakeWordCatalogView(HomeAssistantView):
    """Return the official Tater wake-word catalog."""

    url = f"{API_BASE_PATH}/wake-word/catalog"
    name = "api:tater_satellite:wake_word_catalog"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Load cached catalog choices, refreshing them when expired."""
        _require_admin(request)
        catalog = await _manager(request).wake_word_catalog.async_refresh()
        return self.json(catalog)


class FirmwareRefreshView(HomeAssistantView):
    """Refresh firmware release metadata."""

    url = f"{API_BASE_PATH}/firmware/refresh"
    name = "api:tater_satellite:firmware_refresh"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Force a release catalog refresh."""
        _require_admin(request)
        try:
            result = await _manager(request).firmware.async_refresh(force=True)
        except (ValueError, RuntimeError) as err:
            raise web.HTTPBadGateway(text=str(err)) from err
        return self.json({"ok": True, "firmware": result})


class FirmwareInstallView(HomeAssistantView):
    """Install OTA firmware on a connected satellite."""

    url = f"{API_BASE_PATH}/firmware/install/{{device_id}}"
    name = "api:tater_satellite:firmware_install"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Start an OTA update."""
        _require_admin(request)
        try:
            result = await _manager(request).async_install_firmware(device_id)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json(result)


class FirmwareRecoveryView(HomeAssistantView):
    """Prepare browser USB recovery metadata."""

    url = f"{API_BASE_PATH}/firmware/recovery/{{board}}"
    name = "api:tater_satellite:firmware_recovery"
    requires_auth = True

    async def post(self, request: web.Request, board: str) -> web.Response:
        """Prepare a signed factory or keep-settings ESP Web Tools manifest."""
        _require_admin(request)
        manager = _manager(request)
        body = await _json_body(request)
        flash_kind = str(body.get("flash_kind") or "factory").strip().lower()
        try:
            manifest, signed = await manager.firmware.async_web_install_manifest(
                board,
                f"{request.scheme}://{request.host}",
                flash_kind,
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json(
            {
                "ok": True,
                "manifest": manifest,
                "flash_kind": flash_kind,
                "preserves_settings": flash_kind == "ota",
                "expires_at": signed.expires_at,
            }
        )


class FirmwareFileView(HomeAssistantView):
    """Serve a verified, signed firmware image."""

    url = f"{API_BASE_PATH}/firmware/file/{{filename}}"
    name = "api:tater_satellite:firmware_file"
    requires_auth = False

    async def get(self, request: web.Request, filename: str) -> web.StreamResponse:
        """Serve OTA/factory firmware to a satellite or ESP Web Tools."""
        signed = _manager(request).firmware.signed_artifact(
            str(request.query.get("token") or ""), filename
        )
        if signed is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            signed.path,
            headers={
                "Content-Type": signed.content_type,
                "Cache-Control": "private, max-age=300",
                "Content-Disposition": (f'inline; filename="{Path(filename).name}"'),
            },
        )


class IntercomClipView(HomeAssistantView):
    """Serve a short-lived in-memory push-to-talk recording."""

    url = f"{API_BASE_PATH}/intercom/{{clip_id}}.wav"
    name = "api:tater_satellite:intercom_clip"
    requires_auth = False

    async def get(
        self, request: web.Request, clip_id: str
    ) -> web.StreamResponse:
        """Return an opaque intercom WAV to connected satellite firmware."""
        body = _manager(request).intercom.clip_bytes(
            clip_id,
            str(request.query.get("token") or ""),
        )
        if body is None:
            raise web.HTTPNotFound()
        return web.Response(
            body=body,
            headers={
                "Content-Type": "audio/wav",
                "Cache-Control": "private, no-store, max-age=0",
            },
        )


class IdentifyView(HomeAssistantView):
    """Identify a connected satellite."""

    url = f"{API_BASE_PATH}/command/{{device_id}}/identify"
    name = "api:tater_satellite:identify"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Speak the identify message."""
        _require_admin(request)
        try:
            await _manager(request).async_identify(device_id)
        except (KeyError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True})


class SettingsResyncView(HomeAssistantView):
    """Force a connected satellite to reapply its effective settings."""

    url = f"{API_BASE_PATH}/command/{{device_id}}/sync-settings"
    name = "api:tater_satellite:sync_settings"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Send settings while firmware confirmation continues asynchronously."""
        _require_admin(request)
        try:
            device = await _manager(request).async_resync_settings(device_id)
        except (KeyError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "device": device})


class StereoPairView(HomeAssistantView):
    """Create or update a saved Tater Audio stereo pair."""

    url = f"{API_BASE_PATH}/stereo-pairs"
    name = "api:tater_satellite:stereo_pairs"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save a left/right satellite pair."""
        _require_admin(request)
        manager = _manager(request)
        body = await _json_body(request)
        values = body.get("pair") if isinstance(body.get("pair"), dict) else body
        try:
            pair = await manager.media.async_save_pair(
                values, str(body.get("id") or "")
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "pair": pair})


class StereoPairDeleteView(HomeAssistantView):
    """Delete a saved Tater Audio stereo pair."""

    url = f"{API_BASE_PATH}/stereo-pairs/{{pair_id}}"
    name = "api:tater_satellite:stereo_pair"
    requires_auth = True

    async def delete(self, request: web.Request, pair_id: str) -> web.Response:
        """Remove a stereo pair and its virtual media player."""
        _require_admin(request)
        manager = _manager(request)
        try:
            await manager.media.async_remove_pair(pair_id)
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True})


class ForgetView(HomeAssistantView):
    """Forget an offline satellite."""

    url = f"{API_BASE_PATH}/device/{{device_id}}"
    name = "api:tater_satellite:forget"
    requires_auth = True

    async def delete(self, request: web.Request, device_id: str) -> web.Response:
        """Remove a device credential."""
        _require_admin(request)
        manager = _manager(request)
        try:
            await manager.async_forget(device_id)
        except (KeyError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        hass = request.app["hass"]
        hass.async_create_task(hass.config_entries.async_reload(manager.entry.entry_id))
        return self.json({"ok": True})


VIEWS = (
    SatelliteWebSocketView,
    ManageView,
    PairingView,
    BluetoothScanView,
    BluetoothPairView,
    BluetoothUnpairView,
    GlobalSettingsView,
    TaterAssistantSettingsView,
    VisionSettingsView,
    DoorbellsView,
    DoorbellView,
    DoorbellTestView,
    AwarenessMonitorsView,
    AwarenessMonitorView,
    AwarenessTestView,
    AwarenessImageView,
    TaterAssistantTestView,
    DashboardStudioView,
    TaterHydraClearView,
    TaterSpeechAudioView,
    TrainerSettingsView,
    WakeVerifierSettingsView,
    WakeArbitrationSettingsView,
    SharedWakeSettingsView,
    WakeFamilySettingsView,
    DeviceSettingsView,
    DeviceIdentityView,
    DeviceSettingsResetView,
    TrainerPairingView,
    TrainerAdminUnlinkView,
    TrainerClaimView,
    TrainerPublishView,
    TrainerRemoteUnlinkView,
    AssetUploadView,
    AssetFileView,
    WakeWordCatalogView,
    FirmwareRefreshView,
    FirmwareInstallView,
    FirmwareRecoveryView,
    FirmwareFileView,
    IntercomClipView,
    IdentifyView,
    SettingsResyncView,
    StereoPairView,
    StereoPairDeleteView,
    ForgetView,
)
