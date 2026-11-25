// Private dashboard conversations with live, inert Home Assistant card previews.
const escape = value => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const copy = value => JSON.parse(JSON.stringify(value));
const tag = (name, attributes, content = "") => "<" + name + Object.entries(attributes || {}).filter(([, value]) => value !== false && value != null).map(([key, value]) => " " + key + '="' + escape(value === true ? "" : value) + '"').join("") + ">" + content + "</" + name + ">";
const button = (content, attributes = {}) => tag("button", { type: "button", ...attributes }, content);
const STARTERS = [
  ["creation-outline", "Choose for me", "A thoughtful first draft. No brief needed.", "Suggest a calm, useful dashboard for my home. Use my actual rooms and devices, choose a thoughtful layout, and explain your choices."],
  ["floor-plan", "Room by room", "Familiar rooms, useful controls.", "Design a room-by-room home dashboard with a useful overview. Organize lights, comfort, and useful sensors by their real room."],
  ["tablet-dashboard", "Wall tablet", "Glanceable and easy to touch.", "Create a beautiful wall-tablet dashboard: large touch targets, glanceable status, the controls I use most, and a calm layout without clutter."],
  ["lightning-bolt-outline", "Energy & comfort", "Trends and a comfortable home.", "Design an energy and comfort dashboard using the energy, power, temperature and climate entities my home actually has. Avoid invented data."],
  ["shield-home-outline", "Security overview", "The things that need your attention.", "Build a clear security overview using my actual cameras, doors, windows and alarm entities. Group it logically and make important alerts easy to see."],
];

