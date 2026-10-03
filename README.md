<div align="center">
  <a href="https://taterassistant.com">
    <img src="images/tater-home-assistant-satellites-logo.png" alt="Tater Home Assistant Satellites" width="720"/>
  </a>
</div>
<p align="center">
  <a href="https://taterassistant.com">
    <img alt="Visit Tater Assistant" src="https://img.shields.io/badge/Tater%20Assistant-Visit%20Website-F28C28?style=for-the-badge&logo=googlechrome&logoColor=white" />
  </a>
  <a href="https://discord.gg/w52namKyXT">
    <img alt="Join the Tater Assistant Discord" src="https://img.shields.io/badge/Discord-Join%20the%20Community-5865F2?style=for-the-badge&logo=discord&logoColor=white" />
  </a>
</p>

# Tater Home Assistant Satellites

Connect satellites running
[Tater Native firmware](https://github.com/TaterTotterson/Tater-Native-Firmware)
or [Tater Echo firmware](https://github.com/TaterTotterson/Tater-Echo-Firmware),
as well as the
[Tater ThirdReality S420 firmware](https://github.com/TaterTotterson/Tater-ThirdReality-Voice-Firmware),
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
- Optional STT wake verification through each satellite's selected Assist
  pipeline, with Disabled, Observe, and Enabled modes plus per-satellite results
- Announcements, continued conversations, timers, TTS playback, and diagnostics
- Native Home Assistant media-player entities with URL and media-source music
  playback, seek, stop, mute, volume, and dynamic grouping
- Saved left/right stereo-pair media players plus clock-synchronized multi-room
  playback with firmware playhead drift correction
- Secure six-digit first pairing followed by a per-device credential
- Shared voice defaults and per-satellite settings for wake models, sensitivity,
  wake sounds, trainer captures, conversation behavior, AEC, microphone mute,
  LEDs, S3 Box screen brightness and night dimming, and firmware logging
- Per-satellite speaker volume with a main-card slider and a standard Home
  Assistant number entity
- Official Tater Wake Word Catalog selection with versioned microWakeWord
  models shared with the main Tater app
- Custom microWakeWord TFLite and WAV uploads stored inside Home Assistant
- Secure Wake Word Trainer pairing and automatic wake-word publishing
- Board-aware OTA updates and browser USB recovery for Voice PE, Satellite1,
  Satellite1 Beta.1/rev4.1, ReSpeaker XVF3800, and ESP32-S3-BOX-3

## Pair a satellite

1. Open **Tater Satellites** in the Home Assistant sidebar.
2. Select **Add Satellite** to generate a temporary pairing code.
3. Put the satellite into setup mode.
4. In its setup page, enter the Home Assistant URL shown in the panel as the
   server and enter the pairing code.
5. Save and let the satellite reboot.

The firmware automatically appends `/api/tater/satellite/v1/ws`. After the
first connection, Home Assistant replaces the short pairing code with a
device-specific credential. If that first acknowledgement is interrupted, the
same hardware can recover the pending credential with the same pairing code
during a brief retry window. The bridge sends that acknowledgement before
performing device and Assist setup so the satellite can save its credential
without waiting on the rest of the connection. Existing satellites can be
returned to setup mode
using the physical setup-reset gesture documented in the
[Tater Native firmware guide](https://github.com/TaterTotterson/Tater-Native-Firmware#physical-setup-reset).

## Tater Audio, stereo, and multi-room playback

Current Tater Native, Tater Echo, and Tater ThirdReality firmware expose the
same synchronized media-session protocol. The bridge turns every compatible
satellite into a `media_player` entity and coordinates its firmware render
clock directly.

Open **Tater Satellites -> Tater Audio** to save a stereo pair. The pair appears
as its own media player. For stereo pairs and synchronized groups, the bridge
opens the source URL once and serves the same token-protected audio stream to
every member. It routes the left and right channels, schedules one future
audible start, and uses playhead telemetry to correct drift. After a member
reconnects from rebuffering, the bridge waits for decoder recovery before one
bounded catch-up correction. A seek within a pair keeps the same shared source.
Per-channel trim and placement delay are available when a room needs them.
Single-satellite playback still uses its original media URL directly.

Use Home Assistant's **Join media players** action to group any Tater satellite
or saved stereo pair under a group leader. Standalone satellites in such a
group play mono, while saved pairs retain left/right routing. Playing media on
any member controls the synchronized group. **Unjoin media player** returns it
to independent playback.

For Music Assistant, add its **Home Assistant Plugin** and **Home Assistant
Media Players** provider, then enable the Tater media-player entities there.
Music Assistant can hand the bridge its flow URL while the bridge remains the
owner of Tater channel routing, scheduled starts, and ongoing clock correction.

Older firmware without audio-session version 2 or newer remains available for
voice use, but music playback reports that a firmware update is required.

## Push-to-talk intercom

The bridge recognizes the same held-button intercom turn used by the main Tater
app. Hold the satellite action button, speak, and release it to broadcast the
recording to every other connected Tater satellite. The source is excluded from
playback.

Intercom audio bypasses the Home Assistant Assist pipeline, remains only in
bridge memory, and is exposed to target firmware through an opaque short-lived
WAV URL. If a target is playing Tater Audio and supports overlays, its music is
ducked for the message and then resumes. The bridge also fires a
`tater_satellite_intercom` event for start, delivery, cancellation, and failure
states so Home Assistant automations can observe the feature without receiving
the recorded audio.

## Choose a catalog wake word

Open **Tater Satellites -> Voice Defaults**, set **Wake word** to
**Tater Wake Word Catalog**, and choose any versioned model from the official
catalog. Home Assistant validates that the selected JSON package belongs to the
Tater catalog, sends its URL through the existing custom-model firmware path,
and reads the manifest phrase for STT wake verification.

The catalog is fetched asynchronously and cached for ten minutes. If a refresh
temporarily fails, the bridge keeps the last successfully loaded list. You can
still use **Hey Tater**, upload a model, or enter a custom model URL separately.

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
pushes the new model URL and revision to every connected satellite.

## STT wake verification

The **STT Wake Check** tab can send the short wake-word clip to the STT engine
already selected in each satellite's Assist pipeline:

- **Disabled** performs no STT check.
- **Observe** transcribes and scores the wake clip but never delays or blocks
  listening. Use this first to review accuracy and latency.
- **Enabled** opens listening only when the transcript matches. STT timeouts,
  provider errors, and missing STT configuration fail open so transient service
  problems do not disable the satellite. An unknown custom wake phrase is
  blocked until it can be verified.

The expected phrase follows the active built-in wake word or the latest secure
trainer publish automatically. For manually entered microWakeWord URLs, Home
Assistant reads the `wake_word` value from the model's JSON manifest and binds it
to that exact URL. The tab shows each satellite's latest transcript, match score,
latency, accepted/rejected totals, and fail-open results. Wake audio is processed
as a transient in-memory clip and is not stored by this integration.

Settings saves now wait for the connected satellite's reported settings
generation to advance. The per-satellite diagnostics show the desired and active
wake model, download state, settings generation, and confirmation status. Use
**Resend live settings** to resync settings. Reconnects and unchanged settings
keep using the cached model; uploading or publishing a new model changes its
revision and refreshes it.

## Voice timers

Tater satellites use Home Assistant's built-in timer intents, including starting
multiple named timers, checking timer status, cancelling one or all timers,
pausing or resuming, and increasing or decreasing a timer. No custom sentences
or intent scripts are required.

Home Assistant recognizes the request and keeps a transient intent-side mirror.
The satellite owns the actual countdown and alarm, so it continues through a
temporary Home Assistant or network disconnect and rings locally. The timer is
intentionally lost if the satellite reboots or loses power.

## Firmware updates and recovery

The **Firmware & Recovery** tab reads the latest official Tater Native, Tater
Echo, and Tater ThirdReality release manifests and matches images by the
firmware target reported by each satellite. Home Assistant downloads the
requested image, verifies its published size and SHA-256 hash, and exposes it
through a short-lived local URL. Echo Dot 2 (`biscuit`), Echo Show 5 first
generation (`checkers`), and ThirdReality Voice & Music Assistant
(`thirdreality_s420`) receive the same update entity, availability check,
progress, reboot verification, and OTA flow as the other satellites.

- Use **Install update** for a connected satellite. The integration sends the
  board-matched OTA image and tracks progress through the satellite entity.
- Use **Browser USB Flasher** for a first flash, recovery, or a wired update.
  Select the hardware and use Chrome or Edge from your normal Home Assistant
  page—there is no separate HTTPS requirement in the integration.

Echo factory installation is intentionally not offered through ESP Web Tools.
Use the model-specific factory archive and installer published by Tater Echo
Firmware. After that first installation, normal Biscuit and Checkers updates
are wireless from Home Assistant.

ThirdReality S420 factory installation and recovery are also intentionally not
offered through ESP Web Tools. They use the Amlogic Tater Local USB flow and
require the ThirdReality debug board. Once Tater firmware is installed, signed
S420 `.swu` updates are wireless from Home Assistant.

The USB flasher offers two choices. **Factory** writes the release's merged
image and erases the satellite. **OTA Update · Keep Settings** writes only the
application slots and preserves Wi-Fi, pairing, and saved settings.

Satellite1 Public Batch #1 / Beta.1 HAT and Core rev4.1 uses its own
`Satellite1 Beta.1 / rev4.1` firmware choice. Select it explicitly for the
first USB install; Public Batch #2 and later hardware should use `Satellite1`.
After pairing, the distinct board IDs keep OTA updates on their matching
firmware channels.

## Related projects

- [Tater Assistant](https://github.com/TaterTotterson/Tater)
- [Tater Native Firmware](https://github.com/TaterTotterson/Tater-Native-Firmware)
- [Tater Echo Firmware](https://github.com/TaterTotterson/Tater-Echo-Firmware)
- [Tater ThirdReality Voice Firmware](https://github.com/TaterTotterson/Tater-ThirdReality-Voice-Firmware)
- [Tater Home Assistant Add-ons](https://github.com/TaterTotterson/hassio-addons-tater)
