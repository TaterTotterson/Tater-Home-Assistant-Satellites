# Changelog

## 1.4.28

- Show the first design's chat and accurate AI progress while the model runs,
  instead of leaving Studio on an "Opening Studio" spinner.
- Bound Studio reads and requests so a stalled connection releases the controls
  and offers Reload Studio. Wait for the HA frontend connection before loading
  and refresh bridge/Studio data after it reconnects. Limit the optional wake
  catalog's delay during initial panel loading.
- Repair clear missing card types, including nested cards and bare entity IDs,
  without rewriting entity rows or guessing ambiguous card layouts. Give the
  model explicit card-type feedback when automatic repair is not possible.

## 1.4.27

- Fix Dashboard Studio stopping with "Sections view needs sections" for generated
  layouts. Describe views, sections, and cards explicitly in the model output
  schema and prompt instead of accepting an unspecified view object.
- Repair unambiguous card-nesting mistakes without dropping cards or view options.
  Give incomplete designs up to two repair passes with the previous response,
  concrete layout examples, and validation feedback. Keep validation checks and
  the existing overall request timeout.

## 1.4.26

- Add Dashboard Studio, a workspace at the bottom of Your home in both assistant
  modes, with a separate design chat, guided starting points, saved drafts, and
  phone/tablet/desktop previews.
- Design native HA dashboards from the home's real areas and entities through
  a dedicated OpenAI-compatible connection with its own settings workspace
  inside Studio. Preserve the design and chat when visiting settings. Support
  hosted APIs or local models, preserve saved API keys, and keep credentials
  server-side. Validate proposals and retry invalid designs.
- Create and update UI-managed dashboards through HA's registered APIs with
  backups, draft undo, applied-change undo, and checks for newer edits.
- Keep Studio conversations separate from voice/Hydra conversations, retain
  designs across assistant mode changes, and preserve the bridge's existing theme.
- Refresh the panel and Studio module together when either asset changes.

## 1.4.25

- Add Mini-Tater's natural-language Web search tool to the Hydra catalog and
  Home tools workspace. Search DuckDuckGo first and automatically fall back to
  Bing, without an API key, account, or provider settings.
- Ground web answers in returned search snippets and save verified source links
  with chat messages. Show clickable sources separately from the spoken reply.
- Run searches outside Home Assistant's event loop, bound their duration and
  result size, and cache repeated queries for two minutes. Clearly report
  unavailable, rate-limited, empty, and timed-out searches.
- Give Scheduled actions its own Home tools card with examples, listing and
  cancellation guidance, and scheduling limits. Move scheduling details out of
  the date-and-time card.
- Add SAT1 Raspberry Pi satellite and embedded Tater image links to the README,
  and update the user guide for Mini-Tater's nine built-in tools.

## 1.4.24

- Add wake arbitration before both HA and Mini-Tater voice pipelines so one
  satellite handles a shared wake. Compare command audio or select the first
  wake, using the firmware room or the whole home as the scope.
- Add a Wake arbitration workspace with a selection window, late-wake
  protection, busy safety timeout, and recent decisions. Buffer command audio
  during selection and protect the winner through reply playback. Settings
  apply to new wakes without a firmware update.

## 1.4.23

- Add PoE support information for SAT1, Voice PE, ReSpeaker XVF3800, and
  ESP32-S3-BOX-3 with Native Firmware 0.7.0.
- Show the active network, IP addresses, Ethernet link, and adapter status.
- Keep connection details current through network changes and disconnects.

## 1.4.22

- Add a Doorbell workspace in HA and Mini-Tater modes with independent press
  trigger, camera, editable greeting instructions, and audio-capable HA media
  player selections. Reuse shared Vision and the active mode's speech provider.
- Optionally open the live camera immediately on compatible Show and Rook
  satellites. Keep screen delivery independent of Vision/TTS, bound the display
  duration, and preserve manual camera navigation and dismissal.
