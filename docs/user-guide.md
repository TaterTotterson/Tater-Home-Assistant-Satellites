# User guide

Detailed setup and feature instructions for Tater Home Assistant Satellites.
For a quick start, return to the [README](../README.md).

## Find what you need

- [Installation](#installation) and [pairing](#pair-a-satellite)
- [Panel and satellite settings](#bridge-workspace)
- [Optional Tater assistant mode](#tater-assistant-mode)
- [Camera alerts](#awareness-camera-alerts)
- [Bluetooth](#bluetooth-through-a-satellite)
- [Display and night mode](#display-brightness-and-night-mode),
  [speaker equalizer](#speaker-equalizer-and-bass-protection), and
  [Do Not Disturb](#do-not-disturb)
- [Music, stereo, and multi-room playback](#tater-audio-stereo-and-multi-room-playback)
- [Intercom](#push-to-talk-intercom) and [Sat Chat](#sat-chat)
- [Wake words](#configure-wake-words), [catalog models](#choose-a-catalog-microwakeword),
  [trainer linking](#link-the-wake-word-trainer), and
  [STT wake verification](#stt-wake-verification)
- [Wake arbitration](#wake-arbitration)
- [Voice timers](#voice-timers)
- [Firmware updates and recovery](#firmware-updates-and-recovery)

## Installation

Home Assistant 2026.6.0 or newer is required.

### Marketplace — Home Assistant 2026.11 and newer

[![Open this repository in Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=TaterTotterson&repository=Tater-Home-Assistant-Satellites&category=integration)

1. Open **Settings → Marketplace** and select **Add from link**.
2. Enter `https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites`
   and select **Add**. Connect GitHub when prompted. If asked for the content
   type, select **Integration**.
3. Open **Tater Native Satellites** and select **Install**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration**, search for
   **Tater Satellite**, and add it.

When upgrading to Home Assistant with Marketplace, existing HACS installations
migrate automatically; the bridge does not need to be reinstalled. See the
[Home Assistant Marketplace documentation](https://www.home-assistant.io/integrations/marketplace/).

### HACS — older Home Assistant versions

For Home Assistant 2026.6–2026.10, use HACS to add this repository as an
**Integration**:

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TaterTotterson&repository=Tater-Home-Assistant-Satellites&category=integration)

Install **Tater Native Satellites**, restart Home Assistant, then add
**Tater Satellite** under **Settings → Devices & services → Add integration**.

### Updates

Install bridge updates from **Settings → Updates**, then restart Home Assistant
to apply them. On older Home Assistant versions, continue updating through HACS.

### Manual installation

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
- Bridge-side wake arbitration to choose one satellite when several hear you,
  with room or whole-home scope, audio comparison, and adjustable timing
- Direct Sat Chat audio and video calls between compatible satellites, relayed
  locally over their existing authenticated connections, with capability-gated
  H.264 on updated Echo Shows/Spot and JPEG fallback for other pairs
- Echo screen Climate and Cameras panels, including continuous Home Assistant
  camera streams with automatic snapshot fallback
- Awareness camera monitors in HA and Mini-Tater mode, with shared Vision
  settings and image-and-description alerts to Echo screens and HA phones
- Native Home Assistant media-player entities with URL and media-source music
  playback, seek, stop, mute, volume, and dynamic grouping
- Saved left/right stereo-pair media players plus Sendspin-synchronized
  multi-room playback
- Secure six-digit first pairing followed by a per-device credential
- Native Home Assistant Bluetooth proxying through compatible satellites,
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

## Bridge workspace

The **Tater Satellites** panel groups its navigation into **Tater assistant**,
**Your home** (Satellites, Awareness, Vision, Tater Audio, and Bluetooth), **Voice & wake** (Voice
defaults, STT wake check, and Wake Word Trainer), and **Maintenance** (Firmware &
recovery).

Search satellites by name, room, or hardware, then select **Open** for focused
device sections. Settings appear only where the satellite supports them. Shared
voice defaults have separate Wake profile, Conversation, Wake sound, and
Diagnostics sections; additional schema sections remain available under Other
settings. Unsaved drafts stay available while moving between these workspaces.
Save each section to apply it to the bridge.

In a satellite's **Overview → Name & room**, edit the fields and select **Save
name & room**. On updated Native, Echo, and ThirdReality firmware, changes are
saved on the satellite and apply live without resetting or pairing again. You
can also edit the device name and area in **Settings → Devices & services**;
the bridge sends those edits to the satellite and waits for confirmation.
Connect the satellite before editing; older firmware requires an update.

On updated Echo GPU UIs, each satellite's **Display & Night → Conversation
text** selects **Smooth** (the default) or **Matrix** for recognized speech
and replies. Matrix cycles symbols before letters settle in a shuffled order.
The choice affects only that satellite; changes made on its touchscreen are
saved back to the same override. Older firmware and non-Echo screens hide the
option. Software-rendered screens keep the text readable without the effect.

Use **Server & pairing** to view the Home Assistant address and active pairing
code. **Add satellite** generates a new temporary pairing code.

### Dashboard Studio

**Your home → Dashboard Studio** is available in both assistant modes. Open
**AI connection** to open its own settings workspace for the OpenAI-compatible
API base URL, model, and API key (optional for local providers). Save, then use
**Back to Studio** to return to your design. Studio uses this independent
connection for its dedicated dashboard design chat.
Start with **Choose for me** or a room, tablet, energy, or security layout, then
refine the draft conversationally. Use the phone/tablet/desktop previews before
applying. Draft undo and backups let you reverse changes; newer HA edits are
checked before saving. Switching assistant modes keeps Studio and saved designs
available.
See the [Dashboard Studio guide](dashboard-studio.md) for details.

### Tater assistant mode

The **Assistant** workspace selects who owns the complete voice turn. **Home
Assistant** is the default and keeps the existing Assist pipeline unchanged.
Selecting **Tater** immediately reveals its Models & speech, Home tools, and
Hydra workspaces; selecting Home Assistant hides them again. Save the Assistant
workspace to apply the selected pipeline to voice turns. **Tater** sends the
satellite microphone stream through its configured speech-to-text provider,
Hydra, Home Assistant device control, and its configured text-to-speech provider
before returning audio to the originating satellite.

Configure an OpenAI-compatible language model and either OpenAI-compatible or
Wyoming STT and TTS under **Models & speech**. Image understanding defaults to
**Same as Base** for a multimodal Base model, or can use a separate
OpenAI-compatible Vision URL, model, and API key. Official OpenAI endpoints
require an API key; local compatible endpoints may run without one. Provider
keys stay in Home Assistant storage and are never returned by the management API.
Wyoming model and voice names are optional and remain blank unless the Wyoming
service requires a specific name.

Mini-Tater runs the same three Hydra roles as Tater: **Astraeus** creates a
bounded atomic plan, **Thanatos** executes each locked Home Assistant action,
and **Hermes** writes the final response from verified results. By default all
three heads share the Base language model. Enable **Beast Mode** to keep any
role on Base or give it a dedicated OpenAI-compatible endpoint, model, and API
key.

Mini-Tater supplies the asking satellite's name and firmware-configured room to
every Hydra head and the plan review, using the same default-room rule as Tater. Requests
such as "turn on the lights" use that room unless the user names another room
or a specific device. Each turn reads the room again; management chat has no
assumed room, and an unassigned satellite never supplies a guessed location.

**Continued conversation** works with both modes when enabled on the satellite.
In Home Assistant mode, the selected conversation agent must request a follow-up.
In Mini-Tater mode, a short model check follows Tater's approach: reopen after a
direct question or invitation to answer, not after an ordinary confirmation.
The satellite reopens after successful reply playback and keeps the conversation
ID. A failed or timed-out follow-up check leaves the microphone closed without
preventing the reply from playing.

The satellite's confirmed saved room remains the source of truth. On updated
firmware, an explicit HA area assignment or area rename is saved onto the
satellite. If saving fails, the bridge restores the last confirmed assignment.
Reconnects match the satellite's saved room to a Home Assistant area, creating
the area if needed. A blank room leaves the satellite unassigned. Room matching
does not move other Home Assistant devices, and existing entity IDs remain
unchanged when a device is renamed. Older firmware retains room matching but
cannot accept live name or room changes.

Tater mode automatically uses Home Assistant's built-in Neural Micro VAD to
end command capture after speech. It uses
the default endpoint timing automatically and exposes no Tater-mode VAD options.
Command audio is forwarded to STT immediately after the firmware wake boundary,
including while neural VAD initializes. VAD controls when capture ends; a short
command is not discarded just because VAD never marked a speech start. Empty
STT transcripts are still rejected before Hydra runs.

Mini-Tater has nine built-in capabilities: `device_control`, `tater_vision`,
`voicepe_remote_timer` (Timer), `todo_list`, `weather_forecast`, `broadcast`,
`music_assistant`, `schedule_home`, and `web_search`.
Astraeus receives the same kind of stable tool catalog used by Tater, plans
atomic natural-language steps, and Thanatos passes each locked step unchanged as
`query` to the selected tool. Device control interprets actions and values,
resolves Home Assistant friendly names, aliases, rooms, floors, and supported services,
and rechecks entity scope before execution. Deterministic parsing runs first;
unclear wording or ambiguous names can use a bounded Thanatos model call like
Tater's Device Control Verba.

Every model request receives the current date, time, and timezone from Home
Assistant, following Tater's live-clock prompt. Date and time questions need no
additional tool or setting. All three Hydra roles receive this clock, including
when Beast Mode uses separate models.

The additional tools follow the Shop Verbas' natural-language approach. Home
tools use Home Assistant's configured integrations:

- **Shopping & to-do lists:** read pending items, add items, mark them complete,
  or remove them. Name a list when more than one could match. Changes are saved
  to the actual HA list; duplicate item names require clarification.
- **Weather:** read current conditions or daily, hourly, or twice-daily forecasts
  when the selected HA weather integration provides them. No additional weather
  account is needed. A location must match a configured weather entity.
- **Spoken announcements:** explicitly ask to broadcast a message to a named
  room/satellite or everywhere. Tater satellites use Mini-Tater's configured
  voice; other exposed HA announcement satellites use their configured pipeline.
  Offline or failed destinations are reported.
- **Music & playback:** play or queue named media through Music Assistant or a
  HA player that supports media search. Pause, resume, skip, stop, mute, and
  adjust volume. Name the player/room in chat; satellite requests can use their
  assigned room. Available actions depend on the selected player.
- **Delayed device actions:** for example, “turn off the office lights in five
  minutes.” Ask to list or cancel pending actions. Scheduling keeps the resolved
  device targets, saves the job in HA, and checks the selected entity scope again
  before running. Pending jobs survive HA restarts; jobs more than a minute late
  after an outage are marked missed instead of replayed. An interrupted action
  with an unknown outcome is not retried automatically. Actions may be scheduled
  up to seven days ahead, with at most 50 pending jobs.
- **Web search:** ask for current online information or an explicit lookup.
  DuckDuckGo search needs no API key, account, or provider settings, with an
  automatic key-free Bing fallback when DuckDuckGo cannot return results. Mini-Tater
  summarizes search snippets and shows clickable source links in chat, keeping
  URLs out of the spoken reply. Searches run outside HA's event loop and repeated
  queries are cached for two minutes. This uses unofficial search-page access;
  blocked, rate-limited, empty, and timed-out searches are reported clearly.

Device control also supports thermostat fan modes, mower start/dock, relative
speaker volume and mute, and vacuum cleaning of named HA areas on compatible
devices. Vacuum room cleaning uses HA's cleaning-area action, so the vacuum must
support that action and the requested areas.

Tater Vision mirrors the Tater Shop Verba for current visual questions. It can
resolve a named Home Assistant camera, room, outdoor area, or the asking
satellite's assigned room, capture fresh ephemeral stills, and use the existing
Vision setting from the shared **Vision** workspace. **Same as Base** uses the Base endpoint,
model, and key; the dedicated option uses the existing separate Vision endpoint,
model, and key. Raw camera images are not stored in conversation history or the
Hydra ledger. Mini Tater does not load Cores, Portals, Shop items, downloaded
Verbas, file tools, or external messaging tools. Under **Home tools**,
choose entities exposed to Assist or all supported Home Assistant entities. The
scope applies to lists, weather, media players, and other HA entity targets too.

The **Hydra** workspace shows conversation counts, Astraeus plans and reviews,
Thanatos actions, Hermes responses, timing, and bounded conversation history.
Compound requests are split into atomic steps so different devices can receive
different commands during one turn. Use the text test on the Assistant page to
verify the models and built-in tools without recording audio. The same chat accepts
up to four JPEG, PNG, WebP, or GIF attachments. Vision produces bounded visual
context first, then the request continues through the normal audited Hydra flow;
raw image data is never written to conversation history or the Hydra ledger.

**Timer** follows the Tater Shop Verba's description and natural-language `query`
contract. Ask to start named timers, check time remaining, pause/resume, add or
remove time, cancel or silence an alarm, or snooze (five minutes by default).
The satellite owns running countdowns and alarms, so they continue while
disconnected; the bridge queries live state without resetting running timers
on reconnect. Pausing confirms removal of the running satellite timer and saves
its remaining time in HA; resuming confirms rearming the same timer. Paused timers
remain paused across HA restarts and require HA and the satellite online to
resume. Start durations and adjusted remaining time
are capped at two hours, matching the Verba default. Voice requests use the
asking satellite; in management chat, name the destination satellite or room.
When a room or timer selection is ambiguous, Mini-Tater asks which one to use.

## Awareness camera alerts

**Awareness** and **Vision** remain available in both Home Assistant and
Mini-Tater mode. Camera alerts call the shared Vision model directly; they do not
run Hydra, change the active conversation agent, or require Tater speech setup.
Under **Vision**, reuse an image-capable Base model or choose **Different
endpoint** and enter a Vision URL, model, and optional API key. Existing Vision
settings are preserved and are shared with Mini-Tater camera questions and chat.

In **Awareness**, select **Add monitor**, then choose:

1. A Home Assistant camera.
2. A binary sensor, doorbell/event entity, or toggle helper and its trigger.
   Entities attached to the camera's HA device are suggested first. Only event
   types supplied by that entity are offered, along with **Any event**.
3. One or more connected or saved Echo screens with notification support and/or
   Home Assistant Companion phone notification destinations.

Save the monitor, then use **Test monitor** to send an actual alert. Optional
settings provide a cooldown (60 seconds by default) and a short instruction
about what Vision should focus on. Pause a monitor by clearing **Enabled**.
Camera selection is explicit and independent of conversational Assist exposure.

When the trigger fires, the bridge captures a fresh image before waiting for a
model slot, obtains a concise description, and delivers that same image and
description to each destination. Screen delivery uses the existing authenticated
satellite connection. Phones use HA's authenticated local media attachments;
the `media_source` integration is loaded automatically. Phone image delivery
requires a configured HA media directory and the phone's normal remote access
to Home Assistant. A failed or offline destination does not block the others.

**Recent activity** shows the last 50 runs, including tests, descriptions, and
individual delivery errors. Snapshots expire after one hour and are also removed
when their activity falls out of history. Thumbnails use short-lived signed HA
URLs. Raw image data is not saved in conversation history or the Hydra ledger.
Work is bounded to eight pending monitors and two simultaneous Vision calls;
repeated triggers for a busy monitor are coalesced. Restarting HA preserves saved
monitors, recent activity, and the last-run cooldown. Editing, pausing, or deleting
a monitor cancels any pending alert for that monitor.

## Doorbell greetings and live camera popups

**Doorbell** is available in both Home Assistant and Mini-Tater modes. Choose
**Add doorbell** and set up:

1. The doorbell press sensor or event entity and the event that means a press.
2. The camera to use for the snapshot and live view.
3. An optional AI greeting, its instructions, and the greeting speaker. Any HA
   media player that supports playing the generated audio can be selected,
   including a UniFi Protect doorbell speaker or a separate speaker from another
   integration. The trigger, camera, and speaker can belong to different devices.
4. Optional Show or Rook screens and a display duration of 10–300 seconds.

Greeting images use the existing **Vision** settings. In HA mode, speech uses
the TTS provider, language, and voice in HA's default Assist pipeline. Mini-Tater
mode uses the existing Mini-Tater TTS settings. Complete audio clips are sent
through HA's normal media-player playback action; audio format support and
network reachability depend on the selected media player.

Automatic camera opening requires Echo firmware 5.0.4 or newer with camera popup support.
Older screen firmware is listed with an update note. Screens open independently
of the greeting and automatically close after the selected duration; a visitor
can also dismiss the popup. Manual camera navigation takes ownership of its
view so an earlier popup's timeout cannot close it. A model, speaker, or screen
failure is reported separately and does not block the other outputs. Clear
**AI greeting** to use camera viewing without Vision or TTS.

The default cooldown is 30 seconds. Repeated presses are ignored while a run is
busy or cooling down. Doorbells, cooldown history, and the last 50 activity
results persist across HA restarts; images are only sent to Vision and are not
retained by this feature. Editing, pausing, or deleting a doorbell cancels its
pending greeting. **Test doorbell** runs the saved setup and sends actual audio
and camera popups; it does not enable a paused doorbell.

## Pair a satellite

The bridge workspace and its management APIs require a Home Assistant
administrator. Pairing codes expire after 10 minutes or five different incorrect
guesses. Automatic reconnects with the same incorrect code count once instead
of repeatedly adding HA login failures. A successful connection resets HA's
failed-login counter. If a code is invalidated, select **Add Satellite** to
generate a new one.

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

## Bluetooth through a satellite

Updated Native ESP32, Echo, ThirdReality, and supported Linux satellites can
provide Bluetooth discovery and active GATT over their existing authenticated
WebSocket. Bluetooth stays off when unused; there is no automatic room presence
scan. Install the matching updated firmware (including ThirdReality's system
image for its BlueZ dependencies) to enable the on-demand controls.

Open **Tater Satellites -> Bluetooth**, then choose **Scan for devices**. Opening
the page does not scan. Discovery runs for 15 seconds, pauses for voice activity,
and stops automatically. **Stop scan** leaves existing connections intact.
For a PIN-protected peripheral, choose the satellite that will hold the bond,
enter its six-digit PIN, and select **Pair**. The PIN is used only for that
attempt and is not saved. Home Assistant uses the bonded satellite as the
device's connectable path. **Unpair** removes that satellite's bond; saved bonds
are otherwise preserved across updates.

An active device connection keeps Bluetooth enabled; after the final link and
discovery end, it powers down following a short idle delay. A saved bond alone
does not enable it. This mode does not continuously monitor broadcast-only
Bluetooth sensors or provide Bluetooth speaker audio.

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

## Speaker equalizer and bass protection

Open an Echo satellite's settings in **Tater Satellites** to tune its speaker
under **Speaker Equalizer**: an eight-band equalizer (125 Hz low shelf to 8 kHz
high shelf, ±12 dB), a presence boost, bass protection, and a peak limiter.
Bass protection compresses bass below about 115 Hz. Its **Bass protection
floor** is the most it may cut: -30 dB on the small Echo Dot, Show 5, and Spot
speakers, and -10 dB on the larger Echo 2nd generation (Radar) and Echo Show 8
(Crown and Athena) speakers, where -30 dB makes music sound thin. Raise the
floor toward 0 dB to keep more bass, and listen for distortion at high volume.

The controls are exposed per satellite and only when Echo firmware advertises
the `output_chain` capability. A value set on a satellite always replaces the
board default.

## Do Not Disturb

Open an Echo satellite's settings in **Tater Satellites** to use **Do Not
Disturb**. It silences music, announcements, wake sounds, and other
non-critical playback on that satellite. Timers and alarms remain audible, and
the microphone stays available so DND can be turned off by voice. The firmware
enforces it, so other sources on the network cannot bypass it.

Turn it on now, or set a daily window with start and end times. The two are
additive, overnight windows are supported, and matching times mean all day.
Each satellite also gets a **Do Not Disturb** switch, a schedule switch, start
and end time entities, and a **Do Not Disturb active** sensor for automations.

The window follows Home Assistant's time zone, including daylight-saving
changes. The controls appear only when Echo firmware advertises
`do_not_disturb` (Tater Echo firmware 4.0.0 and later).

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
supports schema-v1 through schema-v4 bundles, including V9 catalog bundles that
can contain MWW, OWW, NWW CNN, NWW GRU, and the detector-independent wake-end
model together. The bridge validates the selected engines and every schema-v4
boundary artifact field, reads the trainer-tested threshold/window/patience
values, and sends only the models each satellite can run. Schema-v4 bundle
revisions cover the complete package so boundary-only retraining refreshes the
cached Echo package even when the detector weights have not changed.

Model-specific override cards appear for the engines active in the selected
policy. With an override disabled, the trainer bundle values remain in effect.
For schema-v4 bundles, the same section shows the included boundary model,
threshold, and size as read-only information. Wake sensitivity and
environment—including **TV Nearby**—remain per-satellite room settings.

## Choose a catalog microWakeWord

While using MWW, set **Wake word** to **Tater Wake Word Catalog** and choose any
versioned model. Companion modes offer only compatible bundles: OWW starts at
V7, NWW starts at V8, and V9 adds the schema-v4 wake boundary. Home Assistant
validates that the selected package belongs to the official catalog before
sending it to satellites.

The catalog is fetched asynchronously and cached for ten minutes. If a refresh
temporarily fails, the bridge keeps the last successfully loaded list. You can
still use **Hey Tater**, upload a model, or enter a custom model URL separately.

## Link the Wake Word Trainer

Audio capture uploads do not require trainer pairing. Enable wake/close-miss
capture and enter a trainer address reachable from the satellite. The satellite
sends audio directly to that address after the voice turn and playback finish.
The **Audio delivery** cards show the satellite's latest upload report, including
queued uploads and errors. Reports are unavailable until supported firmware
sends them; offline cards retain the last report. Counters reset on restart.

The Apple Silicon and NVIDIA microWakeWord trainers can securely publish a newly
trained wake word directly to every Home Assistant-connected Tater satellite:

1. Open **Tater Satellites -> Wake Word Trainer**.
2. In the separate **Auto-training link** section, select
   **Link for auto-training** to generate a temporary code.
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
  empty transcripts, provider errors, and missing STT configuration fail open so
  transient service problems do not disable the satellite. An unknown custom
  wake phrase is blocked until it can be verified.

**Verification audio window** selects 500–2000 ms of buffered audio leading up
to wake detection. The default stays at 1000 ms. Try 2000 ms if an STT provider
returns empty text for short clips. This uses audio already in the satellite's
buffer; it does not wait for more audio to be recorded. Longer clips may take
more time to upload or transcribe.

**Wait for wake check** separately adjusts the live satellite timeout from 500 to
2000 ms. Try 1000 ms if short waits expire while the audio clip or result is
still in transit. Apply the setting to send it to connected satellites; no
firmware installation is needed. Replies are acted on immediately, without
waiting for the slider's full duration. The bridge reserves part of that wait
for audio upload and result delivery rather than using it all for STT.

The page separates the **STT match/mismatch** from the **last satellite report**.
For example, STT can report a mismatch after a satellite has already timed out
and allowed listening. Device reports update with periodic status and may lag
behind the STT decision. STT totals count server decisions, including unavailable
checks separately from matches, and reset when the bridge reloads.

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

## Wake arbitration

Open **Voice & wake → Wake arbitration** to choose one satellite when several
hear the same wake word. It works before STT in both HA and Mini-Tater modes,
buffers command audio during selection, and quietly ends the other captures.
No satellite firmware update is required.

| Setting | Default | Purpose |
| --- | --- | --- |
| Choose one satellite per wake | Enabled | Turn bridge arbitration on or off. |
| Compare satellites | Same room | Use the room saved on each satellite, or compare across the whole home. Satellites without a room are grouped together. |
| Choose the winner | Strongest command audio | Compare buffered PCM audio strength, or prefer the first wake received. Microphone gain affects audio strength; missing audio falls back to the first wake. |
| Selection window | 900 ms | Collect candidates for 100–3000 ms before starting STT. Longer windows add response latency. |
| Late-wake protection | 1500 ms | Keep other satellites quiet for 0–5000 ms after the reply finishes. The winner can wake again immediately. |
| Busy safety timeout | 120 seconds | Release a stuck turn after 5–300 seconds. |

The winner remains protected during listening, processing, and response playback.
Button starts and continued conversations skip the comparison. Saved changes
apply to new wakes, and the page shows the last 30 decisions since bridge startup.

HA mode also retains Home Assistant's own global cooldown for the same wake
phrase. Room-scoped bridge arbitration does not bypass that cooldown.

## Voice timers

Tater satellites use Home Assistant's built-in timer intents, including starting
multiple named timers, checking timer status, cancelling one or all timers,
pausing or resuming, and increasing or decreasing a timer. No custom sentences
or intent scripts are required.

Home Assistant recognizes the request and keeps a transient intent-side mirror.
The satellite owns the actual countdown and alarm, so it continues through a
temporary Home Assistant or network disconnect and rings locally. The timer is
intentionally lost if the satellite reboots or loses power.

## USB Ethernet and PoE

Native firmware 0.7.0 includes USB Ethernet for SAT1, Voice PE, ReSpeaker
XVF3800, and ESP32-S3-BOX-3. Use the powered
[UCTRONICS B0B9ZLVGJ4 (U6113)](https://www.amazon.com/dp/B0B9ZLVGJ4) with a
**data-capable Micro-USB female → USB-C male converter**, connected to the
ESP32 USB port. On ReSpeaker, use the XIAO port; a separate XMOS audio port
is not the ESP32 network connection.

Cold boot the satellite through the powered adapter. Ethernet is preferred
after DHCP succeeds, with saved Wi-Fi available as fallback. To restore the
native USB console, connect directly to a computer and reset/cold boot. No
pairing or voice protocol change is required.

Open a satellite's overview or **Diagnostics** for its active connection and
connection IP. Diagnostics also show reported Ethernet/Wi-Fi IPs, Ethernet link,
and adapter state. The connection IP comes from the current Home Assistant
socket; during a handoff it can briefly differ from a newly reported interface
address. The panel refreshes every five seconds when visible and no input is
active. Older firmware may not report every field. Echo Wi-Fi rescue and wired
recovery remain distinct states. Offline devices do not retain live link or IP
indicators from their last connection.

For adapter alternatives, 5 V power limits, Echo power differences, and recovery,
see [USB Ethernet and PoE in the README](../README.md#usb-ethernet-and-poe).

## Firmware updates and recovery

The **Firmware & Recovery** tab reads the latest official Tater Native, Tater
Echo, and Tater ThirdReality release manifests and matches images by the
firmware target reported by each satellite. Home Assistant downloads the
requested image, verifies its published size and SHA-256 hash, and exposes it
through a short-lived local URL. Echo Dot 2 (`biscuit`), Echo 2 (`radar`), Echo
Show 5 first generation (`checkers`), Show 5 second generation (`cronos`), Echo Show 8 first generation (`crown`),
Echo Show 8 second generation (`athena`), Echo Spot first generation (`rook`),
and ThirdReality Voice & Music Assistant (`thirdreality_s420`) receive the same
update entity, availability check, progress, reboot verification, and OTA flow
as the other satellites.

The new Echo hardware platform requires a **one-time full USB factory upgrade**
from v4.2.3, even on satellites that previously supported OTA. The integration
shows a USB-required explanation and disables OTA until the installed platform
matches. The new app, bridge and system packages use a format that v4.2.3
firmware itself rejects, so updating the host first is not required for safety.
Use the matching Echo factory installer, keeping its default preserve-settings
behavior; a rootfs-only `--repair` is not a kernel/platform upgrade. After USB
migration, normal compatible OTA resumes. When Linux itself needs updating,
the bridge stages the system, verifies its version after reboot, then sends
the final app update. A rolled-back system does not advance to the final app.

- Use **Install update** for a connected satellite. The integration sends the
  board-matched OTA image and tracks progress through the satellite entity.
- Use **Browser USB Flasher** for a first flash, recovery, or a wired update.
  Select the hardware and use Chrome or Edge from your normal Home Assistant
  page—there is no separate HTTPS requirement in the integration.

Echo factory installation is intentionally not offered through ESP Web Tools.
Use the model-specific factory archive and installer published by Tater Echo
Firmware. After installing the matching hardware platform, compatible updates
are wireless from Home Assistant on all Echo targets.
When a compatible screen build needs the newer component-aware updater, Home
Assistant installs the published compatibility bridge, verifies its capability
after reboot, and then sends the final release automatically. A compatibility
bridge never bypasses the one-time USB platform requirement.

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
