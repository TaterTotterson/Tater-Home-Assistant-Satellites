# Tater Satellite 1.4.25

## What's changed

- **Web search for Mini-Tater:** Ask for current online information through the normal Hydra flow. DuckDuckGo is tried first, with an automatic Bing fallback. No API key, account, or search settings are needed.
- **Sources in chat:** Answers use search snippets, with clickable source links below the reply. Links are kept separate from spoken answers. Searches run outside HA's event loop, cache repeated questions briefly, and report failures clearly.
- **Clearer Scheduled actions card:** Find delayed device actions in **Home tools**, with examples, listing/cancellation guidance, and the seven-day scheduling limit.
- **Updated guides:** Document all nine Mini-Tater tools and add SAT1 Raspberry Pi satellite and embedded Tater image links.

Web search requires internet access and uses unofficial search-page access. Providers can occasionally block or limit searches.

Update through Marketplace or HACS, then restart Home Assistant. **No satellite firmware update is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.24...v1.4.25)
