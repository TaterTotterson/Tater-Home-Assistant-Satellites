# Changelog

## Unreleased

## 1.4.9

- Added `tater_vision` as Mini-Tater's second built-in Hydra tool, mirroring the
  Tater Shop Verba for fresh Home Assistant camera and camera-capable satellite
  stills, named room/camera and outdoor-area targeting, and asking-room fallback.
  It uses the existing **Same as Base** or dedicated Vision route and never stores
  raw camera images. The management chat also accepts bounded image attachments,
  sends them through image understanding before Hydra planning, and stores only
  attachment metadata rather than raw image data.
- Aligned Mini-Tater with Tater's natural-language-first Hydra contract:
  Astraeus now receives a stable two-tool capability catalog and produces atomic
  `intent`, `nl`, and `tool_hint` steps; Thanatos calls the selected built-in
  tool with the locked natural-language query; and the Home Assistant runtime owns
  action, value, room, alias, capability, and service resolution with bounded
  model fallback for unclear language or ambiguous device names.
- Added one bounded Thanatos repair attempt for malformed or broadened native
  tool calls, plus Tater-style native structured planning with a cached JSON
  fallback for providers that do not support it, while retaining Home Assistant
  entity-scope and service checks.
- Preserved follow-up context without presenting Hermes prose as prior
  Astraeus output, and added Enter-to-send in the management chat.

## 1.4.8

- Upgraded Mini-Tater to an Astraeus, Thanatos, and Hermes Hydra flow: requests
  are planned into bounded atomic steps, every locked Home Assistant action is
  executed separately, and the final spoken reply is composed from verified
  results.
- Added Beast Mode with Base or dedicated OpenAI-compatible model settings for
  each Hydra head.
- Improved compound device targeting so one request can safely control several
  devices with the same or different commands without broadening an atomic
  step to another requested target.

## 1.4.7

- Renamed the embedded pipeline to Mini-Tater, clarified that it is a
  streamlined Tater for Home Assistant, and hid its text-test chat while the
  Home Assistant pipeline is selected.
- Enriched successful `control_home` results with verified friendly names,
  rooms, action values, counts, and partial failures so Mini-Tater can produce
  specific confirmations instead of generic completion messages.
- Aligned final device-action guidance with Tater's response style: lead with
  the outcome, follow the configured personality, keep spoken replies brief,
  and avoid entity IDs, internal execution details, and repetitive filler.

## 1.4.6

- Aligned mini-Tater Home Assistant device targeting with the Tater Shop
  `device_control` Verba: category words now constrain candidates before room
  or device-name matching, and the original request remains authoritative when
  a model proposes an entity from the wrong domain.
- Added Home Assistant supported-feature checks for media-player commands and
  isolated service failures per entity so an unsupported action becomes a tool
  result instead of terminating the voice pipeline.

## 1.4.5

- Kept Home Assistant as the default conversation pipeline and hid the
  Tater-only Models & speech, Home control, and Hydra pages until Tater mode is
  explicitly selected.
- Split Wyoming's optional STT model and TTS voice names from the OpenAI fields
  so they remain blank by default and no provider-specific name is sent unless
  the user enters one. Existing custom Wyoming names are migrated.

## 1.4.4

- Restored Tater-mode turns on Home Assistant versions whose exposed-entity
  registry provides `async_should_expose` instead of
  `async_get_should_expose`, while retaining compatibility with both APIs.

## 1.4.3

- Removed the external WebRTC dependency that prevented the integration from
  loading on Home Assistant hosts without a compatible wheel.
- Standardized mini-Tater endpointing on Home Assistant's built-in Neural Micro
  VAD with default endpoint timing and removed Tater-mode VAD controls from the
  panel.

## 1.4.2

- Added server-side voice activity detection to mini-Tater mode so native
  satellites receive the end-of-speech event, close their microphone stream,
  and continue from Listening to transcription.
- Added selectable Neural Micro VAD and lightweight WebRTC models under Models
  & speech. Both use Tater-style speech start, no-speech, and maximum-listen
  limits, while the existing per-satellite VAD sensitivity controls how quickly
  trailing silence ends a Tater turn.

## 1.4.1

- Kept the bridge panel's five-second live refresh from returning the page to
  the top or collapsing expanded diagnostics. Scroll position and local view
  state now survive automatic status updates.

## 1.4.0

- Reworked the satellite panel into a Tater Bridge workspace, with grouped
  navigation, a searchable satellite list, focused device settings, and matching
  pairing, wake-word, sound, and confirmation panels in light and dark themes.
- Retained all schema-driven settings, hardware capability checks, device
  commands, and save endpoints. Unsaved device and shared-setting drafts now
  survive navigation, polling, unrelated commands, and saves in other sections.
- Refreshed the panel's module and custom-element identity when its source changes
  so updated installations do not reuse an older UI in an open browser.
