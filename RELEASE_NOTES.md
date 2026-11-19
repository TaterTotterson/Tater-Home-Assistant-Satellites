# Tater Satellite 1.4.16

## What's changed

- **Sound presets in Speaker Equalizer.** Choose Flat, Warm, Voice, or Manual in
  each satellite's settings and through its new Home Assistant Sound preset entity.
  Warm uses the curve suggested in Tater Echo Firmware issue #13 and is the default
  when no EQ has been saved. Voice emphasizes speech; Flat resets all eight bands.
- **Keep your own tuning.** Existing saved curves are preserved as Manual, including
  flat curves. Editing a band or Presence boost switches to Manual. Choosing a
  named preset applies its complete curve and turns Presence boost off.
- **Keep device and bridge EQ in sync.** With Echo firmware 5.0.1 or newer, preset
  changes made on the satellite are saved per device. On connection, the bridge
  adopts the satellite's restored EQ when it has no saved EQ override, before
  sending its first settings update. Existing bridge overrides take priority.
- **Preserve speaker protection.** Presets leave bass protection and the peak
  limiter unchanged, including the device-specific -10 dB or -30 dB bass floor.

Update through HACS and restart Home Assistant. Presets work with Echo firmware
that supports the speaker output chain; firmware 5.0.1 adds preset names and
local EQ synchronization. Devices without speaker EQ support are unaffected.

[EQ suggestion](https://github.com/TaterTotterson/Tater-Echo-Firmware/issues/13) ·
[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.15...v1.4.16)
