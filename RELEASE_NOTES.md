# Tater Satellite 1.4.10

- Add Mini-Tater's built-in Timer tool: create named timers, check remaining
  time, cancel, silence and snooze using natural language. Satellites keep
  owning countdowns and alerts, including while disconnected.
- Add per-satellite Smooth/Matrix conversation text styles for supported Echo
  GPU UIs, and recognize Cronos when offering Echo display settings.
- Negotiate balanced hardware H.264 Sat Chat between compatible Shows/Rook,
  preserving JPEG for older or mixed peers. Bounded audio-priority media queues
  keep slow destinations from blocking the source receive loop.
- Explain and enforce Echo 5's one-time full USB installation, including
  keep-settings guidance. An app-only update cannot replace the kernel/platform.
- After migration, perform verified system-first/application-second OTA when
  needed; refuse the final app if Linux rolls back or reconnects with the wrong
  system version. Native ESP firmware updates are unchanged.

Hardware-video availability depends on the satellites' advertised capabilities;
this bridge update does not install Echo firmware or enable unqualified hardware.

Restart Home Assistant after updating the integration.
