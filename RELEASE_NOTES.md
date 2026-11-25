# Tater Satellite 1.4.29

## What's changed

- **Open existing dashboards:** Fix selecting Overview or another existing dashboard in Dashboard Studio failing with `cannot pickle 'orjson.Fragment' object`.
- **Preserve dashboard content:** Decode Home Assistant's cached JSON responses before creating the Studio draft. Keep the full layout, card options, and dashboard strategy intact, including nested cached content.
- **Regression coverage:** Verify cached and ordinary dashboard loading, independent drafts, successful save responses, and clear errors for invalid responses.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page and select the dashboard again. **No satellite firmware update or AI connection change is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.28...v1.4.29)
