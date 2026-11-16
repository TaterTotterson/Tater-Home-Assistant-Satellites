# Tater Satellite 1.4.13

- **Use the room configured in satellite firmware.** The bridge and Mini-Tater
  always use the satellite's firmware room. An HA area assignment cannot override
  the room used for requests such as "turn on the lights". This corrects the room
  precedence introduced in 1.4.12.
- **Match Home Assistant to that room.** The satellite's HA device is assigned to
  the matching area, creating the area if needed. Startup, pairing, reconnects,
  and HA area edits or renames restore that match, including existing mismatched
  assignments from 1.4.12. Other devices keep their assignments, and no room
  changes are sent to the satellite firmware.
- **Keep unknown rooms unassigned.** An explicitly empty firmware room clears the
  satellite's room context and HA area. Missing room metadata preserves the last
  firmware-reported room. Mini-Tater does not infer a room from an HA override.
- **Preserve the other improvements.** Offline device cleanup and Mini-Tater's
  room-aware planning, execution, and responses remain included.

Update the integration and restart Home Assistant. No satellite firmware update
or reset is required for this correction.

Contributor: @loe (Andrew Loe) — device cleanup and initial room/area integration
([#23](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/23),
[#26](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/26)).
