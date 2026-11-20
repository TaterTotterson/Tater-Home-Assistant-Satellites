# Tater Satellite 1.4.18

## What's changed

- **Change satellite names and rooms live.** Use **Overview → Name & room**
  in the bridge, or edit the satellite's name and area under Home Assistant's
  **Settings → Devices & services**. Clearing the area clears the firmware room;
  renaming an HA area also updates connected satellites assigned to it.
- **Keep firmware and Home Assistant in sync.** Changes are saved on the
  satellite before confirmation. Reconnects retain the saved values, and edits
  made through another controller refresh the bridge's name and room context.
  Firmware remains the source of confirmed identity.
- **Handle failed edits clearly.** Unsupported firmware and offline satellites
  cannot be edited. Failed HA edits restore the last confirmed values and create
  a Repairs notice; bridge drafts survive navigation and automatic refresh.
- **Preserve existing setup.** Pairing, stable device IDs, existing entity IDs,
  and stereo membership stay intact. Newly created entities receive clean default
  IDs without a duplicated Home Assistant area prefix.

## Satellite firmware

Live editing requires the matching firmware update:

- [Native 0.6.6](https://github.com/TaterTotterson/Tater-Native-Firmware/releases/tag/native-0.6.6): Voice PE, Sat1, ReSpeaker XVF3800, and ESP32-S3-BOX-3.
- [Echo 5.0.2](https://github.com/TaterTotterson/Tater-Echo-Firmware/releases/tag/v5.0.2): all supported Echo satellites.
- [ThirdReality S420 0.2.26](https://github.com/TaterTotterson/Tater-ThirdReality-Voice-Firmware/releases/tag/s420-0.2.26).
- Standalone Linux satellites: shared runtime `v1.1.13-tater3`.

[Tater 3.0.4](https://github.com/TaterTotterson/Tater/releases/tag/v3.0.4) adds
matching controls for satellites connected to Tater. Use the satellite's connected
controller; no reset or re-pairing is required. Echo devices must already be on
the v5 hardware baseline to use application OTA.

Install the bridge update through Marketplace or HACS, then restart Home Assistant.
Home Assistant 2026.6.0 remains the minimum supported version.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.17...v1.4.18)
