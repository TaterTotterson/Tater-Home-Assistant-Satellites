# Tater Satellite 1.4.15

## What's changed

- **Adjustable STT wake-check timing.** Add separate sliders for the verification
  audio window (500–2000 ms, default 1000 ms) and the response wait (500–2000 ms,
  default 500 ms). Longer windows give STT more audio context; the wait controls
  how long the satellite allows for a decision. Both use milliseconds, preserve
  unsaved edits during refresh, and apply through existing live firmware settings.
- **Clearer wake-check results.** Separate the STT match or mismatch from the
  satellite's last reported outcome. Show when a timeout allowed listening rather
  than implying that a late STT rejection blocked the wake. Exclude unavailable
  checks from successful STT matches and reserve part of the response wait for
  audio upload and result delivery.
- **Physical volume sync.** Keep volume changes made on a satellite in sync with
  the bridge panel and Home Assistant volume control, including while full
  settings confirmation is pending. Save the per-device volume so later settings
  pushes and reconnects preserve it.
- **Separate audio uploads from auto-training.** Put **Send audio to trainer**
  and its URL first. Give the optional **Auto-training link** its own section and
  explain that linking is for publishing trained model updates. Satellites send
  audio directly to the trainer URL without linking.
- **Trainer audio delivery reports.** Show queued and active uploads, delivered
  clips, failures, deferred attempts, skipped clips, the last error, and available
  internal memory when reported by satellite firmware. Offline devices retain
  their last report; devices without reports are clearly marked as waiting.
- **Accurate Identify confirmation.** Describe the spoken identification message
  instead of saying that an identify tone was sent.

Update through HACS and restart Home Assistant. Existing defaults are preserved.
Empty STT results, provider errors, and timeouts continue to allow listening.
No satellite firmware update is required for the new timing controls.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.14...v1.4.15)
