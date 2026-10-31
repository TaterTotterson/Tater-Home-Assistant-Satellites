<div align="center">
  <a href="https://taterassistant.com">
    <img src="images/tater-home-assistant-satellites-logo.png" alt="Tater Home Assistant Satellites" width="720"/>
  </a>
</div>
<p align="center">
  <a href="https://taterassistant.com">
    <img alt="Visit Tater Assistant" src="https://img.shields.io/badge/Tater%20Assistant-Visit%20Website-F28C28?style=for-the-badge&logo=googlechrome&logoColor=white" />
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
- Direct Sat Chat audio and video calls between compatible satellites, relayed
  locally over their existing authenticated connections
- Echo screen Climate and Cameras panels, including continuous Home Assistant
  camera streams with automatic snapshot fallback
- Native Home Assistant media-player entities with URL and media-source music
  playback, seek, stop, mute, volume, and dynamic grouping
- Saved left/right stereo-pair media players plus Sendspin-synchronized
  multi-room playback
- Secure six-digit first pairing followed by a per-device credential
- Native Home Assistant Bluetooth proxying through compatible Echo satellites,
  including active GATT connections and six-digit PIN pairing without storing
  the PIN
- One shared wake profile with MWW, OWW, NWW, MWW + OWW, and MWW + NWW modes;
  ESP32 and older firmware safely receive the matching MWW fallback
- Shared voice defaults and per-satellite settings for sensitivity, wake sounds,
  trainer captures, conversation behavior, AEC, microphone mute, voice-state
  LEDs, music-reactive ring animations on supported Echo and ESP satellites,
  display brightness, automatic room-light dimming, scheduled night display,
  and firmware logging
- Per-satellite speaker volume with a main-card slider and a standard Home
  Assistant number entity
- Satellite1 output routing with automatic jack detection plus Internal, AUX,
  and simultaneous Internal + AUX modes
- Official Tater Wake Word Catalog selection with all MWW generations, OWW
  bundles from V7 onward, and NWW bundles from V8 onward
- Custom microWakeWord TFLite uploads, schema-v1 and schema-v3 trainer wake
  bundles, NanoWakeWord CNN/GRU selection, and custom WAV wake sounds
- Secure Wake Word Trainer pairing and automatic wake-word publishing
- Board-aware OTA updates and browser USB recovery for Voice PE, Satellite1,
  Satellite1 Beta.1/rev4.1, ReSpeaker XVF3800, ESP32-S3-BOX-3, and all Tater
  Echo targets

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

## Bluetooth through an Echo satellite

Echo Dot 2nd Generation (Biscuit), Echo 2nd Generation (Radar), Echo Show 5 1st
Generation (Checkers), Echo Show 8 1st Generation (Crown), Echo Show 8 2nd
Generation (Athena), and Echo Spot 1st Generation (Rook) satellites running
current Tater Echo Firmware can act as native Home Assistant Bluetooth
scanners. Advertisements and active GATT traffic use the satellite's existing
authenticated WebSocket; no separate Bluetooth bridge service or network
listener is required.

Open **Tater Satellites -> Bluetooth** to see connected Echo scanners and nearby
devices. For a PIN-protected peripheral, choose the Echo that will hold the bond,
enter the device's six-digit Bluetooth PIN, and select **Pair**. The PIN is sent
only for that pairing attempt and is not saved. Home Assistant then uses the
bonded Echo as the device's connectable Bluetooth path. Use **Unpair** to remove
the saved bond from that Echo.

## Display brightness and night mode

Open a screen satellite's settings in **Tater Satellites** to set its normal
brightness and daily night schedule. Echo Show 5 (Checkers), both Echo Show 8
generations (Crown and Athena), and Echo Spot (Rook) can also follow their
ambient-light sensor with a selectable minimum brightness. Night mode can dim
the normal display, show a low-brightness red clock, or turn the screen off.
Calls, timers, and voice activity remain visible when the red-clock mode is
active.

The controls are exposed per satellite and only when Echo firmware advertises
the screen power-management capability. ESP32-S3-BOX-3 retains its established
manual-brightness and scheduled-dimming controls.

## Tater Audio, stereo, and multi-room playback

Current Tater Native, Tater Echo, and Tater ThirdReality firmware expose a
Sendspin v1 player on port `8928`. The bridge turns every compatible satellite
into a `media_player` entity, decodes each Home Assistant media URL once, and
publishes one timestamped 48 kHz stereo PCM timeline to every selected player.
Sendspin owns clock selection, buffering, and drift correction on the devices.

