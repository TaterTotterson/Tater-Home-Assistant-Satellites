# Tater Satellite 1.4.24

## What's changed

- **Wake arbitration:** Choose one satellite to handle a shared wake in both Home Assistant and Mini-Tater modes. Other satellites quietly return to idle.
- **Adjustable controls:** Compare satellites in the same room or across the home, select strongest command audio or first wake, and tune the selection window, late-wake protection, and busy safety timeout.
- **Audio buffering:** Preserve the beginning of commands during selection, including when satellites send many small packets. Protect the winner through reply playback.
- **Recent decisions:** See which satellite was selected and review the audio comparison in the new **Voice & wake → Wake arbitration** workspace.

Arbitration is enabled by default with same-room scope, strongest-audio selection, a **900 ms** selection window, **1500 ms** late-wake protection, and a **120-second** busy safety timeout. Saved changes apply to new wakes. Home Assistant's own wake cooldown still applies in HA mode.

Update through Marketplace or HACS, then restart Home Assistant. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.23...v1.4.24)