export const studioStyles = [
  ".studio-toolbar,.studio-status,.studio-preview-tools,.studio-pills,.studio-compose-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}",
  ".studio-toolbar{justify-content:space-between;margin-bottom:20px}.studio-toolbar label{display:grid;gap:5px;min-width:210px;font-size:12px;font-weight:600;color:var(--secondary-text-color)}",
  ".studio-toolbar select{max-width:320px}.studio-toolbar-actions{display:flex;gap:8px;align-items:end;flex-wrap:wrap}",
  ".studio-connection-workspace{max-width:900px}.studio-connection-back{margin-bottom:20px}.studio-connection{margin-bottom:22px}.studio-connection-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.studio-connection h2{margin:6px 0;font-size:22px}.studio-connection p{font-size:13px;line-height:1.6;max-width:700px}.studio-connection-grid{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin:20px 0}.studio-connection-grid label{display:grid;gap:8px;font-size:12px;font-weight:600}.studio-connection-grid input{box-sizing:border-box;width:100%;min-width:0}.studio-connection-grid small{font-size:11px;font-weight:400;color:var(--secondary-text-color);line-height:1.5}.studio-connection-key{grid-column:1/-1}.studio-key-options{display:flex;align-items:center;gap:8px;font-size:12px;margin:0 0 16px}.studio-key-options input{width:auto}",
  ".studio-hero{border:1px solid var(--divider-color);border-radius:24px;padding:30px;background:linear-gradient(120deg,color-mix(in srgb,var(--tater-accent) 11%,var(--card-background-color)),var(--card-background-color));margin-bottom:20px}",
  ".studio-hero h2{font-size:28px;letter-spacing:-.7px;margin:9px 0}.studio-hero p{max-width:660px;line-height:1.7}.studio-pills{margin-top:20px}.studio-pills span{font-size:12px;padding:6px 10px;border-radius:20px;border:1px solid var(--divider-color);background:var(--card-background-color)}",
  ".studio-start-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}",
  ".studio-start{padding:20px!important;text-align:left;display:grid;align-content:start;gap:10px;border-radius:18px!important;min-height:126px;background:var(--card-background-color)!important;border:1px solid var(--divider-color)!important;color:var(--primary-text-color)!important}",
  ".studio-start:hover{border-color:var(--tater-accent)!important;transform:translateY(-1px)}.studio-start ha-icon{color:var(--tater-accent)}.studio-start small{font-size:12px;line-height:1.5;color:var(--secondary-text-color)}",
  ".studio-resume-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.studio-resume{padding:18px;border:1px solid var(--divider-color);border-radius:18px;display:flex;gap:12px;align-items:center;justify-content:space-between}.studio-resume strong{display:block}.studio-resume small{color:var(--secondary-text-color)}",
  ".studio-workspace{display:grid;grid-template-columns:minmax(300px,370px) minmax(0,1fr);gap:18px;align-items:start}.studio-chat{padding:0!important;overflow:hidden;position:sticky;top:0}",
  ".studio-chat-head{padding:20px;border-bottom:1px solid var(--divider-color)}.studio-chat-head h3{margin:5px 0;font-size:17px}.studio-chat-head p{font-size:12px;margin:0}",
  ".studio-thread{height:410px;overflow:auto;overscroll-behavior:contain;padding:20px;display:flex;flex-direction:column;gap:16px}",
  ".studio-message{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.7}.studio-message strong{display:block;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;color:var(--secondary-text-color)}",
  ".studio-message.user{background:color-mix(in srgb,var(--tater-accent) 9%,var(--card-background-color));padding:12px 14px;border-radius:15px 15px 4px 15px}.studio-message.assistant{padding-right:8px}",
  ".studio-chat-empty{padding:12px 0}.studio-chat-empty h3{font-size:20px;margin:5px 0}.studio-chat-empty p{line-height:1.7}.studio-chat-empty button{margin-top:10px;width:100%}",
  ".studio-compose{border-top:1px solid var(--divider-color);padding:16px}.studio-compose textarea{box-sizing:border-box;width:100%;min-height:88px;resize:vertical;border-radius:12px;font:inherit;line-height:1.6}.studio-compose-actions{justify-content:space-between;margin-top:10px}.studio-compose-actions small{font-size:10px;color:var(--secondary-text-color)}",
  ".studio-suggestions{padding:0 16px 14px;display:flex;gap:6px;flex-wrap:wrap}.studio-suggestions button{font-size:11px!important;padding:7px 9px!important;white-space:normal;text-align:left}",
  ".studio-preview-panel{padding:0!important;overflow:hidden;min-width:0}.studio-preview-top{padding:18px 20px;border-bottom:1px solid var(--divider-color);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.studio-preview-top h3{margin:0;font-size:17px}",
  ".studio-preview-tools button{font-size:11px;padding:6px 9px}.studio-preview-tools button[aria-pressed=true]{background:color-mix(in srgb,var(--tater-accent) 12%,var(--card-background-color));color:var(--tater-accent);border-color:var(--tater-accent)}",
  ".studio-preview-scroll{padding:22px;background:var(--secondary-background-color);min-height:470px;overflow:auto}.studio-preview-frame{margin:0 auto;max-width:1100px}.studio-preview-frame.phone{max-width:370px}.studio-preview-frame.tablet{max-width:780px}",
  ".studio-view-tabs{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:18px}.studio-view-tabs button{background:var(--card-background-color);border-radius:12px}.studio-view-tabs button[aria-current=true]{border-color:var(--tater-accent);color:var(--tater-accent)}",
  ".studio-view-title{font-size:23px;letter-spacing:-.5px;margin:4px 0 18px}.studio-preview-sections{display:grid;grid-template-columns:repeat(var(--studio-columns,2),minmax(0,1fr));gap:16px}.studio-preview-frame.phone .studio-preview-sections{grid-template-columns:1fr}",
  ".studio-preview-section{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:10px;align-content:start;min-width:0}.studio-native-card{grid-column:span 12;min-width:0;--ha-card-border-radius:16px;--ha-card-border-width:1px}.studio-native-card>*{display:block}",
  ".studio-native-card[inert]{cursor:default}.studio-preview-empty{text-align:center;padding:85px 24px;color:var(--secondary-text-color)}.studio-preview-empty ha-icon{--mdc-icon-size:44px;color:var(--tater-accent);margin-bottom:14px}.studio-preview-empty strong{display:block;color:var(--primary-text-color);font-size:18px}",
  ".studio-preview-note{padding:12px 18px;border-top:1px solid var(--divider-color);font-size:11px;line-height:1.6;color:var(--secondary-text-color)}.studio-error{padding:13px 16px;border-radius:12px;background:color-mix(in srgb,var(--error-color,#c84444) 10%,var(--card-background-color));color:var(--error-color,#c84444);margin-bottom:14px;white-space:pre-wrap}",
  ".studio-busy{display:flex;gap:10px;align-items:center;color:var(--secondary-text-color);font-size:12px}.studio-busy .spinner{width:14px;height:14px;border-width:2px;margin:0}.studio-config{margin-top:16px}.studio-config summary{font-size:12px;color:var(--secondary-text-color)}.studio-remove{font-size:11px!important;color:var(--secondary-text-color)!important}.studio-apply-note{font-size:11px;color:var(--secondary-text-color);margin:9px 0 0}",
  "@media(max-width:1100px){.studio-workspace{grid-template-columns:1fr}.studio-chat{position:static}.studio-thread{height:280px}.studio-preview-sections{grid-template-columns:repeat(2,minmax(0,1fr))}}",
  "@media(max-width:650px){.studio-connection-grid{grid-template-columns:1fr}.studio-hero{padding:22px}.studio-hero h2{font-size:24px}.studio-start-grid{grid-template-columns:1fr 1fr}.studio-preview-scroll{padding:14px}.studio-preview-sections{grid-template-columns:1fr}.studio-toolbar-actions{width:100%}.studio-toolbar label{width:100%}.studio-toolbar select{max-width:none}.studio-thread{height:320px}}",
  "@media(prefers-reduced-motion:reduce){.studio-start:hover{transform:none}}",
].join("\n");

