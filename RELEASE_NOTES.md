# Tater Satellite 1.4.26

## What's changed

- **Dashboard Studio:** Create and refine Home Assistant dashboards in a dedicated AI design chat. Find it at the bottom of **Your home**, in both HA and Mini-Tater modes.
- **Guided starting points:** Choose a room layout, wall tablet, energy and comfort, security overview, or let the designer suggest a starting point using your actual rooms and entities.
- **Separate AI connection workspace:** Open **AI connection** to configure an OpenAI-compatible API URL, model, and key. Local servers can run without a key. Use **Back to Studio** to return to your design without losing the chat or pending edits. This connection is independent of Mini-Tater's voice and model settings; saved keys stay on the HA server.
- **Preview before applying:** Inspect native HA cards with live entity state at phone, tablet, and desktop widths. Preview controls are disabled. Designs stay as drafts until you choose **Create dashboard** or **Apply to HA**.
- **Reversible saves:** Keep private saved designs and chats, undo draft revisions, restore previous dashboard saves, and detect newer HA edits before overwriting a layout. Proposals are checked for card structure and entity references before being accepted. UI-managed dashboards are supported; YAML-managed dashboards remain read-only.
- **Updated guides and panel caching:** Add the Dashboard Studio guide and refresh the panel and Studio assets together after an update.

Update through Marketplace or HACS, then restart Home Assistant. **No satellite firmware update is required.** Configure Studio's AI connection before starting your first design.

[Dashboard Studio guide](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/blob/v1.4.26/docs/dashboard-studio.md) · [Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.25...v1.4.26)
