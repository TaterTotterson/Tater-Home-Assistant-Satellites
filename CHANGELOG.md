# Changelog

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