- Add cooldowns, test controls, saved doorbells, and the last 50 activity results
  with separate speaker and screen errors. Camera-only doorbells require no
  Vision or TTS provider. Automatic camera opening requires updated Echo firmware
  advertising the camera popup capability (Echo 5.0.4 or newer).

## 1.4.21

- Preserve the first words spoken immediately after the wake word in Mini-Tater
  mode. Forward post-boundary audio to STT while neural VAD initializes, following
  HA's Assist stream, instead of dropping audio from a short speech-start buffer.
- Close no-speech captures cleanly so STT can finish short commands that VAD did
  not classify, while retaining capture limits and empty-transcript rejection.

## 1.4.20

- Fix Mini-Tater continued conversation by checking whether the final reply
  asks for an answer, following Tater's bounded follow-up classifier. Respect
  each satellite's Continued conversation and microphone-mute settings, preserve
  the conversation ID, and reopen only after successful firmware playback. Keep
  HA mode using the selected conversation agent's continuation flag.
- Give every Mini-Tater Hydra model request the current Home Assistant date,
  time, and timezone, following Tater's live-clock prompt.
- Add natural-language shopping/to-do list, HA weather and forecast, broadcast,
  music search/playback, and delayed device-action tools using the existing
  three-head Hydra flow and Shop Verbas as references. Keep tool descriptions
  in Astraeus's catalog and pass each locked NL query unchanged to Thanatos's
  selected tool.
- Use existing HA lists, weather integrations, Music Assistant or searchable
  media players, and announcement satellites. Recheck the selected Assist scope
  before changes and report unavailable targets and partial failures.
- Save delayed actions with fixed targets across restarts, support listing and
  cancellation, and avoid replaying actions missed by more than a minute or
  retrying interrupted actions with unknown outcomes.
- Extend device control to floors, thermostat fan modes, mower start/dock,
  relative volume/mute, and compatible vacuum area cleaning.
- Add confirmed timer pause/resume and time adjustments using existing satellite
  commands. Store paused remaining time in HA; running timers remain local to
  satellites. Update Home tools in the existing workspace style and document
  provider requirements. Home Assistant mode remains the default pipeline.
- Move Home Assistant device control to the bottom of Home tools with its
  Available now entity list directly underneath. Preserve scope selection and
  save controls.
- Simplify the README setup steps and move detailed feature instructions into
  the linked user guide.

## 1.4.19

- Add explicit 15-second Bluetooth discovery and Stop controls. Reading the panel
  or status does not start a scan; discovery expires and pauses for voice activity.
- Support the shared on-demand GATT proxy on updated Native ESP32, Echo,
  ThirdReality, and Linux satellites. Retain active links when discovery stops
  and power Bluetooth down when unused.
- Accept BlueZ name, service UUID, manufacturer, and service-data advertisements.
  Reject unsolicited batches outside a requested discovery window.
- Preserve existing bonds and connections held by another consumer during PIN
  pairing. Validate six ASCII digits without silently rewriting the PIN.
- Add Bluetooth lifecycle, capability, failure, and bond-ownership regressions.

## 1.4.18

- Save satellite names and rooms live from the bridge or Home Assistant's
  device editor, with persistent firmware confirmation and rollback after
  rejected writes. Support HA area renames and clearing a room assignment.
- Preserve device identity, pairing, existing entity IDs, and stereo membership.
  Refresh registry names after another controller edits the satellite; require
  supported firmware and an online connection before saving changes.
- Give newly created entities explicit default IDs without a duplicated HA area
  prefix; keep all existing entity IDs unchanged.

## 1.4.17

- Add HACS and hassfest validation on pushes, pull requests, a daily schedule,
  and manual runs, with all validation checks enabled.
- Declare UI-only configuration using Home Assistant's config-entry schema,
  resolving the hassfest configuration warning.