- Added a complete mini-Tater voice mode alongside the unchanged Home Assistant
  Assist mode. Tater mode owns STT, Hydra, Home Assistant device control, TTS,
  conversation history, and satellite playback.
- Added matching Assistant, Models & speech, Home control, and Hydra workspaces.
  Providers support OpenAI-compatible APIs or Wyoming speech services, while the
  Hydra ledger records plan review, tool results, final responses, and timing.
- Limited mini Tater to one allowlisted `control_home` tool, with an exposed-to-
  Assist or all-entities scope that is rechecked before device actions. Provider
  secrets are omitted from every management snapshot.

- Added negotiated H.264 Sat Chat profiles for qualified Checkers and Cronos
  peers, including 720p/960p and balanced 768×432/640×480 modes. Encoded packets
  are relayed without JPEG transcoding, with bounded GOP-aware queues.
- Kept mixed and older devices on their existing video profiles, validated
  negotiated frame geometry, and prevented late, reserved, or malformed video
  packets from entering Assist audio.

## 1.3.4

- Added an adjustable STT wake-verification match threshold to the STT Wake
  Check tab. The global control ranges from 50% to 100% in one-percent steps,
  keeps the existing 85% default, and includes a one-click reset.
- Clarified that this threshold tunes only the secondary STT confirmation; the
  satellite's on-device wake model remains the first wake gate.
- Updated per-satellite results to show the latest transcript match beside the
  threshold required for that decision, making Observe mode easier to tune for
  benign substitutions such as “Juniper” being transcribed as “Jennifer.”
- Saved and pushed threshold changes through the dedicated verifier endpoint,
  with validation that preserves compatibility with existing firmware.

## 1.3.3

- Added boundary-aware wake-bundle delivery for Tater Native ESP32 satellites.
  Satellites advertising wake-boundary support now receive the complete,
  verified schema-v4 bundle through the bridge instead of only its ESPHome MWW
  manifest.
- Kept older native firmware fully compatible by continuing to project and
  deliver the MWW-only manifest when wake-boundary support is not advertised.
- Removed Echo-only bundle fields before native delivery while retaining the
  boundary model, runtime contract, calibration, and integrity metadata needed
  by compatible native firmware.

## 1.3.2

- Added schema-v4 wake-bundle support for custom and V9 catalog wake words.
  The bridge validates the hash, size, runtime contract, search window, and
  calibration threshold of the detector-independent wake-boundary model before
  a package can be selected.
- Switched schema-v4 MWW, OWW, and NWW cache revisions to the complete bundle
  hash. Retraining only the boundary model now refreshes the matched Echo
  package even when all detector weights remain unchanged.
- Updated linked Wake Word Trainer publishing to accept the canonical bundle,
  route its adjacent ESPHome manifest to MWW-only satellites, and retain the
  same bundle for Echo companion and boundary installation.
- Added read-only schema, threshold, size, and availability details for the
  boundary model in the shared wake-word UI, plus V9 catalog coverage.
- Preserved schema-v1 through schema-v3 bundle compatibility. Schema-v4 wake
  boundaries require Tater Echo Firmware 4.2.0 or newer.

## 1.3.1

- Added live Assist conversation text to compatible Tater Echo screens. The
  bridge now shows the listening screen, Home Assistant's final STT transcript,
  the thinking state, and the assistant's final reply using the firmware's
  ordered `display.conversation` protocol.
- Kept the existing `voice.event` state and audio flow unchanged. Home
  Assistant currently exposes final STT text to the satellite entity, so the
  completed user sentence appears at `STT_END` without claiming unsupported
  word-by-word transcript streaming.

## 1.3.0

- Added per-satellite Speaker Equalizer settings for Echo satellites: eight
  EQ bands, presence boost, bass protection with an adjustable floor, and the
  peak limiter. They appear only when firmware advertises `output_chain`.
- Defaulted the bass protection floor to -10 dB on the larger Echo speakers
  (Radar, Crown, and Athena) instead of the firmware's -30 dB, which suits the
  small Dot, Show 5, and Spot drivers. Values set on a satellite still win.
- Added per-satellite Do Not Disturb for Echo satellites, matching Tater: a
  manual control and a daily window, enforced by the firmware. It appears in
  the panel and as switch, time, and binary sensor entities only when firmware
  advertises `do_not_disturb`, and the window follows Home Assistant's time
  zone across daylight-saving changes.
- Kept daylight-saving offset changes eligible for retry when a settings send
  fails, preventing a satellite from retaining a stale DND schedule offset.

### Contributor

