# Tater Satellite 1.4.35

## What's changed

- **More time for detailed dashboards:** Allow up to **10 minutes** for a design or alternative idea, including layout repairs. Keep the page waiting for the result and explain that detailed designs can take longer.
- **Cancel a running design:** Add a **Cancel** button that ends the current attempt while keeping your prompt, saved draft, and completed ideas. A cancellation applies only to that attempt; it cannot stop a newer design or another user's work.
- **Clean up abandoned requests:** Close the model connection when a design is cancelled, reaches its deadline, or loses its browser connection. Completed drafts finish saving safely. Use **Tater 3.0.11 or newer** when connecting to Tater's API so cancellation also stops the matching local llama.cpp generation.

All **606 bridge tests** pass, including longer designs, cancellation, disconnects, deadline cleanup, and saved-draft protection. Browser checks verify the Cancel control and preservation of the design brief.

Update through Marketplace or HACS, restart Home Assistant, then refresh the bridge page. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.34...v1.4.35)
