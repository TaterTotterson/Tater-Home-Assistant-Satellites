"""Home Assistant Bluetooth proxy backed by Tater Echo satellites."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import secrets
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from bleak.assigned_numbers import CHARACTERISTIC_PROPERTIES
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.client import BaseBleakClient, NotifyCallback
from bleak.backends.descriptor import BleakGATTDescriptor
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
from habluetooth import (
    Allocations,
    BaseHaRemoteScanner,
    HaBluetoothConnector,
    get_manager as get_bluetooth_manager,
)
from homeassistant.components import bluetooth

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable

    from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

_CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"
_DEFAULT_MTU = 23
_GATT_TIMEOUT = 35.0
_CONNECT_TIMEOUT = 42.0
_ADVERTISEMENT_MAX_AGE = 45.0


def normalize_address(value: Any) -> str:
    """Return a canonical Bluetooth address or an empty string."""
    raw = "".join(ch for ch in str(value or "") if ch.lower() in "0123456789abcdef")
    if len(raw) != 12:
        return ""
    return ":".join(raw[index : index + 2] for index in range(0, 12, 2)).upper()


def scanner_source(runtime: SatelliteRuntime) -> str:
    """Return a stable locally administered MAC for a satellite scanner."""
    hardware_id = normalize_address(runtime.record.get("hardware_id"))
    if hardware_id:
        return hardware_id
    digest = bytearray(hashlib.sha256(runtime.device_id.encode()).digest()[:6])
    digest[0] = (digest[0] | 0x02) & 0xFE
    return ":".join(f"{part:02X}" for part in digest)


def _uuid(value: Any) -> str:
    """Normalize a firmware UUID for Bleak."""
    try:
        return normalize_uuid_str(str(value or ""))
    except (TypeError, ValueError):
        return str(value or "")


class TaterBluetoothScanner(BaseHaRemoteScanner):
    """One connectable HA scanner supplied by an Echo satellite."""

    def __init__(
        self,
        proxy: TaterBluetoothProxyManager,
        runtime: SatelliteRuntime,
    ) -> None:
        self.proxy = proxy
        self.runtime = runtime
        self._slots = 0
        self._free = 0
        self._allocated: list[str] = []
        source = scanner_source(runtime)
        connector = HaBluetoothConnector(
            client=partial(TaterBleakClient, proxy=proxy),
            source=source,
            can_connect=self.can_connect,
        )
        super().__init__(
            source,
            f"{runtime.name} Bluetooth",
            connector,
            connectable=True,
        )

    def can_connect(self) -> bool:
        """Return whether this satellite can accept a GATT connection."""
        return self.runtime.connected and (self._slots == 0 or self._free > 0)

    def set_slots(self, payload: dict[str, Any]) -> None:
        """Apply the firmware's live GATT allocation report."""
        self._slots = max(0, int(payload.get("limit") or 0))
        self._free = max(0, min(self._slots, int(payload.get("free") or 0)))
        self._allocated = [
            address
            for value in payload.get("addrs") or []
            if (address := normalize_address(value))
        ]
        if self._slots:
            get_bluetooth_manager().async_on_allocation_changed(
                Allocations(
                    adapter=self.source,
                    slots=self._slots,
                    free=self._free,
                    allocated=self._allocated,
                )
            )

    def get_allocations(self) -> Allocations | None:
        """Return the current firmware connection slots."""
        if not self._slots:
            return None
        return Allocations(
            adapter=self.source,
            slots=self._slots,
            free=self._free,
            allocated=list(self._allocated),
        )

    def feed(self, payload: dict[str, Any]) -> None:
        """Feed a raw advertisement batch into Home Assistant Bluetooth."""
        now = time.monotonic()
        for row in payload.get("adverts") or []:
            if not isinstance(row, dict):
                continue
            address = normalize_address(row.get("address"))
            if not address:
                continue
            bonded_satellite = self.proxy.bonded_satellite(address)
            if bonded_satellite and bonded_satellite != self.runtime.device_id:
                # A PIN is deliberately never retained centrally. Only the Echo
                # holding this bond may advertise a connectable path for it.
                continue
            try:
                raw = bytes.fromhex(str(row.get("data") or ""))
                rssi = int(row.get("rssi") or 0)
                address_type = int(row.get("address_type") or 0)
                age_ms = max(0, int(row.get("age_ms") or 0))
            except (TypeError, ValueError):
                continue
            if not raw:
                continue
            seen = now - (age_ms / 1000)
            try:
                self._async_on_raw_advertisement(
                    address,
                    rssi,
                    raw,
                    {"address_type": address_type},
                    seen,
                )
            except (IndexError, TypeError, ValueError):
                _LOGGER.debug(
                    "Ignoring malformed Bluetooth advertisement from %s via %s",
                    address,
                    self.runtime.name,
                )
                continue
            info = self._previous_service_info.get(address)
            self.proxy.note_advertisement(
                self,
                address,
                address_type,
                rssi,
                info.name if info is not None else "",
            )


