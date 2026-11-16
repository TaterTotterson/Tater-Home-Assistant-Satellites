# Tater Satellite 1.4.12

- **Clean up forgotten devices.** Forgetting an offline satellite now removes its
  Home Assistant device and entities. Home Assistant can also delete offline or
  orphaned satellite devices, with protections for connected satellites, saved
  stereo pairs, and unrelated devices.
- **Keep rooms in sync.** Bridge features use the satellite's assigned Home
  Assistant area, falling back to its firmware room when no area is assigned.
  Area changes and renames refresh the room context. Ordinary reconnects preserve
  manual area assignments; a changed firmware room updates the Home Assistant area.
- **Give Mini-Tater room context.** Hydra receives the asking satellite's name
  and resolved room throughout planning, execution, and the final reply. Requests
  such as "turn on the lights" can use that room, while explicitly named rooms
  and devices take precedence. Management chat does not assume a room.
- **Preserve Home Assistant compatibility.** Supports the device-registry APIs
  in Home Assistant 2026.6 and newer.

Update the integration through HACS or your usual installation method, then
restart Home Assistant. No satellite firmware update is required for these changes.

## Contributor

Thanks to [Andrew Loe (@loe)](https://github.com/loe) for contributing the device
cleanup and room/area synchronization fixes:

- [#23 — Remove the HA device when forgetting a satellite](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/23)
- [#26 — Sync satellite areas and give Mini-Tater room context](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/pull/26)

Resolves bridge issues [#21](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/issues/21)
and [#25](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/issues/25).
