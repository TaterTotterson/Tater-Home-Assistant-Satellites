"""HTTP and WebSocket views for Tater satellites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import (
    API_BASE_PATH,
    DATA_MANAGER,
    DOMAIN,
    SATELLITE_WS_PATH,
    TRAINER_LINK_HEADER,
)
from .manager import TaterSatelliteManager


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
        return self.json(_manager(request).snapshot())


class PairingView(HomeAssistantView):
    """Start a satellite pairing session."""

    url = f"{API_BASE_PATH}/pairing"
    name = "api:tater_satellite:pairing"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Generate a pairing code."""
        return self.json(_manager(request).start_pairing())


class GlobalSettingsView(HomeAssistantView):
    """Manage global satellite defaults."""

    url = f"{API_BASE_PATH}/settings/global"
    name = "api:tater_satellite:settings_global"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Save global settings."""
        body = await _json_body(request)
        values = body.get("settings")
        if not isinstance(values, dict):
            values = body
        try:
            saved = await _manager(request).async_set_global_settings(values)
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


class DeviceSettingsResetView(HomeAssistantView):
    """Reset per-satellite overrides."""

    url = f"{API_BASE_PATH}/settings/device/{{device_id}}/reset"
    name = "api:tater_satellite:settings_device_reset"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Reset overrides."""
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
        return self.json(_manager(request).trainer.start_pairing())


class TrainerAdminUnlinkView(HomeAssistantView):
    """Revoke the linked trainer from the management panel."""

    url = f"{API_BASE_PATH}/trainer/manage/unlink"
    name = "api:tater_satellite:trainer_admin_unlink"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Unlink the trainer as a Home Assistant administrator."""
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


class FirmwareRefreshView(HomeAssistantView):
    """Refresh firmware release metadata."""

    url = f"{API_BASE_PATH}/firmware/refresh"
    name = "api:tater_satellite:firmware_refresh"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Force a release catalog refresh."""
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
        """Prepare a signed factory image and ESP Web Tools manifest."""
        manager = _manager(request)
        try:
            manifest, signed = await manager.firmware.async_web_install_manifest(
                board, f"{request.scheme}://{request.host}"
            )
        except (KeyError, ValueError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json(
            {
                "ok": True,
                "manifest": manifest,
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


class IdentifyView(HomeAssistantView):
    """Identify a connected satellite."""

    url = f"{API_BASE_PATH}/command/{{device_id}}/identify"
    name = "api:tater_satellite:identify"
    requires_auth = True

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Play the identify tone."""
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
        try:
            device = await _manager(request).async_resync_settings(device_id)
        except (KeyError, RuntimeError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"ok": True, "device": device})


class ForgetView(HomeAssistantView):
    """Forget an offline satellite."""

    url = f"{API_BASE_PATH}/device/{{device_id}}"
    name = "api:tater_satellite:forget"
    requires_auth = True

    async def delete(self, request: web.Request, device_id: str) -> web.Response:
        """Remove a device credential."""
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
    GlobalSettingsView,
    DeviceSettingsView,
    DeviceSettingsResetView,
    TrainerPairingView,
    TrainerAdminUnlinkView,
    TrainerClaimView,
    TrainerPublishView,
    TrainerRemoteUnlinkView,
    AssetUploadView,
    AssetFileView,
    FirmwareRefreshView,
    FirmwareInstallView,
    FirmwareRecoveryView,
    FirmwareFileView,
    IdentifyView,
    SettingsResyncView,
    ForgetView,
)
