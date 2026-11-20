# Tater Satellite 1.4.19

## What's changed

- **Scan only when requested.** Open **Bluetooth** and choose **Scan for devices**
  for a 15-second discovery window. Opening the panel or refreshing it does not
  start Bluetooth. Discovery expires automatically and pauses for voice activity.
- **Keep devices connected.** **Stop scan** ends discovery without closing active
  GATT connections. Bluetooth stays enabled while a device needs a connection,
  then powers down after a short idle delay. Saved bonds alone do not enable it.
- **Use compatible satellites.** Updated Native ESP32 and ThirdReality satellites
  now provide the same GATT proxy as Echo and supported Linux satellites, in both
  HA and Mini-Tater modes. BlueZ advertisements retain manufacturer and service
  data for Home Assistant discovery.
- **Preserve pairing.** Existing bond keys remain on the satellite. Pairing
  accepts an exact six-digit PIN, does not save the PIN, and preserves connections
  already used by another consumer.

## Matching firmware and Tater updates

- [Native 0.6.7](https://github.com/TaterTotterson/Tater-Native-Firmware/releases/tag/native-0.6.7): Voice PE, Sat1, ReSpeaker XVF3800, and ESP32-S3-BOX-3.
- [Echo 5.0.3](https://github.com/TaterTotterson/Tater-Echo-Firmware/releases/tag/v5.0.3): application OTA for devices on the v5 hardware baseline.
- [ThirdReality S420 0.2.27](https://github.com/TaterTotterson/Tater-ThirdReality-Voice-Firmware/releases/tag/s420-0.2.27): install the signed system OTA or matching factory image to add BlueZ and Bleak. An application-only update cannot add these dependencies.
- [Linux runtime v1.1.13-tater4](https://github.com/TaterTotterson/Tater-Linux-Satellite/releases/tag/v1.1.13-tater4): requires BlueZ and system D-Bus access.
- [Tater 3.0.5](https://github.com/TaterTotterson/Tater/releases/tag/v3.0.5) adds the matching Bluetooth workspace and removes room presence tracking in the main app.
- [Meshtastic Core 0.3.6](https://github.com/TaterTotterson/Tater_Shop/releases/tag/Meshtastic_Core_v0.3.6) starts bounded discovery through the selected satellite.

Update firmware to stop the previous automatic scanning. This on-demand mode
does not continuously monitor broadcast-only sensors or provide Bluetooth speaker
audio. Physical pairing, reconnect, and voice coexistence testing remain pending.

Install through Marketplace or HACS, then restart Home Assistant. Home Assistant
2026.6.0 remains the minimum supported version.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.18...v1.4.19)
