# Tater Satellite 1.4.20

## What's changed

- **Shopping and to-do lists.** Ask Mini-Tater to read pending items, add an
  item, mark it complete, or remove it from an existing Home Assistant list.
- **Weather and forecasts.** Get current conditions and supported daily,
  hourly, or twice-daily forecasts from HA's configured weather entities. No
  additional weather API account is needed.
- **Spoken announcements.** Ask to broadcast a message to a named room or
  satellite, or everywhere. Tater satellites use Mini-Tater's configured voice;
  other exposed HA announcement satellites use their configured pipeline.
  Failed destinations are reported.
- **Music and playback.** Play or queue named media through Music Assistant or
  a HA player supporting media search. Pause, resume, skip, stop, mute, and
  adjust volume on supported players.
- **Delayed device actions.** Schedule requests such as “turn off the office
  lights in five minutes,” then list or cancel pending actions. Jobs keep their
  original device targets, survive HA restarts, and recheck the selected entity
  scope before running. Actions missed by more than a minute during an outage
  are marked missed; interrupted actions with unknown outcomes are not retried
  automatically. Up to 50 actions can be pending, up to seven days ahead.
- **More device controls.** Target lights by floor, set supported thermostat
  fan modes, start or dock mowers, adjust speaker volume or mute, and clean named
  HA areas with compatible vacuums and configured area mappings.
- **More Mini-Tater timer controls.** Pause, resume, and add or remove time from
  existing timers using confirmed satellite commands. Running countdowns and
  alarms remain on the satellite; paused remaining time is saved in HA until
  resumed.
- **Current local date and time.** All three Hydra heads receive HA's current
  clock and configured timezone, following Tater's live-clock prompt.
- **Continued conversation fix.** Mini-Tater now checks whether its reply asks
  for an immediate answer and requests microphone reopening after successful
  playback when the satellite's **Continued conversation** setting is enabled.
  Muted microphones stay closed. A failed or timed-out check still lets the
  reply play. HA mode continues to follow its conversation agent's request.
- **Home tools layout and help.** Keep the existing workspace style, with
  **Home Assistant device control** and its **Available now** entity list
  together at the bottom. The README now focuses on setup, with detailed
  instructions in the linked user guide.

The new tools use the existing three-head Hydra flow: Astraeus receives tool
descriptions, and Thanatos passes each locked natural-language instruction to
the selected tool. They use HA's configured integrations and the selected
Assist exposure scope or all supported entities. Home Assistant remains the
default conversation mode.

## Updating

Install through Marketplace or HACS, then **restart Home Assistant** to load
the update. This bridge release does not require a new satellite firmware
release. Available media, weather, and device actions depend on the configured
HA integrations and device capabilities.

## Validation

- 450 automated tests passed, including panel, timer, follow-up, scope, and
  scheduling regressions.
- Home Assistant hassfest validation passed.
- Live end-to-end voice and hardware testing of these additions remains pending.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.19...v1.4.20)