export class DashboardStudio {
  constructor(panel) {
    this.panel = panel;
    this.catalog = null;
    this.workspace = null;
    this.busy = false;
    this.operation = "";
    this.error = "";
    this.notice = "";
    this.message = "";
    this.device = "desktop";
    this.view = 0;
    this._previewRevision = 0;
    this._cards = [];
    this.connectionDraft = null;
    this.screen = "design";
    this._designViewState = null;
  }
  formatError(error) {
    return String(error?.body?.message || error?.body || error?.message || "The design could not be completed. Please try again.");
  }
  async load() {
    if (this.busy) return;
    this.busy = true; this.operation = "load"; this.error = "";
    try { this.panel.render(); this.catalog = await this.loadCatalog(); }
    catch (error) { this.error = this.formatError(error); }
    finally { this.busy = false; this.operation = ""; this.panel.render(); }
  }
  async loadCatalog() {
    return this.panel.api("GET", "dashboard-studio", undefined, {
      timeoutMs: 15000,
      timeoutMessage: "Studio could not finish loading. Home Assistant may be starting or reconnecting. Choose Reload Studio to try again.",
    });
  }
  async request(action, values = {}) {
    return this.panel.api("POST", "dashboard-studio", {
      action, workspace_id: this.workspace?.id, revision: this.workspace?.revision, ...values,
    }, {
      timeoutMs: action === "chat" ? 195000 : 60000,
      timeoutMessage: "Studio lost track of this request. Reload Studio to check the latest saved design before trying again.",
    });
  }
  async saveConnection() {
    if (this.busy || !this.connectionDraft) return;
    this.busy = true; this.operation = "settings"; this.error = ""; this.notice = "";
    try {
      this.panel.render();
      const result = await this.request("settings", { settings: { ...this.connectionDraft } });
      this.catalog = { ...this.catalog, settings: result.settings };
      this.connectionDraft = { ...result.settings, api_key: "", clear_api_key: false };
      this.catalog = await this.loadCatalog();
      this.notice = this.catalog.model_ready ? "Studio connection saved. You're ready to design." : "Connection saved. Add a model and any required API key to start designing.";
    } catch (error) { this.error = this.formatError(error); }
    finally { this.busy = false; this.operation = ""; this.panel.render(); }
  }
  navigate(screen) {
    if (screen === "connection") this._designViewState = this.panel.captureViewState?.();
    this.screen = screen;
    this.error = ""; this.notice = "";
    this.panel.render({ preserveView: false });
    if (screen === "design") this.panel.restoreViewState?.(this._designViewState);
    else {
      this.panel.scrollIntoView?.({ block: "start" });
      this.panel.shadowRoot?.querySelector(".workspace-main")?.scrollTo?.({ top: 0, left: 0 });
    }
  }
  renderConnection() {
    const c = this.catalog;
    if (!c) return "";
    if (!this.connectionDraft) this.connectionDraft = { base_url: "https://api.openai.com/v1", model: "", ...c.settings, api_key: "", clear_api_key: false };
    const draft = this.connectionDraft;
    const field = (name, label, type, placeholder, help) => tag("label", { class: name === "api_key" ? "studio-connection-key" : "" }, escape(label) +
      tag("input", { type, "data-studio-setting": name, value: draft[name], placeholder, disabled: this.busy, autocomplete: type === "password" ? "new-password" : "off", spellcheck: "false" }) + tag("small", {}, escape(help)));
    return tag("div", { class: "studio-connection-workspace" },
      button(this.panel.renderIcon("arrow-left") + " Back to Studio", { class: "studio-connection-back", "data-studio-action": "back-to-design", disabled: this.busy }) +
      tag("section", { class: "card studio-connection", "aria-label": "Dashboard Studio AI connection" },
      tag("div", { class: "studio-connection-head" }, tag("div", {}, '<span class="workspace-eyebrow">Dashboard Studio settings</span><h2>AI connection</h2>') + tag("span", { class: "badge " + (c.model_ready ? "online" : "update") }, c.model_ready ? "Ready to design" : "Setup needed")) +
      '<p class="muted">Use OpenAI or a compatible local model for your dashboard designer. This connection works in both assistant modes and is separate from Mini-Tater’s models.</p>' +
      tag("div", { class: "studio-connection-grid" },
        field("base_url", "API base URL", "url", "https://api.openai.com/v1", "Use an OpenAI-compatible address, including http:// for local servers.") +
        field("model", "Model", "text", "Enter a model ID", "Use the exact model name from your provider.") +
        field("api_key", "API key", "password", c.settings?.api_key_set ? "Key saved · leave blank to keep it" : "Optional for local servers", "Stored on your HA server. Saved keys are never sent back to this page.")) +
      (c.settings?.api_key_set ? tag("label", { class: "studio-key-options" }, tag("input", { type: "checkbox", "data-studio-clear-key": "", checked: draft.clear_api_key, disabled: this.busy }) + "Remove saved key when saving") : "") +
      button("Save connection", { class: "primary", "data-studio-action": "save-settings", disabled: this.busy })));
  }
  async act(action, values = {}) {
    if (this.busy) return;
    this.busy = true; this.operation = action; this.error = ""; this.notice = "";
    try {
      this.panel.render();
      const result = await this.request(action, values);
      if (result.workspace) this.workspace = result.workspace;
      if (action === "remove") this.workspace = null;
      this.catalog = await this.loadCatalog();
      if (action === "apply") this.notice = "Saved to Home Assistant. Your previous layout is backed up.";
      if (action === "undo_apply") this.notice = "The previous Home Assistant layout has been restored.";
      this.view = Math.min(this.view, Math.max(0, (this.workspace?.config?.views?.length || 1) - 1));
    } catch (error) { this.error = this.formatError(error); }
    finally { this.busy = false; this.operation = ""; this.panel.render(); }
  }
  async send(text = this.message) {
    if (this.busy || !String(text).trim()) return;
    const pending = String(text).trim();
    this.message = pending;
    this.busy = true; this.operation = this.workspace ? "chat" : "open"; this.error = ""; this.notice = "";
    try {
      this.panel.render();
      if (!this.workspace) this.workspace = (await this.request("open", { workspace_id: "", title: "My home" })).workspace;
      this.operation = "chat";
      this.panel.render();
      this.workspace = (await this.request("chat", { text: pending })).workspace;
      this.message = "";
      this.operation = "refresh";
      this.panel.render();
      this.catalog = await this.loadCatalog();
    } catch (error) { this.error = this.formatError(error); }
    finally {
      this.busy = false; this.operation = ""; this.panel.render();
      const thread = this.panel.shadowRoot?.querySelector(".studio-thread");
      thread?.scrollTo?.({ top: thread.scrollHeight });
    }
  }
  starterButtons(ready, compact = false) {
    return STARTERS.slice(0, compact ? 3 : STARTERS.length).map(([icon, label, help], index) =>
      button(this.panel.renderIcon(icon) + tag("strong", {}, escape(label)) + (compact ? "" : tag("small", {}, escape(help))), {
        class: compact ? "" : "studio-start", "data-studio-starter": index, disabled: this.busy || !ready,
      })).join("");
  }
  render() {
    const c = this.catalog, w = this.workspace;
    const ready = c?.model_ready;
    let result = "";
    if (this.error) result += tag("div", { class: "studio-error", role: "alert" }, escape(this.error) + " " + button("Reload Studio", { "data-studio-action": "reload", disabled: this.busy }));
    if (this.notice) result += tag("div", { class: "banner success", role: "status" }, escape(this.notice));
    if (this.busy) {
      const label = { load: "Opening Studio…", open: "Opening your design…", chat: "Designing your dashboard…", refresh: "Refreshing your designs…", settings: "Saving AI connection…", apply: "Saving dashboard to Home Assistant…", undo_apply: "Restoring the previous dashboard…", undo_draft: "Restoring the previous draft…", remove: "Removing Studio design…" }[this.operation] || "Working on your dashboard…";
      result += tag("div", { class: "studio-busy", role: "status", style: "margin-bottom:16px" }, '<span class="spinner"></span>' + escape(label));
    }
    if (this.screen === "connection") return result + this.renderConnection();
    const options = tag("option", { value: "" }, "Choose a dashboard…") + (c?.dashboards || []).map((row, index) => tag("option", { value: index }, escape(row.title || row.url_path) + (row.mode === "yaml" ? " · YAML (read-only)" : ""))).join("");
    const status = w ? w.has_changes ? "Draft · not applied" : w.is_new ? "New design" : "In sync with HA" : "Your design workspace";
    result += tag("div", { class: "studio-toolbar" },
      tag("div", { class: "studio-status" }, tag("span", { class: "badge " + (w?.has_changes ? "update" : "online") }, status)) +
      tag("div", { class: "studio-toolbar-actions" }, tag("label", {}, "Edit an existing dashboard" + tag("select", { "data-studio-dashboard": "", disabled: this.busy || !c }, options)) +
        button(this.panel.renderIcon("cog-outline") + " AI connection", { "data-studio-action": "settings", disabled: this.busy || !c }) +
        button(this.panel.renderIcon("plus") + " New design", { "data-studio-action": "new", disabled: this.busy || !c })));
    if (c && !ready) result += tag("div", { class: "verifier-note" }, "Choose AI connection to set up your dashboard designer. Your saved designs stay available here.");
    if (w) return result + this.renderWorkspace(ready);
    result += tag("section", { class: "studio-hero" }, '<span class="workspace-eyebrow">Your AI dashboard designer</span><h2>A dashboard that feels like your home.</h2><p class="muted">Describe what you want, or let your designer find a starting point. Shape the design together, preview it, and apply it when it feels right.</p>' +
      tag("div", { class: "studio-pills" }, [String(c?.home?.areas || 0) + " rooms", String(c?.home?.entities || 0) + " available entities", "Native Home Assistant cards", "Built-in undo"].map(label => tag("span", {}, label)).join("")));
    result += tag("div", { class: "studio-start-grid" }, this.starterButtons(ready));
    result += tag("div", { class: "studio-compose card" }, '<label for="studio-first-message"><strong>Or describe your own idea</strong></label>' + this.composer(ready, true));
    if (c?.workspaces?.length) result += '<div class="workspace-section-heading" style="margin-top:26px"><div><span class="workspace-eyebrow">Pick up where you left off</span><h2>Your designs</h2></div></div>' +
      tag("div", { class: "studio-resume-grid" }, c.workspaces.map(row => tag("article", { class: "studio-resume" },
        tag("div", {}, tag("strong", {}, escape(row.title)) + tag("small", {}, row.url_path === null ? "New dashboard draft" : "Home Assistant dashboard")) +
        button("Continue", { "data-studio-resume": row.id, disabled: this.busy }))).join(""));
    return result;
  }
  composer(ready, first = false) {
    return tag("textarea", { id: first ? "studio-first-message" : null, "data-studio-message": "", "aria-label": "Describe a dashboard change",
      placeholder: first ? "I'd like a simple dashboard for downstairs…" : "Make the lights easier to find…", disabled: this.busy }, escape(this.message)) +
      tag("div", { class: "studio-compose-actions" }, "<small>Enter to send · Shift+Enter for a new line</small>" +
        button(first ? "Start designing" : "Send " + this.panel.renderIcon("arrow-up"), { class: "primary", "data-studio-action": "send", disabled: this.busy || !ready }));
  }
  renderWorkspace(ready) {
    const w = this.workspace, views = w.config?.views || [], selected = views[this.view];
    const action = (name, label, disabled = false, extra = {}) => button(label, { "data-studio-action": name, disabled: this.busy || disabled, ...extra });
    const messages = w.messages?.length ? w.messages.map(message => tag("article", { class: "studio-message " + (message.role === "user" ? "user" : "assistant") },
      tag("strong", {}, message.role === "user" ? "You" : "Designer") + escape(message.content))).join("") :
      tag("div", { class: "studio-chat-empty" }, "<h3>Let's find your starting point.</h3><p class=\"muted\">Describe how you'll use this dashboard, or let your designer suggest a layout from your rooms and devices.</p>" + this.starterButtons(ready, true));
    const chat = tag("section", { class: "card studio-chat" },
      tag("header", { class: "studio-chat-head" }, '<span class="workspace-eyebrow">Your dashboard designer</span>' + tag("h3", {}, escape(w.title)) + '<p class="muted">A separate conversation, just for this design.</p>') +
      tag("div", { class: "studio-thread", "aria-live": "polite" }, messages) +
      tag("div", { class: "studio-suggestions" }, (w.suggestions || []).map((text, index) => button(escape(text), { "data-studio-suggestion": index, disabled: this.busy || !ready })).join("")) +
      tag("div", { class: "studio-compose" }, this.composer(ready)));
    const devices = ["phone", "tablet", "desktop"].map(device => button(this.panel.renderIcon(device === "desktop" ? "monitor" : device === "tablet" ? "tablet" : "cellphone"),
      { "data-studio-device": device, "aria-pressed": String(this.device === device), "aria-label": device + " preview" })).join("");
    const canvas = views.length ? tag("nav", { class: "studio-view-tabs", "aria-label": "Dashboard views" }, views.map((view, index) => button(escape(view.title || "View " + (index + 1)),
      { "data-studio-view": index, "aria-current": String(this.view === index) })).join("")) + tag("h3", { class: "studio-view-title" }, escape(selected?.title || w.title)) + '<div data-studio-native-preview></div>' :
      tag("div", { class: "studio-preview-empty" }, this.panel.renderIcon("view-dashboard-outline") + "<strong>Your design will appear here</strong><p>Start a conversation to turn your home's devices into a dashboard.</p>");
    const preview = tag("section", { class: "card studio-preview-panel" },
      tag("header", { class: "studio-preview-top" }, tag("div", {}, '<span class="workspace-eyebrow">Draft preview</span>' + tag("h3", {}, escape(w.title))) + tag("div", { class: "studio-preview-tools" }, devices)) +
      tag("div", { class: "studio-preview-scroll" }, tag("div", { class: "studio-preview-frame " + this.device }, canvas)) +
      tag("footer", { class: "studio-preview-note" }, "Native HA cards with live state. Controls are disabled in this preview. Screen sizes show how the layout adapts; HA's final spacing may vary."));
    const toolbar = tag("div", { class: "studio-toolbar", style: "margin-top:15px" },
      tag("div", { class: "studio-toolbar-actions" }, action("undo_draft", this.panel.renderIcon("undo") + " Undo draft", !w.can_undo_draft) + action("undo_apply", "Restore last save", !w.can_undo_apply)) +
      tag("div", { class: "studio-toolbar-actions" }, (w.url_path !== null ? tag("a", { class: "button", target: "_blank", rel: "noopener", href: "/" + (w.url_path || "lovelace") }, "Open in HA " + this.panel.renderIcon("open-in-new")) : "") +
        action("apply", this.panel.renderIcon("check") + (w.is_new ? " Create dashboard" : " Apply to HA"), !w.has_changes || !views.length, { class: "primary" })));
    const details = tag("details", { class: "studio-config" }, "<summary>Dashboard configuration</summary>" + tag("pre", {}, escape(JSON.stringify(w.config, null, 2))) + action("export", "Download JSON"));
    const bottom = tag("div", { class: "studio-toolbar", style: "margin-top:20px" }, action("home", this.panel.renderIcon("arrow-left") + " All designs") + action("remove", "Remove Studio design", false, { class: "studio-remove" }));
    return tag("div", { class: "studio-workspace" }, chat + tag("div", {}, preview + toolbar + '<p class="studio-apply-note">Drafts stay in Studio until you apply them. Every save keeps the previous HA layout for undo.</p>' + details + bottom));
  }
  bindEvents() {
    const root = this.panel.shadowRoot;
    root.querySelectorAll("[data-studio-action]").forEach(control => control.addEventListener("click", () => {
      const action = control.dataset.studioAction;
      if (control.disabled || this.busy) return;
      if (action === "settings") return this.navigate("connection");
      if (action === "back-to-design") return this.navigate("design");
      if (action === "save-settings") return this.saveConnection();
      if (action === "send") return this.send();
      if (action === "reload") return this.workspace && this.screen === "design" ? this.act("open", { workspace_id: this.workspace.id }) : this.load();
      if (action === "new") return this.act("open", { workspace_id: "", url_path: null, title: "My home" });
      if (action === "home") { this.workspace = null; this.panel.render(); return; }
      if (action === "export") {
        const url = URL.createObjectURL(new Blob([JSON.stringify(this.workspace.config, null, 2)], { type: "application/json" }));
        const link = document.createElement("a"); link.href = url; link.download = "dashboard.json"; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000); return;
      }
      if (action === "remove") return this.panel.confirmAction(
        "Remove Studio design", "Remove this design and its chat? The Home Assistant dashboard will stay as it is.",
        "Remove design", () => this.act(action),
      );
      if (action === "undo_apply") return this.panel.confirmAction(
        "Restore last save", "Restore the previous Home Assistant layout? Your current Studio draft will be replaced.",
        "Restore layout", () => this.act(action),
      );
      return this.act(action);
    }));
    root.querySelectorAll("[data-studio-setting]").forEach(control => control.addEventListener("input", event => { this.connectionDraft[control.dataset.studioSetting] = event.target.value; }));
    root.querySelector("[data-studio-clear-key]")?.addEventListener("change", event => { this.connectionDraft.clear_api_key = event.target.checked; });
    root.querySelector("[data-studio-message]")?.addEventListener("input", event => { this.message = event.target.value; });
    root.querySelector("[data-studio-message]")?.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.send(); }
    });
    root.querySelector("[data-studio-dashboard]")?.addEventListener("change", event => {
      if (event.target.value === "") return;
      const row = this.catalog.dashboards[Number(event.target.value)];
      if (row) this.act("open", { workspace_id: "", url_path: row.url_path });
    });
    root.querySelectorAll("[data-studio-starter]").forEach(control => control.addEventListener("click", () => this.send(STARTERS[Number(control.dataset.studioStarter)][3])));
    root.querySelectorAll("[data-studio-suggestion]").forEach(control => control.addEventListener("click", () => this.send(this.workspace.suggestions[Number(control.dataset.studioSuggestion)])));
    root.querySelectorAll("[data-studio-resume]").forEach(control => control.addEventListener("click", () => this.act("open", { workspace_id: control.dataset.studioResume })));
    root.querySelectorAll("[data-studio-device]").forEach(control => control.addEventListener("click", () => { this.device = control.dataset.studioDevice; this.panel.render(); }));
    root.querySelectorAll("[data-studio-view]").forEach(control => control.addEventListener("click", () => { this.view = Number(control.dataset.studioView); this.panel.render(); }));
  }
  updateHass(hass) { for (const card of this._cards) card.hass = hass; }
  async mountPreview() {
    const generation = ++this._previewRevision;
    this._cards = [];
    const target = this.panel.shadowRoot?.querySelector("[data-studio-native-preview]");
    if (!target) return;
    const view = this.workspace?.config?.views?.[this.view];
    if (!view) return;
    try {
      if (typeof window.loadCardHelpers !== "function") {
        const resolver = document.createElement("partial-panel-resolver");
        const routes = resolver.getRoutes?.([{ component_name: "lovelace", url_path: "studio-preview" }]);
        await routes?.routes?.["studio-preview"]?.load?.();
      }
      if (typeof window.loadCardHelpers !== "function") throw new Error("Open a Home Assistant dashboard once, then reload Studio to load HA's card preview helpers.");
      const helpers = await window.loadCardHelpers();
      if (generation !== this._previewRevision || !target.isConnected) return;
      const grid = document.createElement("div");
      grid.className = "studio-preview-sections";
      grid.style.setProperty("--studio-columns", this.device === "phone" ? "1" : this.device === "tablet" ? "2" : String(Math.min(3, Math.max(1, Number(view.max_columns) || 3))));
      const sections = view.type === "sections" ? view.sections || [] : [{ cards: view.cards || [] }];
      const makeCard = config => {
        const holder = document.createElement("div"); holder.className = "studio-native-card"; holder.inert = true;
        holder.setAttribute("aria-label", "Preview only");
        if (typeof config.grid_options?.columns === "number") holder.style.gridColumn = "span " + Math.max(1, Math.min(12, config.grid_options.columns));
        const rebuild = () => {
          if (generation !== this._previewRevision) return;
          const old = holder.firstElementChild;
          const card = helpers.createCardElement(copy(config)); card.hass = this.panel._hass;
          card.addEventListener("ll-rebuild", event => { event.stopPropagation(); rebuild(); }, { once: true });
          holder.replaceChildren(card);
          this._cards = this._cards.filter(item => item !== old);
          this._cards.push(card);
        };
        rebuild();
        return holder;
      };
      for (const section of sections) {
        const column = document.createElement("section"); column.className = "studio-preview-section";
        for (const config of section.cards || []) {
          column.append(makeCard(config));
        }
        grid.append(column);
      }
      const children = [];
      if (view.header?.card) children.push(makeCard(view.header.card));
      if (view.badges?.length && helpers.createBadgeElement) {
        const badges = document.createElement("div");
        badges.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px";
        badges.inert = true;
        for (const config of view.badges) {
          const badge = helpers.createBadgeElement(typeof config === "string" ? { type: "entity", entity: config } : copy(config));
          badge.hass = this.panel._hass; badges.append(badge); this._cards.push(badge);
        }
        children.push(badges);
      }
      children.push(grid);
      if (view.footer?.card) children.push(makeCard(view.footer.card));
      target.replaceChildren(...children);
    } catch (error) {
      if (generation !== this._previewRevision) return;
      const note = document.createElement("p"); note.className = "muted"; note.textContent = this.formatError(error); target.replaceChildren(note);
    }
  }
}