- Add the voice-assistant Marketplace category and the official Marketplace
  installation button. Document Marketplace installation and updates for Home
  Assistant 2026.11 and newer while retaining HACS instructions for older versions.

## 1.4.16

- Add Flat, Warm, Voice, and Manual sound presets to each satellite's Speaker
  Equalizer and a capability-gated Home Assistant Sound preset select entity.
- Default to Warm only when no EQ has been saved. Preserve existing curves,
  including flat curves and partial legacy overrides, as Manual.
- Apply all eight bands and disable Presence boost when selecting a named preset;
  switch to Manual when a band or Presence boost is edited. Preserve unsaved EQ
  edits during panel refresh and keep bass protection and limiter settings intact.
- With Echo firmware 5.0.1, save accepted device EQ changes and adopt restored
  device EQ before the first settings push when HA has no saved EQ override.
  Validate reports and preserve existing bridge overrides on reconnect.
- Keep older output-chain firmware compatible by sending the expanded curve and
  only including preset metadata when the device advertises support.

## 1.4.15

- Separate **Send audio to trainer** from the optional **Auto-training link**.
  Put the upload URL and capture controls first, and clarify that linking is
  only needed to publish trained model updates, not to send satellite audio.
- Add a separate 500–2000 ms verification audio window slider to STT Wake Check,
  keeping the existing 1000 ms default. Save and push the buffered clip length
  through the existing firmware setting, independently of the response wait.
  Keep empty STT results, provider errors, and timeouts allowing listening.
- Show each satellite's trainer audio delivery reports: pending/running uploads,
  delivered clips, failures, deferred attempts, skipped clips, last error, and
  available internal memory. Clarify that satellites upload directly to the
  configured trainer and that pairing is only needed for model publishing.
- Keep physical satellite volume changes in sync with the bridge panel and HA
  volume control while full settings confirmation is pending. Save the new
  per-satellite volume so reconnects and later settings pushes preserve it;
  ignore stale unconfirmed status, failed reports, and invalid values.
- Add a 500–2000 ms wake-check wait slider using the satellite's existing live
  timeout setting. Validate and save it through the dedicated STT Wake Check
  form, preserve drafts during refresh, and show the selected time in milliseconds.
- Reserve time for the wake clip upload and result delivery so STT does not use
  the satellite's entire response window. Keep immediate results and the existing
  fallback that allows listening when STT is unavailable or times out.
- Separate STT mismatches from the satellite's last reported outcome, including
  timeouts that allowed listening. Report server totals independently from device
  counters and exclude unavailable checks from successful STT matches.
- Correct the Identify confirmation to describe spoken message playback.

## 1.4.14

- Add the Awareness workspace in both Home Assistant and Mini-Tater mode. Create
  monitors by choosing a camera, a binary sensor/event/toggle trigger, and Echo
  screen or HA Companion phone notification destinations. Suggest trigger
  entities belonging to the camera's HA device.
- Capture a fresh image at trigger time, obtain a short Vision description, and
  deliver that same image and description to each selected destination. Use the
  paired satellite connection for screen alerts and authenticated HA local media
  for phone images, loading `media_source` automatically.
- Move the existing Vision model settings into a shared workspace available in
  either mode. Preserve Base/dedicated endpoint settings and saved credentials.
  HA-mode Awareness does not require Mini-Tater language or speech setup and
  does not run a Hydra conversation turn.
- Add monitor enable/pause controls, a default 60-second cooldown, optional
  description instructions, and real test alerts. Keep the last 50 runs with
  per-destination delivery status and errors. Retain snapshots for up to one
  hour and remove images pruned from recent history.
- Bound pending work and simultaneous Vision calls, coalesce repeated busy
  triggers, and time out failed providers or destinations independently. Ignore
  startup/restored sensor states while recognizing repeated doorbell events.
  Cancel pending work when a monitor is edited, paused, deleted, or unloaded.
