<div align="center">
  <a href="https://taterassistant.com">
    <img src="images/tater-home-assistant-satellites-logo.png" alt="Tater Home Assistant Satellites" width="720"/>
  </a>
</div>
<h3 align="center">
  <a href="https://taterassistant.com">taterassistant.com</a>
</h3>

# Tater Home Assistant Satellites

Connect satellites running
[Tater Native firmware](https://github.com/TaterTotterson/Tater-Native-Firmware)
directly to Home Assistant and use them as native Assist satellites.

This custom integration is a protocol adapter. It does not modify Home
Assistant, Tater, or the satellite firmware, and the Tater Assistant add-on does
not need to be installed or running.

## Install with HACS

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TaterTotterson&repository=Tater-Home-Assistant-Satellites&category=integration)

After adding the repository:

1. Install **Tater Native Satellites** in HACS.
2. Restart Home Assistant.
3. Open **Settings -> Devices & services -> Add integration**.
4. Search for **Tater Satellite** and add it.

Home Assistant 2026.6.0 or newer is required.

For a manual install, copy `custom_components/tater_satellite` into
`/config/custom_components/tater_satellite`, restart Home Assistant, and add the
integration from **Devices & services**.

## Features

- A Home Assistant Assist satellite entity for every paired device
- Local wake-word activation with 16 kHz mono PCM sent into the selected Assist
  pipeline
- Announcements, continued conversations, timers, TTS playback, and diagnostics
- Secure six-digit first pairing followed by a per-device credential
- Shared voice defaults and per-satellite settings for wake models, sensitivity,
  wake sounds, trainer captures, conversation behavior, AEC, microphone mute,
  LEDs, and firmware logging
- Device-owned speaker volume, so changing volume on a satellite is not
  overwritten by Home Assistant
- Custom microWakeWord TFLite and WAV uploads stored inside Home Assistant
- Secure Wake Word Trainer pairing and automatic wake-word publishing
- Board-aware OTA updates and browser USB recovery for Voice PE, Satellite1,
  ReSpeaker XVF3800, and ESP32-S3-BOX-3

## Pair a satellite

1. Open **Tater Satellites** in the Home Assistant sidebar.
2. Select **Add Satellite** to generate a temporary pairing code.
3. Put the satellite into setup mode.
4. In its setup page, enter the Home Assistant URL shown in the panel as the
   server and enter the pairing code.
5. Save and let the satellite reboot.

The firmware automatically appends `/api/tater/satellite/v1/ws`. After the
first connection, Home Assistant replaces the short pairing code with a
device-specific credential. Existing satellites can be returned to setup mode
using the physical setup-reset gesture documented in the
[Tater Native firmware guide](https://github.com/TaterTotterson/Tater-Native-Firmware#physical-setup-reset).

## Link the Wake Word Trainer

The Apple Silicon and NVIDIA microWakeWord trainers can securely publish a newly
trained wake word directly to every Home Assistant-connected Tater satellite:

1. Open **Tater Satellites -> Wake Word Trainer**.
2. Select **Link Trainer** to generate a temporary code.
3. In the trainer, open **Auto -> Link Tater**.
4. Enter the Home Assistant address shown in the Tater Satellites panel and the
   temporary code.

After pairing, the trainer stores a device-specific credential and Home
Assistant stores only its hash. A published wake-word URL must belong to the
linked trainer and point to its trained wake-word API. Publishing updates the
shared wake word, clears conflicting per-satellite wake-word overrides, and
pushes the new model URL to every connected satellite.

## Firmware updates and recovery

The **Firmware & Recovery** tab reads the latest official Tater Native release
manifest and matches images by the board ID reported by each satellite. Home
Assistant downloads the requested image, verifies its published size and
SHA-256 hash, and exposes it through a short-lived URL.

- Use **Install update** for a connected satellite. The integration sends the
  board-matched OTA image and tracks progress through the satellite entity.
- Use **Browser USB Recovery** for a first flash or a satellite that cannot
  reconnect. Select the hardware and use Chrome or Edge over a secure Home
  Assistant connection.

USB recovery writes the release's merged factory image. OTA writes only the
application image and preserves the satellite's Wi-Fi and pairing data.

## Related projects

- [Tater Assistant](https://github.com/TaterTotterson/Tater)
- [Tater Native Firmware](https://github.com/TaterTotterson/Tater-Native-Firmware)
- [Tater Home Assistant Add-ons](https://github.com/TaterTotterson/hassio-addons-tater)
