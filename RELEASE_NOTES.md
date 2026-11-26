# Tater Satellite 1.4.32

## What's changed

- **Administrator-only management:** Require an HA administrator for all 39 bridge management handlers, matching the panel's existing access restriction. Protect settings and status reads, provider connections and keys, Dashboard Studio, pairing, Bluetooth, uploads, firmware installation, and device removal. Reject unauthorized requests before reading their bodies or running actions.
- **Pairing attempt limits:** Invalidate the six-digit satellite pairing code after five failed authentication attempts across connections, device IDs, and addresses. Apply the same limit to the pending first-connection credential retry. An administrator can select **Add Satellite** to generate a new code.
- **Home Assistant login-ban support:** Report rejected satellite authentication to HA's login-ban system so configured IP-ban rules apply.
- **Awareness preview compatibility:** Cache signed camera preview links separately for each HA session so administrator-only image access continues working after background camera events.

All **589 automated tests** pass, including authorization checks for every management handler, pairing limits and concurrent attempts, WebSocket rejection and login reporting, existing device reconnection, and signed preview caching.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **Existing paired satellites keep their credentials, and no satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.31...v1.4.32)
