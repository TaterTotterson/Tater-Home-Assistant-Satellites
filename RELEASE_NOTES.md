# Tater Satellite 1.4.14

- **Awareness in HA and Mini-Tater mode.** Choose a camera, a motion sensor,
  doorbell/event entity, or toggle trigger, and where to receive the alert. The
  bridge captures a fresh image, asks Vision for a short description, and sends
  that same image and description to the selected destinations.
- **Screen and phone notifications.** Compatible Echo screens receive alerts
  through their paired satellite connection. Home Assistant Companion phones
  receive image attachments through authenticated local media. Each destination
  has its own delivery result; an offline screen or failed phone does not block
  the others.
- **Shared Vision settings.** Vision now has its own workspace, visible in both
  modes. Keep using the Base model or a dedicated compatible endpoint with the
  existing settings and saved key. HA users can configure Vision without setting
  up Mini-Tater's language, STT, or TTS providers. Awareness calls Vision directly
  without running Hydra.
- **Simple monitor controls.** Enable or pause monitors, set a cooldown (60
  seconds by default), add optional description instructions, and send a real
  test alert. Related camera-device trigger entities are suggested first.
- **Recent activity and delivery details.** Inspect the last 50 runs, including
  tests, pictures, descriptions, and individual destination errors. Images expire
  after one hour or when their run leaves recent history. Raw images are kept
  out of conversation history and the Hydra ledger.
- **Bounded background work.** Limit pending monitors and concurrent Vision
  calls, coalesce repeated triggers while a monitor is busy, and apply provider
  and delivery timeouts. Ignore startup/restored sensor changes and recognize
  successive doorbell presses. Editing, pausing, or deleting a monitor cancels
  its pending alert.
- **Matching workspace styling.** Awareness and Vision follow the bridge's
  dark/light theme and phone layout. Unsaved drafts survive navigation and
  refresh; saving Vision does not overwrite unrelated assistant changes.

Update the integration through HACS and restart Home Assistant. Existing Vision
settings are retained. Compatible Echo screens use their existing notification
support; no new satellite firmware build is required for this release.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.13...v1.4.14)
