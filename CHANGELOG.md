# Changelog

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
