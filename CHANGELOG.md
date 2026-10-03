# Changelog

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
