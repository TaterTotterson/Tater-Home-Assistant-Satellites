"""Network reports describe the active route, independently of attached links."""

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "satellite_network", ROOT / "custom_components/tater_satellite/network.py"
)
network = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(network)


class NetworkStatusTests(unittest.TestCase):
    def snapshot(self, status, connected=True):
        return network.network_snapshot(status, connected=connected, remote="192.0.2.9")

    def test_native_ethernet_keeps_saved_wifi_separate(self):
        status = {"wifi_rssi": -45, "network": {
            "active_interface": "usb_ethernet", "ethernet_ip": "192.0.2.9",
            "wifi_ip": "192.0.2.10", "ethernet_link": True,
            "usb_ethernet_state": "connected", "private": "do not forward",
        }}
        original = copy.deepcopy(status)
        result = self.snapshot(status)
        self.assertEqual(result["connection"], "USB Ethernet")
        self.assertEqual(result["ethernet_ip"], "192.0.2.9")
        self.assertEqual(result["wifi_ip"], "192.0.2.10")
        self.assertTrue(result["ethernet_link"])
        self.assertNotIn("private", result)
        self.assertEqual(status, original)

    def test_wifi_wins_even_when_ethernet_is_attached_or_waiting_for_dhcp(self):
        for link in (True, False):
            result = self.snapshot({"network": {
                "active_interface": "wifi", "ethernet_link": link,
                "ethernet_ip": "0.0.0.0", "usb_ethernet_state": "waiting_for_dhcp",
            }})
            self.assertEqual(result["connection"], "Wi-Fi")
            self.assertEqual(result["ethernet_ip"], "")
            self.assertEqual(result["ethernet_link"], link)

    def test_current_native_report_overrides_legacy_echo_fields(self):
        result = self.snapshot({"network": {"active_interface": "wifi"},
                                "usb_ethernet": {"transport": "ethernet", "state": "rescue"}})
        self.assertEqual(result["connection"], "Wi-Fi")
        self.assertEqual(result["usb_ethernet_state"], "")

    def test_no_active_route_is_not_guessed_to_be_wifi(self):
        result = self.snapshot({"network": {"active_interface": "none"}})
        self.assertEqual(result["connection"], "No active interface")

    def test_echo_active_address_is_ethernet_not_wifi(self):
        result = self.snapshot({"wifi_rssi": -40, "usb_ethernet": {
            "transport": "ethernet", "active": True, "state": "active",
            "address": "192.0.2.9/24", "interface": "eth0",
        }})
        self.assertEqual(result["connection"], "USB Ethernet")
        self.assertEqual(result["ethernet_ip"], "192.0.2.9")
        self.assertIsNone(result["ethernet_link"])  # Echo does not report carrier.

    def test_echo_rescue_and_recovery_do_not_claim_a_healthy_wired_connection(self):
        for transport, state, label in (
            ("wifi", "rescue", "Wi-Fi rescue"),
            ("ethernet", "recovering", "USB Ethernet (recovering)"),
        ):
            result = self.snapshot({"usb_ethernet": {"transport": transport, "state": state}})
            self.assertEqual(result["connection"], label)

    def test_echo_explicit_wifi_transport_wins_over_old_active_flag(self):
        result = self.snapshot({"usb_ethernet": {"transport": "wifi", "active": True}})
        self.assertEqual(result["connection"], "Wi-Fi")

    def test_older_echo_active_flag_remains_usable(self):
        self.assertEqual(self.snapshot({"usb_ethernet": {"active": True}})["connection"], "USB Ethernet")

    def test_offline_hides_stale_addresses_and_link(self):
        result = self.snapshot({"network": {
            "active_interface": "usb_ethernet", "ethernet_ip": "192.0.2.9",
            "ethernet_link": True, "usb_ethernet_state": "connected",
        }}, connected=False)
        self.assertEqual(result["connection"], "Offline")
        self.assertEqual(result["connection_ip"], "")
        self.assertEqual(result["ethernet_ip"], "")
        self.assertEqual(result["usb_ethernet_state"], "")
        self.assertIsNone(result["ethernet_link"])

    def test_bad_or_missing_fields_do_not_fabricate_network_status(self):
        for report in (None, [], {"active_interface": []}, {"active_interface": "future"}):
            self.assertEqual(self.snapshot({"network": report})["connection"], "Not reported")
        result = self.snapshot({"network": {
            "active_interface": "ethernet", "ethernet_link": "false",
            "ethernet_ip": "<invalid>", "wifi_ip": 123,
        }})
        self.assertEqual(result["connection"], "Ethernet")
        self.assertIsNone(result["ethernet_link"])
        self.assertEqual(result["ethernet_ip"], "")
        self.assertEqual(result["wifi_ip"], "")

    def test_connection_ip_is_the_current_socket_peer(self):
        result = self.snapshot({"network": {"active_interface": "wifi", "wifi_ip": "192.0.2.10"}})
        self.assertEqual(result["connection_ip"], "192.0.2.9")
        self.assertEqual(result["wifi_ip"], "192.0.2.10")
        self.assertEqual(network.network_snapshot({}, connected=True, remote="::1")["connection_ip"], "::1")


if __name__ == "__main__":
    unittest.main()