class TaterBleakClient(BaseBleakClient):
    """Bleak backend that transports GATT over a satellite WebSocket."""

    def __init__(
        self,
        address_or_ble_device: BLEDevice | str,
        *args: Any,
        proxy: TaterBluetoothProxyManager,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("timeout", _GATT_TIMEOUT)
        kwargs.setdefault("disconnected_callback", None)
        super().__init__(address_or_ble_device, *args, **kwargs)
        if not isinstance(address_or_ble_device, BLEDevice):
            raise BleakError("A discovered Bluetooth device is required")
        self._device = address_or_ble_device
        self._proxy = proxy
        details = address_or_ble_device.details or {}
        self._source = str(details.get("source") or "")
        self._address_type = int(details.get("address_type") or 0)
        self._is_connected = False
        self._disconnecting = False
        self._mtu = _DEFAULT_MTU
        self._notify_callbacks: dict[int, NotifyCallback] = {}

    @property
    def name(self) -> str:
        """Return the advertised device name."""
        return self._device.name or self.address

    @property
    def mtu_size(self) -> int:
        """Return the negotiated ATT MTU."""
        return self._mtu

    @property
    def is_connected(self) -> bool:
        """Return current link state."""
        return self._is_connected

    @property
    def runtime(self) -> SatelliteRuntime:
        """Return the satellite selected by Home Assistant."""
        runtime = self._proxy.runtime_for_source(self._source)
        if runtime is None or not runtime.connected:
            raise BleakError("The selected Tater Bluetooth satellite is offline")
        bonded_satellite = self._proxy.bonded_satellite(self.address)
        if bonded_satellite and bonded_satellite != runtime.device_id:
            raise BleakError(
                "This Bluetooth bond is stored on a different Echo satellite"
            )
        return runtime

    async def _request(
        self,
        operation: str,
        *,
        timeout: float = _GATT_TIMEOUT,
        **values: Any,
    ) -> dict[str, Any]:
        payload = {
            "t": operation,
            "req": self._proxy.next_request_id(),
            "addr": normalize_address(self.address),
            **values,
        }
        try:
            result = await self.runtime.async_request(
                "ble.gatt",
                payload,
                timeout=timeout,
            )
        except (TimeoutError, RuntimeError) as err:
            raise BleakError(str(err)) from err
        if not bool(result.get("ok")):
            error = str(result.get("error") or "failed")
            detail = str(result.get("detail") or "")
            raise BleakError(
                f"Tater Bluetooth {operation} failed: {error}"
                f"{f' ({detail})' if detail else ''}"
            )
        return result

    async def connect(self, pair: bool, **kwargs: Any) -> None:
        """Open the satellite's GATT connection and discover services."""
        if self._is_connected:
            return
        if pair and not self._proxy.is_bonded(self.address):
            raise BleakError(
                "Pair this device with its PIN in Tater Satellites > Bluetooth first"
            )
        try:
            result = await self._request(
                "connect",
                timeout=_CONNECT_TIMEOUT,
                addr_type=self._address_type,
            )
        except BleakError as err:
            if "already_connected" not in str(err):
                raise
            result = {}
        self._mtu = max(_DEFAULT_MTU, int(result.get("mtu") or _DEFAULT_MTU))
        self._is_connected = True
        self._proxy.register_client(self)
        try:
            await self._get_services()
        except Exception:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """Release the satellite GATT connection."""
        self._disconnecting = True
        try:
            if self._is_connected:
                with contextlib.suppress(BleakError):
                    await self._request("disconnect")
            self._disconnected(False)
        finally:
            self._disconnecting = False

    async def pair(self, *args: Any, **kwargs: Any) -> None:
        """Pair using a PIN supplied by the Tater panel."""
        pin = str(kwargs.get("pin") or "")
        if not pin:
            raise BleakError("Enter the device PIN in Tater Satellites > Bluetooth")
        if not self._is_connected:
            await self.connect(False)
        result = await self._request("pair", timeout=_CONNECT_TIMEOUT, pin=pin)
        if not all(
            bool(result.get(key)) for key in ("bonded", "encrypted", "authenticated")
        ):
            raise BleakError(
                "Bluetooth pairing did not establish an authenticated encrypted bond"
            )

    async def unpair(self) -> None:
        """Remove the bond from the satellite."""
        self._disconnecting = True
        try:
            await self._request("forget", timeout=_CONNECT_TIMEOUT)
            self._proxy.forget_bond(self.address)
            await self._proxy.manager.async_save()
            self._disconnected(False)
        finally:
            self._disconnecting = False

    async def _get_services(self) -> BleakGATTServiceCollection:
        result = await self._request("services")
        services = BleakGATTServiceCollection()

        def maximum_write() -> int:
            return max(20, self.mtu_size - 3)

        for service_row in result.get("services") or []:
            service = BleakGATTService(
                service_row,
                int(service_row.get("start") or 0),
                _uuid(service_row.get("uuid")),
            )
            services.add_service(service)
            for char_row in service_row.get("chars") or []:
                props_value = int(char_row.get("props") or 0)
                props = [
                    prop
                    for mask, prop in CHARACTERISTIC_PROPERTIES.items()
                    if props_value & mask
                ]
                characteristic = BleakGATTCharacteristic(
                    char_row,
                    int(char_row.get("value_handle") or char_row.get("handle") or 0),
                    _uuid(char_row.get("uuid")),
                    props,
                    maximum_write,
                    service,
                )
                services.add_characteristic(characteristic)
                for descriptor_row in char_row.get("descs") or []:
                    services.add_descriptor(
                        BleakGATTDescriptor(
                            descriptor_row,
                            int(descriptor_row.get("handle") or 0),
                            _uuid(descriptor_row.get("uuid")),
                            characteristic,
                        )
                    )
        self.services = services
        return services

    async def read_gatt_char(
        self,
        characteristic: BleakGATTCharacteristic,
        *,
        use_cached: bool = False,
        **kwargs: Any,
    ) -> bytearray:
        """Read a characteristic through the satellite."""
        return await self._read(characteristic.handle)

    async def read_gatt_descriptor(
        self,
        descriptor: BleakGATTDescriptor,
        *,
        use_cached: bool = False,
        **kwargs: Any,
    ) -> bytearray:
        """Read a descriptor through the satellite."""
        return await self._read(descriptor.handle)

    async def _read(self, handle: int) -> bytearray:
        result = await self._request("read", handle=handle)
        try:
            return bytearray(base64.b64decode(str(result.get("value") or "")))
        except (ValueError, TypeError) as err:
            raise BleakError("Satellite returned invalid Bluetooth data") from err

    async def write_gatt_char(
        self,
        characteristic: BleakGATTCharacteristic,
        data: Any,
        response: bool,
    ) -> None:
        """Write a characteristic through the satellite."""
        await self._write(characteristic.handle, data, response)

    async def write_gatt_descriptor(
        self,
        descriptor: BleakGATTDescriptor,
        data: Any,
    ) -> None:
        """Write a descriptor through the satellite."""
        await self._write(descriptor.handle, data, True)

    async def _write(self, handle: int, data: Any, response: bool) -> None:
        value = base64.b64encode(bytes(data)).decode()
        await self._request(
            "write",
            handle=handle,
            value=value,
            response=bool(response),
        )

    async def start_notify(
        self,
        characteristic: BleakGATTCharacteristic,
        callback: NotifyCallback,
        **kwargs: Any,
    ) -> None:
        """Subscribe to notifications or indications."""
        descriptor = next(
            (item for item in characteristic.descriptors if item.uuid == _CCCD_UUID),
            None,
        )
        if descriptor is None:
            raise BleakError("Characteristic has no client configuration descriptor")
        if "notify" in characteristic.properties:
            enabled = b"\x01\x00"
        elif "indicate" in characteristic.properties:
            enabled = b"\x02\x00"
        else:
            raise BleakError("Characteristic does not support notifications")
        self._notify_callbacks[characteristic.handle] = callback
        try:
            await self._write(descriptor.handle, enabled, True)
        except Exception:
            self._notify_callbacks.pop(characteristic.handle, None)
            raise

    async def stop_notify(self, characteristic: BleakGATTCharacteristic) -> None:
        """Stop characteristic notifications."""
        descriptor = next(
            (item for item in characteristic.descriptors if item.uuid == _CCCD_UUID),
            None,
        )
        if descriptor is not None and self._is_connected:
            await self._write(descriptor.handle, b"\x00\x00", True)
        self._notify_callbacks.pop(characteristic.handle, None)

    def handle_notify(self, handle: int, value: bytes) -> None:
        """Deliver a firmware notification to Bleak."""
        if callback := self._notify_callbacks.get(handle):
            callback(bytearray(value))

    def _disconnected(self, notify: bool = True) -> None:
        """Clear local connection state and optionally notify the consumer."""
        was_connected = self._is_connected
        self._is_connected = False
        self.services = BleakGATTServiceCollection()
        self._notify_callbacks.clear()
        self._proxy.unregister_client(self)
        if (
            notify
            and not self._disconnecting
            and was_connected
            and self._disconnected_callback
        ):
            self._disconnected_callback()


class TaterBluetoothProxyManager:
    """Register Echo scanners and route their active GATT protocol."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self._scanners: dict[str, TaterBluetoothScanner] = {}
        self._scanner_cancels: dict[str, list[Callable[[], None]]] = {}
        self._clients: dict[tuple[str, str], TaterBleakClient] = {}
        self._nearby: dict[tuple[str, str], dict[str, Any]] = {}
        self._request_id = secrets.randbits(31) or 1

    @staticmethod
    def supported(runtime: SatelliteRuntime) -> bool:
        """Return whether firmware advertises active Bluetooth GATT."""
        return bool(runtime.capabilities.get("ble_gatt"))

    def next_request_id(self) -> int:
        """Return a non-zero compact firmware request id."""
        self._request_id = (self._request_id + 1) & 0xFFFFFFFF
        if self._request_id == 0:
            self._request_id = 1
        return self._request_id

    def runtime_for_source(self, source: str) -> SatelliteRuntime | None:
        """Resolve a registered scanner source to its live satellite."""
        scanner = self._scanners.get(source)
        return scanner.runtime if scanner is not None else None

    def async_connect_runtime(self, runtime: SatelliteRuntime) -> None:
        """Register a newly connected compatible satellite with HA Bluetooth."""
        if not self.supported(runtime):
            return
        source = scanner_source(runtime)
        self.disconnect_runtime(runtime)
        scanner = TaterBluetoothScanner(self, runtime)
        cancel_register = bluetooth.async_register_scanner(
            self.manager.hass,
            scanner,
            source_domain=DOMAIN,
            source_model=runtime.board or "Tater Echo",
            source_config_entry_id=self.manager.entry.entry_id,
        )
        cancel_setup = scanner.async_setup()
        self._scanners[source] = scanner
        self._scanner_cancels[source] = [cancel_setup, cancel_register]
        self.manager.entry.async_create_background_task(
            self.manager.hass,
            self._async_refresh_slots(runtime),
            f"tater_bluetooth_slots_{runtime.device_id}",
        )

    async def _async_refresh_slots(self, runtime: SatelliteRuntime) -> None:
        """Ask for allocation state after the WebSocket receive loop starts."""
        await asyncio.sleep(0)
        if not runtime.connected:
            return
        with contextlib.suppress(Exception):
            await runtime.async_send(
                "ble.gatt",
                {"t": "slots", "req": self.next_request_id()},
            )

    def disconnect_runtime(self, runtime: SatelliteRuntime) -> None:
        """Unregister a scanner and disconnect its active HA clients."""
        source = scanner_source(runtime)
        for (client_source, _), client in tuple(self._clients.items()):
            if client_source == source:
                client._disconnected(True)
        for cancel in self._scanner_cancels.pop(source, []):
            with contextlib.suppress(Exception):
                cancel()
        self._scanners.pop(source, None)

    async def async_shutdown(self) -> None:
        """Remove all scanners and client routes."""
        for runtime in tuple(self.manager.runtimes.values()):
            self.disconnect_runtime(runtime)

    def handle_message(
        self,
        runtime: SatelliteRuntime,
        kind: str,
        payload: dict[str, Any],
    ) -> bool:
        """Consume Bluetooth advertisement and GATT event messages."""
        scanner = self._scanners.get(scanner_source(runtime))
        if kind == "ble.advertisements":
            if scanner is not None:
                scanner.feed(payload)
            return True
        if kind != "ble.gatt.event":
            return False
        event_type = str(payload.get("t") or "")
        if event_type == "slots":
            self._handle_slots(runtime, payload)
            return True
        address = normalize_address(payload.get("addr"))
        client = self._clients.get((scanner_source(runtime), address))
        if client is None:
            return True
        if event_type == "notify":
            try:
                value = base64.b64decode(str(payload.get("value") or ""))
                client.handle_notify(int(payload.get("handle") or 0), value)
            except (TypeError, ValueError):
                _LOGGER.debug("Ignoring malformed GATT notification from %s", address)
        elif event_type == "disconnected":
            client._disconnected(True)
        return True

    def _handle_slots(
        self,
        runtime: SatelliteRuntime,
        payload: dict[str, Any],
    ) -> None:
        if scanner := self._scanners.get(scanner_source(runtime)):
            scanner.set_slots(payload)

    def register_client(self, client: TaterBleakClient) -> None:
        """Route firmware events to a connected client."""
        address = normalize_address(client.address)
        previous = self._clients.get((client._source, address))
        if previous is not None and previous is not client:
            previous._disconnected(True)
        self._clients[(client._source, address)] = client

    def unregister_client(self, client: TaterBleakClient) -> None:
        """Remove a connected client's event route."""
        key = (client._source, normalize_address(client.address))
        if self._clients.get(key) is client:
            self._clients.pop(key, None)

    def note_advertisement(
        self,
        scanner: TaterBluetoothScanner,
        address: str,
        address_type: int,
        rssi: int,
        name: Any,
    ) -> None:
        """Keep a small panel-facing cache for manual pairing."""
        self._nearby[(scanner.source, address)] = {
            "address": address,
            "address_type": address_type,
            "name": str(name or address),
            "rssi": rssi,
            "source": scanner.source,
            "satellite_id": scanner.runtime.device_id,
            "satellite_name": scanner.runtime.name,
            "last_seen": time.time(),
        }

    def is_bonded(self, address: Any) -> bool:
        """Return whether bridge metadata records a completed bond."""
        return normalize_address(address) in self.manager.data.get(
            "bluetooth_devices", {}
        )

    def bonded_satellite(self, address: Any) -> str:
        """Return the satellite that owns a saved peripheral bond."""
        record = self.manager.data.get("bluetooth_devices", {}).get(
            normalize_address(address), {}
        )
        return str(record.get("satellite_id") or "") if isinstance(record, dict) else ""

    def forget_bond(self, address: Any) -> None:
        """Forget bridge-side bond metadata after a Bleak unpair."""
        self.manager.data.get("bluetooth_devices", {}).pop(
            normalize_address(address), None
        )

    def _choose_runtime(
        self,
        address: str,
        satellite_id: str = "",
    ) -> tuple[SatelliteRuntime, int]:
        candidates = [
            row
            for (source, candidate_address), row in self._nearby.items()
            if candidate_address == address
            and source in self._scanners
            and (not satellite_id or row["satellite_id"] == satellite_id)
        ]
        candidates.sort(key=lambda row: (row["rssi"], row["last_seen"]), reverse=True)
        if not candidates:
            raise ValueError(
                "No connected Echo satellite can currently see this device"
            )
        selected = candidates[0]
        runtime = self.manager.runtimes.get(selected["satellite_id"])
        if runtime is None or not runtime.connected:
            raise RuntimeError("The selected Echo satellite is offline")
        return runtime, int(selected["address_type"])

    async def async_pair(
        self,
        address_value: Any,
        pin_value: Any,
        satellite_id: str = "",
    ) -> dict[str, Any]:
        """Pair a radio through the selected or strongest Echo."""
        address = normalize_address(address_value)
        pin = "".join(ch for ch in str(pin_value or "") if ch.isdigit())
        if not address:
            raise ValueError("Choose a valid Bluetooth device")
        if len(pin) != 6:
            raise ValueError("Bluetooth PIN must contain exactly six digits")
        runtime, address_type = self._choose_runtime(address, satellite_id)
        source = scanner_source(runtime)
        connected_client = self._clients.get((source, address))
        opened = connected_client is None
        try:
            if opened:
                connect = await runtime.async_request(
                    "ble.gatt",
                    {
                        "t": "connect",
                        "req": self.next_request_id(),
                        "addr": address,
                        "addr_type": address_type,
                    },
                    timeout=_CONNECT_TIMEOUT,
                )
                if (
                    not connect.get("ok")
                    and connect.get("error") != "already_connected"
                ):
                    raise RuntimeError(
                        "Bluetooth connection failed: "
                        f"{connect.get('error') or 'unknown error'}"
                    )
            result = await runtime.async_request(
                "ble.gatt",
                {
                    "t": "pair",
                    "req": self.next_request_id(),
                    "addr": address,
                    "pin": pin,
                },
                timeout=_CONNECT_TIMEOUT,
            )
            if not result.get("ok"):
                raise RuntimeError(
                    f"Bluetooth pairing failed: {result.get('error') or 'unknown error'}"
                )
            if not all(
                bool(result.get(key))
                for key in ("bonded", "encrypted", "authenticated")
            ):
                raise RuntimeError(
                    "Bluetooth pairing did not establish an authenticated encrypted bond"
                )
            nearby = self._nearby.get((source, address), {})
            self.manager.data.setdefault("bluetooth_devices", {})[address] = {
                "address": address,
                "name": str(nearby.get("name") or address),
                "satellite_id": runtime.device_id,
                "satellite_name": runtime.name,
                "address_type": address_type,
                "paired_at": time.time(),
            }
            await self.manager.async_save()
            return dict(self.manager.data["bluetooth_devices"][address])
        finally:
            if opened:
                with contextlib.suppress(Exception):
                    await runtime.async_request(
                        "ble.gatt",
                        {
                            "t": "disconnect",
                            "req": self.next_request_id(),
                            "addr": address,
                        },
                        timeout=8,
                    )

    async def async_unpair(
        self,
        address_value: Any,
        satellite_id: str = "",
    ) -> None:
        """Remove a device bond from its Echo satellite."""
        address = normalize_address(address_value)
        if not address:
            raise ValueError("Choose a valid Bluetooth device")
        record = self.manager.data.get("bluetooth_devices", {}).get(address, {})
        chosen = satellite_id or str(record.get("satellite_id") or "")
        runtime = self.manager.runtimes.get(chosen)
        if runtime is None or not runtime.connected or not self.supported(runtime):
            raise RuntimeError("The satellite holding this Bluetooth bond is offline")
        result = await runtime.async_request(
            "ble.gatt",
            {
                "t": "forget",
                "req": self.next_request_id(),
                "addr": address,
            },
            timeout=_CONNECT_TIMEOUT,
        )
        if not result.get("ok"):
            raise RuntimeError(
                f"Bluetooth unpair failed: {result.get('error') or 'unknown error'}"
            )
        self.forget_bond(address)
        await self.manager.async_save()

    def snapshot(self) -> dict[str, Any]:
        """Return pairing and scanner data for the management panel."""
        cutoff = time.time() - _ADVERTISEMENT_MAX_AGE
        self._nearby = {
            key: row for key, row in self._nearby.items() if row["last_seen"] >= cutoff
        }
        nearby = sorted(
            self._nearby.values(),
            key=lambda row: (row["rssi"], row["last_seen"]),
            reverse=True,
        )
        return {
            "supported": bool(self._scanners),
            "scanners": [
                {
                    "source": scanner.source,
                    "satellite_id": scanner.runtime.device_id,
                    "satellite_name": scanner.runtime.name,
                    "connected": scanner.runtime.connected,
                    "slots": scanner._slots,
                    "free": scanner._free,
                    "allocated": list(scanner._allocated),
                }
                for scanner in self._scanners.values()
            ],
            "nearby": nearby[:100],
            "paired": sorted(
                (
                    dict(row)
                    for row in self.manager.data.get("bluetooth_devices", {}).values()
                    if isinstance(row, dict)
                ),
                key=lambda row: str(row.get("name") or row.get("address")),
            ),
        }
