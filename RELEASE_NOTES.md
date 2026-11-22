# Tater Satellite 1.4.23

## What's changed

- **Live network diagnostics.** Show the active connection and connection IP
  in the satellite overview. Diagnostics add Ethernet/Wi-Fi IPs, Ethernet link,
  and USB adapter state when reported. Keep Wi-Fi signal separate from the
  active connection, including when Wi-Fi remains connected as fallback.
- **Native ESP32 and Echo reports.** Read the new Native Firmware network
  fields and existing Echo USB Ethernet reports. Preserve Echo Wi-Fi rescue
  and wired recovery labels. Show unavailable fields as not reported and clear
  live network indicators when a satellite disconnects.
- **ESP32 USB Ethernet and PoE.** Native Firmware **0.7.0** includes USB Ethernet
  in the standard **SAT1**, **Voice PE**, **ReSpeaker XVF3800**, and
  **ESP32-S3-BOX-3** images. Update the matching satellite image through
  **Firmware & recovery**. Pairing and voice use the existing protocol over
  either network connection.
- **Adapter setup and README.** Document the powered
  [UCTRONICS B0B9ZLVGJ4 (U6113)](https://www.amazon.com/dp/B0B9ZLVGJ4), the same
  adapter used with Echo. For native USB-C boards, use a **data-capable
  Micro-USB female → USB-C male converter**, connect to the ESP32 USB port,
  and cold boot through the powered adapter. Saved Wi-Fi remains available
  as fallback after Ethernet takes priority through DHCP.
- **Compatibility guidance.** Other powered RTL8152 adapters exposing USB
  `0bda:8152` and CDC-ECM configuration 2 may work with native firmware; only
  the linked adapter has been tested. Other chipsets are not enabled, and
  power-only PoE splitters do not carry USB Ethernet data. The tested adapter
  supplies 5 V and does not enable SAT1's higher-voltage amplifier modes.
  Echo power and connector requirements remain specific to each model.

## Updating

Install bridge **1.4.23** through Marketplace or HACS, then restart Home
Assistant. Existing pairing and settings are retained. Update ESP32 satellites
separately to [Native Firmware 0.7.0](https://github.com/TaterTotterson/Tater-Native-Firmware/releases/tag/native-0.7.0)
for USB Ethernet support. The bridge reads the current official firmware
catalog automatically; this bridge update adds the network display.

See [USB Ethernet and PoE](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites#usb-ethernet-and-poe)
for setup, adapter alternatives, and Echo power differences.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.22...v1.4.23)