Open **Tater Satellites -> Tater Audio** to save a stereo pair. The pair appears
as its own media player. The bridge assigns persistent left/right Sendspin
output modes and keeps per-channel trim and placement delay available for room
calibration. Single speakers, saved pairs, and dynamic groups all use the same
Sendspin transport. Seeking starts a new synchronized timeline at the requested
source position.

Use Home Assistant's **Join media players** action to group any Tater satellite
or saved stereo pair under a group leader. Standalone satellites in such a
group play mono, while saved pairs retain left/right routing. Playing media on
any member controls the synchronized group. **Unjoin media player** returns it
to independent playback.

Music Assistant can discover updated satellites directly as Sendspin players.
That is the preferred route when Music Assistant owns playback. The bridge's
Home Assistant media-player entities remain available for Home Assistant media
services, saved stereo pairs, and groups; avoid enabling both representations
of the same physical satellite in one Music Assistant group.

Older firmware without Sendspin v1 remains available for voice use, but music
playback reports that a firmware update is required.

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

## Sat Chat

Compatible Echo satellites can start live audio or video calls from their Sat
Chat screen. Home Assistant keeps only the transient call directory and routes
16 kHz PCM plus tagged JPEG frames directly between the two authenticated
satellite WebSockets. Sat Chat does not enter the Assist pipeline and no call
audio, video, or history is persisted.

Video uses a one-frame best-effort queue. If a receiving display briefly falls
behind, the bridge discards the old waiting image and sends the newest one so
live audio and call controls remain responsive. Calls end automatically when
either satellite disconnects.

## Configure wake words

Open **Tater Satellites -> Voice Defaults**. The bridge keeps one wake profile
for every connected satellite. Choose a single-model or dual-model policy:

- **MWW** uses the same microWakeWord selection on every satellite. Choose
  built-in Hey Tater, a catalog model, an uploaded model, or a custom package
  URL.
- **OWW** uses openWakeWord alone on capable satellites. ESP32
  and other MWW-only satellites automatically use the matching microWakeWord
  half of the same profile.
- **NWW** uses a selected NanoWakeWord CNN or GRU model on capable satellites,
  with the matching MWW fallback everywhere else.
- **MWW + OWW** and **MWW + NWW** require both selected detectors to agree
  before a capable satellite opens the microphone. MWW-only firmware keeps the
  matching MWW half.

For custom companion or dual detection, select the canonical
`.wake-bundle.json` produced by a Tater Wake Word Trainer. Home Assistant
supports schema-v1 through schema-v3 bundles, including the new bundles that
can contain MWW, OWW, NWW CNN, and NWW GRU together. The bridge validates the
selected engine, reads the trainer-tested threshold/window/patience values, and
sends only the models each satellite can run.

Model-specific override cards appear for the engines active in the selected
policy. With an override disabled, the trainer bundle values remain in effect.
Wake sensitivity and environment—including **TV Nearby**—remain per-satellite
room settings.

## Choose a catalog microWakeWord

While using MWW, set **Wake word** to **Tater Wake Word Catalog** and choose any
versioned model. Companion modes offer only compatible bundles: OWW starts at
V7 and NWW starts at V8. Home Assistant validates that the selected package
belongs to the official catalog before sending it to satellites.

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
Assistant stores only its hash. A published microWakeWord URL must belong to the
linked trainer and point to its trained wake-word API. Publishing selects MWW
mode for the shared profile, clears conflicting per-satellite wake overrides,
and pushes the new model to every connected satellite. Select a matching wake
bundle afterward if you want to switch the shared profile back to Dual mode.

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
through a short-lived local URL. Echo Dot 2 (`biscuit`), Echo 2 (`radar`), Echo
Show 5 first generation (`checkers`), Echo Show 8 first generation (`crown`),
Echo Show 8 second generation (`athena`), Echo Spot first generation (`rook`),
and ThirdReality Voice & Music Assistant (`thirdreality_s420`) receive the same
update entity, availability check, progress, reboot verification, and OTA flow
as the other satellites.

- Use **Install update** for a connected satellite. The integration sends the
  board-matched OTA image and tracks progress through the satellite entity.
- Use **Browser USB Flasher** for a first flash, recovery, or a wired update.
  Select the hardware and use Chrome or Edge from your normal Home Assistant
  page—there is no separate HTTPS requirement in the integration.

Echo factory installation is intentionally not offered through ESP Web Tools.
Use the model-specific factory archive and installer published by Tater Echo
Firmware. After that first installation, normal Biscuit and Checkers updates
are wireless from Home Assistant, as are Radar, Crown, Athena, and Rook updates.
When an older screen build needs the newer component-aware updater, Home
Assistant installs the published compatibility bridge, verifies its capability
after reboot, and then sends the final release automatically.

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
