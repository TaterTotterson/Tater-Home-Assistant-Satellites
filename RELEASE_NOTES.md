# Tater Satellite 1.4.22

## What's changed

- **Doorbell workspace in both modes.** Set up doorbell greetings and camera
  popups while using Home Assistant or Mini-Tater.
- **Choose each device independently.** Select the press trigger, camera, and
  any HA media player that supports playing the generated audio. A UniFi Protect
  doorbell speaker or a separate speaker from another integration can be used.
- **Steer the greeting.** Edit the prompt describing how the assistant should
  greet visitors. Reuse the shared Vision model and the active mode's speech
  provider; HA mode uses the default Assist pipeline's TTS engine and voice.
- **Optional live camera popups.** Open the selected camera on Show or Rook
  satellites for 10–300 seconds. Popups can be dismissed and restore the previous
  workspace when they expire. Manual camera navigation takes ownership of its
  view. Screen delivery runs independently of the AI greeting.
- **Camera-only setup.** Disable the greeting to display a camera without a
  Vision model or TTS provider.
- **Controls and activity.** Save, edit, pause, delete, and test doorbells. Add
  cooldowns and retain the last 50 activity results, with separate speaker and
  screen errors. A failure at one destination does not block the other outputs.

## Updating

Install through Marketplace or HACS, then restart Home Assistant. Automatic
camera popups require **Echo firmware 5.0.4 or newer with camera popup support**
on the selected Show or Rook. Older firmware remains usable for ordinary camera
viewing and is shown with an update note. Doorbell greetings do not require a
satellite firmware update. Speaker playback depends on the media player's audio
format support and network access to Home Assistant.

Saved doorbells, cooldowns, and recent activity persist across HA restarts.
Doorbell snapshots are sent to Vision for the greeting and are not retained by
this feature. Live end-to-end doorbell and speaker testing remains pending.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.21...v1.4.22)
