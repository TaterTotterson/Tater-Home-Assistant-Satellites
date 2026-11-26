# Tater Satellite 1.4.34

## What's changed

- **Open the bridge reliably:** Fix the page getting stuck on **Connecting to Home Assistant** when first opened. Settings now load without clicking another HA page and returning.
- **Recover the early connection handoff:** Keep the HA connection and panel configuration when Home Assistant supplies them before Dashboard Studio finishes loading. Future HA updates and reconnects continue reaching the panel normally.

All **601 automated tests** pass, including startup, reconnect, settings draft, and save coverage. A browser reproduction confirmed the original freeze and verified the fix with delayed Studio loading.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.33...v1.4.34)
