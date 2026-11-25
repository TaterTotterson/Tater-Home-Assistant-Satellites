# Dashboard Studio

Open **Your home → Dashboard Studio** in either Home Assistant or Mini-Tater
mode. Select **AI connection** to open a separate settings workspace for its
OpenAI-compatible API base URL, model ID, and API key. Use your provider's model
name and key, or connect a local compatible server with an HTTP URL; a key is
optional when the local
server does not require one. Select **Save connection**, then **Back to Studio**
to start designing. Your design, chat, and pending edits stay in place while
you visit connection settings.

When connecting to Tater's own API, use **tater/base** or **tater/direct** as the
model. These forward Studio's prompts and function schema to your language model.
The **tater/hydra** route runs Tater's own assistant flow instead.

Studio's connection is separate from Mini-Tater's models and speech settings.
Keys are stored on the HA server and never returned to the page. Leave the key
field blank to keep a saved key, or select **Remove saved key when saving** to
clear it. No MCP server or additional Home Assistant access token is needed.

Start with **Choose for me**, **Room by room**, **Wall tablet**,
**Energy & comfort**, or **Security overview**. Your designer considers the home's
actual HA areas, entities, and device capabilities and proposes a focused layout. You
can also start with your own request or choose an existing UI-managed dashboard.

Refine it in the dedicated chat:

- "Put the cameras first."
- "Group the lights by room."
- "Make this simpler for a wall tablet."
- "Keep the kitchen view and only change the living room."

Studio remembers each design and its chat. It does not use your satellite
conversations. Studio and saved designs remain available when switching
assistant modes. Designs are private to the HA administrator who created them.

## Preview and apply

The preview uses Home Assistant's native card helpers and live entity state.
Phone, tablet, and desktop controls let you inspect different widths. Preview
controls are disabled; the final HA layout may use different spacing. Existing
custom cards can be preserved, but new designs use built-in cards without
installing resources or themes.

**Undo draft** steps back through proposed designs. **Create dashboard** or
**Apply to HA** publishes the current draft through HA's dashboard commands.
The new dashboard appears in HA's sidebar without a restart.

Before applying, Studio saves a recovery copy and checks that the HA dashboard
has not changed since it was opened. **Restore last save** undoes an applied
change. For a dashboard created by Studio, undoing its first save removes that
new dashboard. Studio keeps five previous saves and five draft undo steps.

If a newer edit is detected, open the dashboard's latest version from the
dashboard selector; the old Studio design remains available in **Your designs**.
You can download a draft as JSON. **Remove Studio design** removes only the
private draft and its chat, not a published HA dashboard.

YAML-managed dashboards are not edited here. Built-in automatically generated
dashboards can be redesigned as explicit views; their previous configuration is
backed up before publishing. Card structure, entity references, known card types,
and domain-specific cards are checked before a proposal is accepted. Studio
repairs unambiguous nesting mistakes, such as cards placed directly on a Sections
view, without dropping content. Incomplete layouts get up to two model repair
attempts with concrete examples and validation feedback, within the same overall
request timeout. Empty layouts are not filled with invented devices just to pass
validation. These checks are not a full replacement for Home Assistant's frontend
card validation.

## Design and implementation references

The implementation uses HA's existing registered command handlers, schema
validation, authenticated administrator, collection management, and update events.
It does not edit HA's storage files or create a second dashboard collection.

The design draws on:

- [Hass-MCP](https://github.com/voska/hass-mcp): draft previews, whole-config
  updates, and backups before writing.
- [HA-MCP](https://github.com/homeassistant-ai/ha-mcp) and its
  [dashboard guide](https://github.com/homeassistant-ai/skills/blob/main/skills/home-assistant-best-practices/references/dashboard-guide.md):
  entity discovery, native layouts, and care around strategy dashboards.
- HA's [Sections](https://www.home-assistant.io/dashboards/sections/),
  [cards](https://www.home-assistant.io/dashboards/cards/), and
  [views](https://www.home-assistant.io/dashboards/views/): room grouping,
  responsive layouts, headings, and appropriate built-in controls.
- HA's [Lovelace command implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/lovelace/websocket.py):
  normal dashboard reads, saves, and update notifications.
