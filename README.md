<div align="center">
  <a href="https://taterassistant.com">
    <img src="images/tater-home-assistant-satellites-logo.png" alt="Tater Home Assistant Satellites" width="720"/>
  </a>
</div>
<p align="center">
  <a href="https://taterassistant.com">
    <img alt="Visit Tater Assistant" src="https://img.shields.io/badge/Tater%20Assistant-Visit%20Website-F28C28?style=for-the-badge&logo=googlechrome&logoColor=white" />
  </a>
  <a href="LICENSE">
    <img alt="License: GNU AGPL v3" src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" />
  </a>
</p>

# Tater Home Assistant Satellites

Bring your Tater satellites into Home Assistant for voice control, timers,
announcements, and music. They connect directly to Home Assistant Assist, so
the Tater Assistant add-on is not required.

## What you can do

- **Voice:** use Assist, set timers, and play announcements.
- **Music:** play audio, save stereo pairs, and group speakers across rooms.
- **Calls and alerts:** broadcast intercom messages, make Sat Chat calls, and
  send camera alerts to compatible Echo screens or Home Assistant phones.
- **Doorbell:** generate a visitor greeting from a fresh camera image, play it
  through a compatible HA media player, and optionally open the camera on Echo screens.
- **Personalize:** choose wake words and adjust each satellite's sound,
  display, and night settings.
- **Bluetooth:** discover and connect supported Bluetooth devices through a satellite.
- **Optional Tater mode:** use your own language and speech models for voice
  conversations, home control, camera questions, HA lists and weather, music,
  spoken announcements, and delayed device actions.

Available features depend on the satellite's hardware and firmware.

## Get started

### 1. Check the requirements

You need **Home Assistant 2026.6.0 or newer** and a satellite running compatible
Tater firmware:

