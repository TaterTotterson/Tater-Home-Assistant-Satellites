# Tater Satellite 1.4.28

## What's changed

- **Accurate design progress:** Open the first design's chat as soon as its workspace is created. Show **Designing your dashboard** while the model runs, rather than leaving the page on **Opening Studio**. Connection saves, dashboard saves, and refreshes also show the correct progress stage.
- **Recovery from stalled requests:** Add request timeouts so a lost connection ends the spinner and offers **Reload Studio**. Reload checks the saved design before another attempt; timed-out design and save requests are not automatically repeated.
- **Frontend startup and reconnection:** Wait for the Home Assistant frontend connection before loading bridge settings, and refresh bridge and Studio data after it reconnects. Limit how long the optional wake-word catalog can delay initial panel loading.
- **Missing card-type repair:** Correct clear shorthand entity, heading, list, markdown, grid, and conditional cards, including nested cards. Preserve card options and entity rows. Ambiguous layouts receive explicit card-type feedback for model repair instead of guessing their intended type.
- **Regression coverage and guide updates:** Cover first-request progress, loading timeouts, late responses, frontend reconnection, and missing card types.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **No satellite firmware update or AI connection change is required.** You can keep using **tater/base**.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.27...v1.4.28)
