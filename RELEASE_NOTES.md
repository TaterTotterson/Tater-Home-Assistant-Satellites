# Tater Satellite 1.4.38

## What's changed

- **Smaller jobs for dashboard models:** Studio now plans short natural-language tasks, executes one task at a time, then explains the completed draft. The bridge builds the Home Assistant layout structure instead of asking the model to generate or repeatedly repair an entire nested dashboard.
- **Full redesigns and precise edits:** Create new views and sections, add or edit cards, remove content, and reorder existing items. Each task receives the relevant nodes and devices; unrelated content and card options stay in place.
- **Keep the design experience:** Continue using the existing Studio AI connection, visual directions, themes, installed community cards, preview, alternative ideas, Apply, Undo, and Cancel. A failed or cancelled design leaves the saved draft unchanged.

All **625 automated tests** pass. Also verified with a local model: generated an Office draft, then changed only its requested heading while preserving every other part of the draft.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.37...v1.4.38)
