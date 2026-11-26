# Tater Satellite 1.4.31

## What's changed

- **Faster bridge opening:** Show settings and device status as soon as Home Assistant responds. The optional wake-word catalog loads separately in the background, so a slow catalog request cannot hold the page on “Connecting to your satellites.”
- **Automatic connection recovery:** Load when HA's frontend connection becomes ready and recover after reconnecting. Ignore late responses from an old connection or a closed panel.
- **Clear retry controls:** Retry initial settings reads up to three times. If a read fails or times out, show the error and a **Retry connection** button so you can recover without navigating away.
- **Preserve active work:** Keep unsaved settings and focused editors intact during background updates. Reconnecting never repeats a settings save or satellite command.

All **576 automated tests** pass, including eight new frontend regression checks. Delayed connections, stalled catalog loading, and retry recovery were also checked in the browser.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.30...v1.4.31)