- [Tater Native Firmware](https://github.com/TaterTotterson/Tater-Native-Firmware)
- [Tater Echo Firmware](https://github.com/TaterTotterson/Tater-Echo-Firmware)
- [Tater ThirdReality S420 Firmware](https://github.com/TaterTotterson/Tater-ThirdReality-Voice-Firmware)
- [Tater SAT1 RPi](https://github.com/TaterTotterson/Tater-SAT1-RPi) — Satellite1 HAT + Raspberry Pi; choose the **satellite** image.

For Home Assistant voice control, have a working Assist pipeline ready.

### 2. Install the integration

On **Home Assistant 2026.11 or newer**, use Marketplace:

[![Add to Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=TaterTotterson&repository=Tater-Home-Assistant-Satellites&category=integration)

1. Open **Settings → Marketplace → Add from link** and enter
   `https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites`.
   Connect GitHub if prompted and choose **Integration** if asked.
2. Install **Tater Native Satellites**, then restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**, search for
   **Tater Satellite**, and add it.

On **Home Assistant 2026.6–2026.10**, [add this repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=TaterTotterson&repository=Tater-Home-Assistant-Satellites&category=integration)
as an **Integration**, then follow steps 2–3 above.
[Manual installation](docs/user-guide.md#manual-installation) is also available.

### 3. Pair your satellite

1. Open **Tater Satellites** in the Home Assistant sidebar.
2. Select **Add satellite** to get a temporary pairing code.
3. Put your satellite into setup mode. On its setup page, enter the
   **Home Assistant URL shown in the panel** and the **pairing code**.
4. Save and let the satellite reboot.

Once the satellite is online, try your wake word and a voice command.
It uses your preferred Assist pipeline by default; open the satellite's
**Voice** settings to choose a different one.

## USB Ethernet and PoE

[Tater Native Firmware **0.7.0**](https://github.com/TaterTotterson/Tater-Native-Firmware/releases/tag/native-0.7.0)
includes USB Ethernet in all four ESP32 satellite images: **SAT1**, **Voice PE**,
**ReSpeaker XVF3800**, and **ESP32-S3-BOX-3**. Supported Echo satellites also
provide USB Ethernet through Tater Echo Firmware.

The tested powered adapter is the
[UCTRONICS B0B9ZLVGJ4 (U6113)](https://www.amazon.com/dp/B0B9ZLVGJ4), the same
adapter used with Echo. It carries Ethernet data over USB and supplies 5 V
power from a compatible PoE switch/injector. For the native USB-C boards, add
a **data-capable Micro-USB female → USB-C male converter**.

1. Update the satellite's firmware from **Firmware & recovery**.
2. Disconnect it from the computer and connect the powered adapter to its
   **ESP32 USB port** (the XIAO port on ReSpeaker, not a separate XMOS audio port).
3. Cold boot through the adapter. Ethernet takes priority after DHCP; saved
   Wi-Fi remains available as fallback.
4. Open the satellite's overview or **Diagnostics** to see its active network
   and connection IP. Diagnostics also show Ethernet/Wi-Fi IPs, Ethernet link,
   and adapter state when reported. Wi-Fi signal is a separate reading and
   does not indicate which connection is active.

Bridge **1.4.23** adds these network details to the panel. Existing pairing and
voice work over either connection; Ethernet does not require pairing again.
To use the native USB console, boot directly on a computer. Reboot through the
adapter to enable USB Ethernet again.

Other powered RTL8152 adapters exposing **USB `0bda:8152` and CDC-ECM
configuration 2** may work with native firmware. Only the linked adapter has
been tested; other chipsets are not enabled. A power-only PoE splitter cannot
provide Ethernet data. A USB-C plug or higher wattage alone does not establish
compatibility. The tested adapter supplies 5 V and does not enable SAT1's
higher-voltage amplifier modes.

Echo follows its own per-device USB and power requirements: Biscuit can receive
power through this adapter; Checkers, Cronos, Crown, Athena, and Rook retain
their normal power supplies. See the
[Native USB Ethernet guide](https://github.com/TaterTotterson/Tater-Native-Firmware/blob/main/docs/usb-ethernet.md)
and [Echo adapter guide](https://github.com/TaterTotterson/Tater-Echo-Firmware#usb-ethernet-adapters)
for setup and recovery details.

## Make it yours

Everything is managed from **Tater Satellites** in the sidebar:

- **Satellites:** open a device to change its name, room, volume, and settings.
- **Voice defaults:** choose a shared wake word and voice settings.
- **Wake arbitration:** choose which satellite answers when several hear you.
- **Tater Audio:** create stereo pairs and manage room playback.
- **Awareness / Vision:** set up camera alerts and image understanding.
- **Assistant:** keep Home Assistant Assist or configure optional Tater mode.

For Bluetooth, wake-word training, calls, and other options, see the
[user guide](docs/user-guide.md).

## Updates and recovery

Update the integration from **Settings → Updates** (or HACS on older versions),
then restart Home Assistant. Update satellite firmware from
**Tater Satellites → Firmware & recovery**.

Echo devices moving from v4.2.3 to the new hardware platform need a one-time
full USB factory upgrade before wireless updates can resume. See
[firmware and recovery instructions](docs/user-guide.md#firmware-updates-and-recovery)
for hardware-specific steps.

## More help

- [User guide](docs/user-guide.md) — detailed setup and feature instructions
- [Release notes](RELEASE_NOTES.md) and [changelog](CHANGELOG.md)
- [Report a problem](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/issues)

## Related projects

- [Tater Native Firmware](https://github.com/TaterTotterson/Tater-Native-Firmware)
- [Tater Echo Firmware](https://github.com/TaterTotterson/Tater-Echo-Firmware)
- [Tater ThirdReality Voice Firmware](https://github.com/TaterTotterson/Tater-ThirdReality-Voice-Firmware)
- [Tater SAT1 RPi](https://github.com/TaterTotterson/Tater-SAT1-RPi) — ready-to-flash Raspberry Pi images for Satellite1.
- [Tater Assistant](https://github.com/TaterTotterson/Tater)
- [Tater Home Assistant Add-ons](https://github.com/TaterTotterson/hassio-addons-tater)

Licensed under [GNU AGPL v3](LICENSE). The name and logo are covered by the
[Tater Trademark Policy](TRADEMARKS.md).
