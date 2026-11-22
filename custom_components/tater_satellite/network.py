"""Normalize native ESP32 and Echo network reports for diagnostics."""

from __future__ import annotations

from ipaddress import ip_interface
from typing import Any


def _ip(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        address = ip_interface(value.strip()).ip
    except ValueError:
        return ""
    return "" if address.is_unspecified or address.is_multicast else str(address)


def network_snapshot(
    status: dict[str, Any], *, connected: bool, remote: str = ""
) -> dict[str, Any]:
    """Expose reported interfaces without mistaking fallback Wi-Fi for active Wi-Fi."""
    native = status.get("network")
    native = native if isinstance(native, dict) else {}
    echo = status.get("usb_ethernet")
    echo = echo if isinstance(echo, dict) else {}
    active = native.get("active_interface")
    use_echo = not isinstance(active, str) or active not in {
        "usb_ethernet", "ethernet", "wifi", "none"
    }
    if use_echo:
        transport = echo.get("transport")
        active = (
            "usb_ethernet" if transport == "ethernet"
            else "wifi" if transport == "wifi"
            else "usb_ethernet" if echo.get("active") is True else "unknown"
        )
    state = echo.get("state") if use_echo else native.get("usb_ethernet_state")
    state = state[:64] if isinstance(state, str) else ""
    link = native.get("ethernet_link") if not use_echo else None
    link = link if isinstance(link, bool) else None
    ethernet_ip = _ip(echo.get("address") if use_echo else native.get("ethernet_ip"))
    wifi_ip = _ip(native.get("wifi_ip"))
    label = {
        "usb_ethernet": "USB Ethernet", "ethernet": "Ethernet", "wifi": "Wi-Fi",
        "none": "No active interface", "unknown": "Not reported",
    }[active]
    if use_echo and state == "rescue" and active == "wifi":
        label = "Wi-Fi rescue"
    elif use_echo and state == "recovering" and active == "usb_ethernet":
        label = "USB Ethernet (recovering)"
    if not connected:
        active, label, state = "none", "Offline", ""
        ethernet_ip, wifi_ip, link = "", "", None
    return {
        "active_interface": active,
        "connection": label,
        # The socket peer describes the current HA connection, independently
        # of a reported interface change that may still be reconnecting.
        "connection_ip": _ip(remote) if connected else "",
        "ethernet_ip": ethernet_ip,
        "wifi_ip": wifi_ip,
        "ethernet_link": link,
        "usb_ethernet_state": state,
    }
