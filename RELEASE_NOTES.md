# Tater Satellite 1.4.11

- Fix silent **Identify** buttons in the bridge panel and Home Assistant device
  controls. The satellite now speaks an identification message, like the Tater
  app, instead of receiving a tone request with no playable audio URL.
- Use the satellite's selected Assist pipeline TTS voice in Home Assistant mode,
  or Mini-Tater's configured TTS provider and voice in Mini-Tater mode.
- Wait for announcement playback and report TTS, connection and playback errors
  instead of silently succeeding.

No satellite firmware update is required for this fix. Configure a working TTS
voice for the selected assistant, update the integration, and restart Home
Assistant.

Fixes [Tater Echo firmware issue #14](https://github.com/TaterTotterson/Tater-Echo-Firmware/issues/14).
