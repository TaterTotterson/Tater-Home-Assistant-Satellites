# Tater Satellite 1.4.33

## What's changed

- **Handle mistyped-code retries:** Automatic reconnects with the same incorrect credential count once toward the pairing session's guess limit and once toward HA login failures for that source/credential. Treat spaces and hyphens in six-digit pairing codes equally. Reject every unauthorized connection.
- **Keep protection against different guesses:** Five different incorrect guesses still invalidate the pairing code, including the pending first-connection credential retry. A new pairing session gets a fresh guess budget, independent of cached login reports, so previously attempted credentials cannot bypass the limit. New failures are reported to HA's configured login-ban system.
- **Reset failures after a successful connection:** Use HA's normal successful-login handling for first pairing, interrupted credential handoff recovery, and existing device-token reconnections. This resets the failed-login counter; it does not remove an existing IP ban.
- **Bound retry tracking:** Keep at most 512 source/credential fingerprints, with no raw credentials stored in the retry cache. Expire entries after 30 minutes without retries. Continuous automatic retries refresh their entry instead of periodically adding another login failure.

The first incorrect attempt still counts toward HA's configured ban threshold.

All **601 automated tests** pass, including real WebSocket retries, concurrent requests, formatted codes, different guesses and source addresses, new pairing sessions, successful reconnections, and bounded retry tracking.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **Existing paired satellites keep their credentials, and no satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.32...v1.4.33)
