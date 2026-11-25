# Tater Satellite 1.4.30

## What's changed

- **Original dashboard designs:** Add **Invent an original design** and **Surprise me**. Working examples for bento, editorial, room navigation, control centers, and media walls are optional starting points; the model can combine patterns or invent its own composition.
- **Compare three ideas:** Generate three separate drafts with different compositions, preview them, and choose one to refine with Undo. Keep completed ideas if a later generation fails and continue from the next idea. Generating or choosing ideas does not publish to Home Assistant.
- **Visual directions and themes:** Choose minimal, neon, natural, playful, editorial, or cinematic styling and an installed HA theme. Save palettes, backgrounds, card colors, and layout options in the actual dashboard configuration, and preview view/section themes and backgrounds.
- **Installed community components:** Discover supported registered Mushroom, Bubble Card, Button Card, Mini Graph Card, and card-mod resources. Give the model usage guidance and support verified custom cards and static styling. Native designs remain available, and Studio does not install extra components or themes.
- **Focused editing:** Edit only a selected view or section. Studio preserves surrounding views, sections, and global options in code, then checks that the result still fits the full dashboard.
- **Stronger layout recovery:** Include the detailed output schema for plain-JSON responses and use a focused final repair for missing Sections content. Reject incomplete repairs and palette-only duplicate concepts while keeping the saved draft unchanged. Offer a design retry without requiring a page reload.
- **Smaller prompts and clearer progress:** Balance entity selections across rooms and domains, prioritize requested and existing entities, and continue validating against the full home inventory. Show progress for each idea and distinguish slow model responses from connection failures.
- **Updated guide and regression coverage:** Document the new design workflow. All **576 automated tests** pass, including the frontend checks; comparison and focused-editing controls were also checked in the browser.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. Existing Studio designs remain available. **No satellite firmware update or AI connection change is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.29...v1.4.30)
