# Tater Satellite 1.4.36

## What's changed

- **Tell the designer what Studio supports:** Supply an explicit guide to native cards, installed community components, layout rules, required card fields, and design limits with every request. Keep freedom to create original compositions within those capabilities.
- **Constrain card names:** Give the model explicit supported card-type choices in design and repair schemas. Preserve existing custom cards and avoid treating fragments of JSON as card names.
- **Repair the affected layout:** Target missing or malformed sections and cards with precise field paths, preserving complete views and view options. Explain invalid output without assuming a model needs more context.
- **Recover encoded layout containers:** Decode complete JSON-encoded views, sections, and cards while preserving card text and entity rows. Keep validation in place and leave the saved draft unchanged if repair fails.

All **611 automated tests** pass, including the reported malformed card-name shapes, focused repairs, supported-component choices, encoded layouts, and saved-draft protection.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.35...v1.4.36)