Contributions from [Martin Tremblay](https://github.com/MartyTremblay) included
in this release:

- [#15 — Add Speaker Equalizer settings for Echo satellites](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/15)
- [#16 — Add Do Not Disturb for Echo satellites](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/16)

## 1.2.1

- Improved Echo screen cameras by preferring a camera's continuous Home
  Assistant stream and converting it to a bounded three-frame-per-second MJPEG
  relay over the existing authenticated `TCAM1` connection.
- Kept the 1 FPS Home Assistant snapshot path as an automatic fallback for
  snapshot-only, WebRTC-only, unavailable, or stalled camera streams.
- Added latest-frame-only buffering so a slow satellite drops stale video
  frames instead of accumulating latency, while retaining the existing
  15-minute limit and close/disconnect cleanup.

## 1.2.0

- Added a per-satellite Clock format setting (12-hour or 24-hour) for Echo
  screens: Checkers, Crown, Athena, and Rook. It appears under Display & Night
  and as a select entity only when firmware advertises `screen_clock_format`;
  older firmware never receives the new setting.
- Fixed Echo screen clocks showing UTC by sending Home Assistant's configured
  local time and current UTC offset on connection and every minute, including
  daylight-saving changes.
- Stopped high-frequency Bluetooth proxy advertisements from rewriting every
  satellite entity, and cached effective settings for each entity refresh to
  prevent Bluetooth traffic from pinning a Home Assistant CPU core.
- Enabled the Climate panel on compatible Echo screens with a per-satellite
  thermostat selector, live setpoint and HVAC-mode controls, and up to six
  selected room-temperature sensors.
- Enabled the Cameras panel on compatible Echo screens with Home Assistant's
  camera list and authenticated `TCAM1` JPEG snapshots, refreshed about once a
  second and automatically stopped on close, disconnect, or after 15 minutes.

### New contributor

- Welcome and thank you to [Martin Tremblay](https://github.com/MartyTremblay)
  for the Echo screen clock, local-time, Climate, and Cameras work, plus the
  Bluetooth proxy performance fix included in this release.

## 1.1.4

- Matched Tater's proven settings boundaries: wake models, STT Wake Check,
  trainer feedback, and Voice Defaults now use separate requests with explicit
  allowlists in both the panel and bridge.
- Limited official-catalog validation to explicit catalog selections so stale
  or unrelated draft fields cannot cause an HTTP 400 while saving another tab.
- Kept the legacy wake-family route compatible with older catalog-only clients
  without weakening validation on the current shared-wake API.

## 1.1.3

- Fixed HTTP 400 responses when saving Voice Defaults, including STT Wake
  Check, while using the built-in wake word or another non-catalog companion
  wake model.
- Kept panel-only companion catalog fields out of global settings requests and
  made the bridge safely discard empty legacy catalog fields without weakening
  validation for explicit catalog selections.

## 1.1.2

- Used the firmware's ordered wake pre-roll boundary to keep the local wake
  phrase out of Home Assistant command STT and VAD while forwarding immediate
  post-wake speech without an artificial delay.
- Preserved full-stream behavior for older firmware and added a bounded
  fail-open path when marker-aware firmware does not deliver its boundary.

## 1.1.1

- Preserved and logged detailed native playback failures reported by a
  satellite instead of reducing them to a silent success/failure boolean.
- Home Assistant's existing streaming WAV reply path now plays incrementally
  on Echo firmware advertising streaming voice playback version 1; older
  satellite behavior remains unchanged.

## 1.1.0

- Added the full Tater Echo firmware lineup to Home Assistant OTA discovery:
  Biscuit, Radar, Checkers, Crown, Athena, and Rook. Echo Show 8 2nd Generation
  devices now resolve to the Athena release and use the matching Sat Chat video
  profile.
- Added safe staged Echo updates. Older screen builds receive the signed OTA
  compatibility bridge first; Home Assistant verifies the new component-aware
  updater after reboot before sending the final release.
- Added per-satellite display controls for Checkers, Crown, Athena, and Rook:
  normal brightness, ambient-light automatic brightness with a minimum level,
  scheduled night brightness, and dim, red-clock, or screen-off night modes.
- Kept the established ESP32-S3-BOX-3 brightness and scheduled-dimming wire
  contract unchanged, and hide the new Echo controls unless firmware advertises
  screen power-management support.

## 1.0.0

- Added NanoWakeWord CNN and GRU support with MWW, OWW, NWW, MWW + OWW, and
  MWW + NWW wake policies. Satellites without the selected companion engine
  automatically keep the matching MWW fallback.
- Added canonical schema-v3 wake-bundle support while preserving schema-v1 and
  schema-v2 MWW/OWW packages. The bridge now applies each bundle's MWW, OWW,
  and NWW calibration values and validates the selected NWW architecture.
- Added model-specific shared tuning cards and kept room sensitivity and
  environment in the per-satellite settings. Stale per-device model overrides
  are removed during migration.
- Expanded the official catalog selector to use OWW bundles from V7 onward and
  NWW bundles from V8 onward.

## 0.9.2

- Added **OWW Where Supported** to the shared wake-detection setting. Capable
  satellites receive openWakeWord-only detection while ESP32 and other
  MWW-only satellites automatically receive the matching microWakeWord model.
- Custom OWW and Dual selections continue to use one validated wake bundle so
  every satellite listens for the same phrase.
- Simplified the settings labels: the wake engine now says **On-device wake
  detection**, and the built-in/custom selector is named **Wake word model**.

## 0.9.1

- Added direct Sat Chat audio and video calls between compatible satellites
  connected to Home Assistant, without routing live media through Assist.
- Relayed the Echo firmware's tagged JPEG video frames over the existing
  authenticated satellite WebSockets with a latest-frame-only queue so slow
  displays cannot build latency or delay call audio.
- Added live participant and busy-state directories, capability validation,
  call cleanup on disconnect, and transient call diagnostics. Call media and
  state remain in memory and are never persisted by the integration.

## 0.9.0

- Replaced separate ESP and Echo wake profiles with one shared wake-word setup.
  Choose microWakeWord or Dual Wake Word once; ESP firmware receives the MWW
  model, while capable Echo firmware receives the matching MWW+OWW pair.
- Existing standalone openWakeWord selections migrate to Dual mode, and custom
  MWW selections are preserved when upgrading from the former split profiles.
- Expanded music-reactive LED settings beyond Biscuit to Echo 2/Radar, Voice
  PE, Satellite1, and ReSpeaker XVF3800 satellites. The selected animation also
  follows Sendspin playback and can be disabled with **No Animation**.

## 0.8.0

- Added native Home Assistant Bluetooth proxy support through compatible Echo
  satellites running Tater Echo Firmware 2.4.0 or newer. Each connected Echo
  registers as a connectable scanner and forwards raw advertisements, GATT
  service discovery, reads, writes, and notifications over its existing secure
  satellite connection.
- Added a Bluetooth tab to Tater Satellites with live Echo capacity, nearby
  devices, six-digit PIN pairing, saved bond details, and unpair controls.
- Bluetooth PINs are used only for the pairing request and are never stored by
  Home Assistant. A paired device remains routed through the Echo that owns its
  encrypted bond.

## 0.7.2

- Added per-device Satellite1 audio output controls for automatic jack
  detection, the internal speaker, 3.5 mm AUX/line-out, or both outputs. The
  setting is available in the Tater Satellites panel and as a Home Assistant
  select entity.
- Simplified wake-word settings so ESP/MWW and Echo satellites each show one
  clear **Wake engine** selector with only the choices supported by that
  firmware family.
- Fixed live panel refreshes replacing an open dropdown or active settings
  control while it is being used.

## 0.7.1

- Added a **No Animation** choice for listening, thinking, tool-call, and
  replying LEDs.
- Added Biscuit music LED controls for Audio Glow, Beat Pulse, Level Bars,
  Reactive Orbit, Reactive Wave, or no animation. The setting is available in
  the Tater Satellites panel and as a Home Assistant select entity.
- Music-only LED settings are shown and sent only to supported Echo Dot 2
  (Biscuit) satellites.

## 0.7.0

- Added separate ESP/MWW and Echo wake profiles. Echo satellites can select
  microWakeWord, openWakeWord, or Dual Wake Word, including matched custom
  `.wake-bundle.json` packages produced by the Tater Wake Word Trainer.
- Echo live settings now follow Tater's atomic settings contract so both wake
  detectors and their matched package are applied together. Firmware settings
  failures are retained and shown instead of being silently discarded.
- Replaced the private `audio.clock.sync` and `media.session.*` music protocol
  with a Sendspin v1 source shared by single players, stereo pairs, and groups.
- Home Assistant now decodes each media URL once through its FFmpeg component
  and sends one timestamped PCM timeline to every selected satellite.
- Stereo pair left/right output modes are pushed as firmware settings; channel
  trim, placement delay, multi-room mono routing, seeking, and device volume
  controls remain available.
- Removed the signed shared-media spool and bridge-side playhead correction.
  Sendspin clients now own buffering, clock synchronization, and drift control.
- Normal Assist replies, announcements, and intercom overlays remain on their
  existing native playback paths.

## 0.6.3

- Stereo pairs and synchronized groups now fetch each media source once and
  share identical audio bytes through a signed, local bridge URL. This is
  especially useful for dynamic Music Assistant flow URLs.
- A seek reuses the pair's current shared stream. Completed streams remain
  available long enough for their expected track duration; stopped live
  streams are closed and their temporary files are cleaned up.
- A stereo member that rebuffered receives at most one bounded catch-up jump
  after its decoder recovers. No correction is sent while it is stalled.
- Single-satellite playback, channel assignments, and firmware protocols are
  unchanged.