- Match the bridge's dark/light workspace theme and responsive layout. Preserve
  monitor and Vision drafts during navigation and refresh, and save shared
  Vision independently from other assistant settings.

## 1.4.13

- Correct the room precedence introduced in 1.4.12. The firmware-configured room
  is authoritative for bridge features and every Mini-Tater Hydra head; a Home
  Assistant area assignment cannot override it.
- Match the satellite's HA area to its firmware room on startup, pairing,
  reconnects, and area edits or renames. Reuse the matching area or create it when
  absent, and repair existing HA overrides without changing firmware settings or
  moving unrelated devices.
- Treat an explicitly empty firmware room as unassigned. Missing room metadata
  preserves the last firmware-reported room; neither case adopts an HA override.
- Preserve the offline device cleanup from PR #23 and Mini-Tater's room-aware
  planning, tool execution, and responses from PR #26.

## 1.4.12

- Remove the matching Home Assistant device and its entities when an offline
  satellite is forgotten. Allow deletion of offline or orphaned satellite devices
  from Home Assistant while protecting connected satellites, saved stereo pairs,
  and unrelated devices. ([#23](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/23))
- Use the satellite's assigned Home Assistant area as its effective room, with
  firmware-room fallback. Refresh room context after area changes or renames,
  preserve manual area assignments on ordinary reconnects, and follow changed
  firmware rooms. ([#26](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/26))
- Give Mini-Tater's Hydra heads the asking satellite's name and resolved room so
  requests such as "turn on the lights" can use the current room, while explicit
  room and device names remain authoritative. Include this context in plan checks,
  retries, and the Hydra ledger without assuming a room for management chat.
- Keep compatibility with Home Assistant 2026.6 and newer. No satellite firmware
  update is required; restart Home Assistant after updating the integration.
- Contributor: [Andrew Loe (@loe)](https://github.com/loe), device cleanup and
  room/area synchronization in PRs #23 and #26.

## 1.4.11

- Fix silent Identify buttons in the bridge panel and Home Assistant device
  controls. Identify now speaks a short message instead of sending an unsupported
  tone-synthesis request without an audio URL.
- Use the satellite's selected Assist pipeline TTS voice in Home Assistant mode,
  or the configured Mini-Tater TTS provider and voice in Mini-Tater mode.
- Wait for normal announcement playback and surface synthesis, connection and
  playback failures rather than reporting a silent success. No satellite firmware
  update is required for this fix.

## 1.4.10

- Block the Echo hardware-platform OTA until its one-time full USB upgrade is
  complete, with a keep-settings explanation in the panel and update entity.
  Check platform eligibility before compatibility bridges; support verified
  system-first/app-second OTA after migration, and refuse continuing if Linux
  rolls back or reconnects on the wrong system version. Native ESP updates are
  unchanged.
- Match Tater's qualified hardware Sat Chat negotiation for Checkers, Cronos,
  Crown, Athena and Rook. Athena/Rook require their balanced-only capability;
  older/mixed peers retain JPEG. Preserve H.264 GOP order/keyframe recovery,
  use bounded audio-priority media queues and avoid blocking the source's
  receive loop under peer backpressure. Hardware video requires matching
  capability-advertising firmware; legacy pairs retain JPEG compatibility.

- Added Timer (`voicepe_remote_timer`) as Mini-Tater's third built-in tool with
  the exact Timer Verba description and natural-language-only `query` contract.
  It supports named timers, spoken durations, remaining-time checks, cancel,
  silence, and snooze through live satellite commands. Satellites keep owning
  countdowns and alarms while disconnected, with no bridge timer database.
- Added per-satellite **Conversation text** in Display & Night: Smooth (default)
  or Matrix symbol cycling with shuffled letter reveals on updated Echo GPU UIs.
  Unsupported firmware does not receive the setting. Local touchscreen changes
  are saved to the same satellite's override, without affecting voice defaults.
- Recognize Cronos as an Echo display when offering per-satellite screen settings.

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
