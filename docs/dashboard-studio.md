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

Detailed designs can take up to **10 minutes**. Choose **Cancel** to stop the
current attempt and keep your prompt, saved draft, and completed ideas. A timeout
also closes the model request. Use an updated Tater app when connecting Studio
to `tater/base` so cancellation stops its local llama.cpp generation as well.

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

## Choose a look

Open **Visual direction** to choose **Calm & minimal**, **Neon control room**,
**Warm & natural**, **Playful color**, **Editorial**, or **Cinematic**, or let the
designer choose. You can describe a completely different look in chat. These
choices steer your next message; selecting a style does not publish changes.

Choose an installed **Home Assistant theme**, or let the designer keep the
current theme or choose one that fits. Studio discovers existing theme names;
it does not install themes or community cards. It can vary layouts, native card
colors and icons, section backgrounds and widths, headers, and view backgrounds.
Full custom typography and card styling depend on the themes already installed.
The styling is part of the proposed Lovelace configuration and remains after
you apply it. Saved designs remember their visual direction and theme choice.

**Layout direction** is separate from the palette. Choose bento, editorial,
room navigation, control center, or a media wall as a starting point. Choose
**Invent an original design**, or the **Surprise me** starter, to let the AI
create its own composition. Examples show working HA structure using actual
entities; they are not fixed templates. The designer can combine patterns,
vary card sizes, choose a focal point and invent a different layout.

When HA has supported registered resources, **Use supported community cards
already installed in HA** lets the designer use Mushroom, Bubble Card, Button
Card, Mini Graph Card, and static card-mod styling as available. Studio supplies
their supported usage, validates custom types against those resources, and loads
needed installed modules for preview. No additional resources are installed.
You can disable this option for a native-only design.

## Compare ideas and refine a section

Select **Show me three ideas** to generate three separate drafts: a bento
approach, an editorial approach, and an original composition. Each generation
has its own progress stage. Ideas must differ in composition, not just palette.
Use **Preview** to compare them, then **Use this idea** to make one your editable
draft. You can return to your previous draft with Undo. Choosing an idea does not
publish it. If generation stops partway through, completed ideas stay saved and
**Finish the three ideas** continues from the next one while the draft is unchanged.

Select **Edit scope** in the preview, or **Edit only this section**, then describe
the change in chat. Studio sends only the selected view or section to the model
and merges that result back into the draft. Unselected views, sections and global
options are preserved in code, even if the model tries to change them. Choose
**Whole dashboard** to return to editing the full composition.

## Preview and apply

The preview uses Home Assistant's card helpers and live entity state.
Phone, tablet, and desktop controls let you inspect different widths. Preview
controls are disabled; the final HA layout may use different spacing. Existing
custom cards can be preserved. New custom cards are limited to supported
components already registered in HA; Studio does not install resources or themes.

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
view, and missing card types for clear entity, heading, list, and grid cards.
Entity rows stay unchanged, and ambiguous card shapes go back to the model for
repair. Incomplete layouts get up to two model repair
attempts with concrete examples and validation feedback. If whole-dashboard
repair repeats missing Sections content, the final attempt asks only for those
missing views and merges their sections while preserving completed views and
options. Models that return plain JSON receive the same detailed output schema.
All attempts share the same overall request timeout. Empty layouts are not filled with invented devices just to pass
validation. These checks are not a full replacement for Home Assistant's frontend
card validation.

## Loading and progress

**Opening Studio** loads the workspace data; **Designing your dashboard** means
the language model is working. The chat opens as soon as the design is created,
including on the first request. Design generation and repair can take longer on
local models. If a connection stalls, Studio ends the spinner and offers
**Reload Studio** to check the latest saved design before trying again.
If a model still returns an invalid design, the saved draft stays unchanged and
**Try design again** keeps your request ready to resend. You can also ask for a
smaller change or use a model with more context.

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
- [Mushroom](https://github.com/piitaya/lovelace-mushroom),
  [Bubble Card](https://github.com/Clooos/Bubble-Card),
  [Button Card](https://github.com/custom-cards/button-card),
  [Mini Graph Card](https://github.com/kalkih/mini-graph-card), and
  [card-mod](https://github.com/thomasloven/lovelace-card-mod): documented component
  options for resources already installed in HA.
- HA's [Lovelace command implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/lovelace/websocket.py):
  normal dashboard reads, saves, and update notifications.
