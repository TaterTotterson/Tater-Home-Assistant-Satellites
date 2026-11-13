const API = "tater/satellite/v1";
const ACCENT = "#e87b40";
const TATER_HOSTED_USB_FLASHER_URL = "https://taterassistant.com/usb-flasher/";
const PANEL_ASSET_VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";
const PANEL_ELEMENT_NAME = `tater-satellite-panel-${
  PANEL_ASSET_VERSION.toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "dev"
}`;
const VOICE_DEFAULT_SETTING_KEYS = new Set([
  "wake_sound_enabled",
  "wake_sound",
  "wake_sound_url",
  "wake_sound_asset_id",
  "muted",
  "continued_chat",
  "barge_in_enabled",
  "aec_enabled",
  "aec_strength_percent",
  "aec_delay_ms",
  "logging_level",
]);
const TRAINER_SETTING_KEYS = new Set([
  "capture_wake_audio",
  "capture_close_misses",
  "close_miss_threshold",
  "trainer_app_url",
]);
const WAKE_VERIFIER_SETTING_KEYS = new Set([
  "wake_verifier_mode",
  "wake_verifier_threshold",
]);
const WORKSPACE_PAGES = [
  { id: "assistant", label: "Assistant", icon: "robot-outline", group: "Tater assistant", description: "Choose who owns each voice turn: Home Assistant Assist or the complete Tater pipeline." },
  { id: "models", label: "Models & speech", icon: "creation-outline", group: "Tater assistant", description: "Connect Tater's language, speech-to-text, and text-to-speech providers." },
  { id: "home-control", label: "Home control", icon: "home-automation", group: "Tater assistant", description: "Choose which Home Assistant entities Tater's one built-in device tool can use." },
  { id: "hydra", label: "Hydra", icon: "chart-timeline-variant-shimmer", group: "Tater assistant", description: "Tune conversation memory and inspect every device-control decision." },
  { id: "satellites", label: "Satellites", icon: "access-point", group: "Your home", description: "Voice around your home, connected directly to Home Assistant." },
  { id: "audio", label: "Tater Audio", icon: "waveform", group: "Your home", description: "Stereo pairs, room playback, and push-to-talk intercom." },
  { id: "bluetooth", label: "Bluetooth", icon: "bluetooth", group: "Your home", description: "Echo scanners and the nearby devices they connect to Home Assistant." },
  { id: "defaults", label: "Voice defaults", icon: "microphone", group: "Voice & wake", description: "One shared wake profile, with clear defaults for every satellite." },
  { id: "verifier", label: "STT wake check", icon: "text-recognition", group: "Voice & wake", description: "Confirm wake words through each satellite’s Assist pipeline." },
  { id: "trainer", label: "Wake Word Trainer", icon: "school-outline", group: "Voice & wake", description: "Link your trainer and publish wake words to your satellites." },
  { id: "firmware", label: "Firmware & recovery", icon: "package-variant-closed-check", group: "Maintenance", description: "Update wirelessly or prepare a board-specific USB installer." },
];
const TATER_ONLY_PAGE_IDS = new Set(["models", "home-control", "hydra"]);
const DEVICE_SETTING_GROUPS = [
  { id: "voice", label: "Voice", sections: ["audio"] },
  { id: "wake", label: "Wake", sections: ["wake", "wake_sound", "feedback", "verifier"] },
  { id: "audio", label: "Audio", sections: ["audio_output", "output_chain"] },
  { id: "display", label: "Display & lights", sections: ["display", "led"] },
  { id: "quiet", label: "Quiet hours", sections: ["dnd"] },
  { id: "diagnostics", label: "Diagnostics", sections: ["diagnostics"] },
];
const SHARED_SETTING_GROUPS = [
  { id: "conversation", label: "Conversation", sections: ["audio"] },
  { id: "sound", label: "Wake sound", sections: ["wake_sound"] },
  { id: "diagnostics", label: "Diagnostics", sections: ["diagnostics"] },
];
const PICKER_SETTING_KEYS = new Set(["wake_word", "oww_wake_word", "wake_word_catalog_url", "oww_wake_word_catalog_url", "wake_sound"]);

function pickSettings(values, allowedKeys) {
  return Object.fromEntries(
    Object.entries(values || {}).filter(([key]) => allowedKeys.has(key)),
  );
}

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const clone = (value) => JSON.parse(JSON.stringify(value ?? {}));

const isWakeWordCatalogUrl = (value) => {
  try {
    const url = new URL(String(value || ""));
    return (
      url.protocol === "https:" &&
      url.hostname.toLowerCase() === "raw.githubusercontent.com" &&
      /^\/TaterTotterson\/Tater-Wake-Words\/main\/microWakeWordsV[0-9]+\/[^/]+\.json$/i.test(
        url.pathname,
      )
    );
  } catch (_error) {
    return false;
  }
};

const browserUsbCapability = () => {
  if (typeof window === "undefined" || !window.isSecureContext) {
    return {
      available: false,
      message: "Browser USB needs a secure Home Assistant page opened over HTTPS or localhost.",
    };
  }
  const serial = typeof navigator === "undefined" ? null : navigator.serial;
  if (!serial || typeof serial.requestPort !== "function") {
    return {
      available: false,
      message: "This browser session does not expose Web Serial. Open Home Assistant in Chrome or Edge and try again.",
    };
  }
  return {
    available: true,
    message: "Browser USB is ready. The browser will ask you to choose the connected ESP satellite.",
  };
};

const formatApiError = (error) => {
  const seen = new Set();
  const extract = (value) => {
    if (typeof value === "string") return value.trim();
    if (!value || typeof value !== "object" || seen.has(value)) return "";
    seen.add(value);
    for (const key of ["message", "detail", "error", "body", "statusText"]) {
      const message = extract(value[key]);
      if (message) return message;
    }
    try {
      const serialized = JSON.stringify(value);
      if (serialized && serialized !== "{}") return serialized;
    } catch (_error) {
      // Fall through to the generic request error.
    }
    return "";
  };
  return extract(error) || "The request failed. Check the satellite diagnostics and try again.";
};

const formatAge = (timestamp) => {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - Number(timestamp || 0)));
  if (!timestamp) return "Never";
  if (seconds < 10) return "Just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
};

const formatBytes = (value) => {
  const bytes = Number(value || 0);
  if (!bytes) return "—";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
};

const formatDateTime = (value) => {
  if (!value) return "Never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
};

const fileToBase64 = async (file) => {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const step = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += step) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + step));
  }
  return btoa(binary);
};

class TaterSatellitePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = "";
    this._notice = "";
    this._tab = "satellites";
    this._selectedDeviceId = "";
    this._taterDraft = null;
    this._hydraSection = "ledger";
    this._testMessage = "";
    this._testConversationId = "tater-panel-test";
    this._globalDraft = null;
    this._wakeDraft = null;
    this._deviceDraft = null;
    this._deviceOriginal = null;
    this._pipelineDraft = "";
    this._dirty = false;
    this._loading = false;
    this._recovery = null;
    this._recoveryBoard = "";
    this._recoveryFlashKind = "factory";
    this._wakeWordCatalog = null;
    this._wakeWordCatalogLastAttempt = 0;
    this._pollTimer = null;
    this._backgroundRenderPending = false;
    this._renderRevision = 0;
    this._deviceSection = "overview";
    this._voiceSection = "wake";
    this._firmwareSection = "updates";
    this._deviceQuery = "";
    this._roomFilter = "";
    this._dialog = "";
    this._confirmation = null;
    this._picker = null;
    this._pickerQuery = "";
    this._dialogFocus = null;
    this._dirtyScopes = new Set();
    this._deviceDrafts = new Map();
    this._stereoDraft = {};
    this.addEventListener?.("keydown", (event) => this.handleDialogKeydown(event));
  }

  set hass(value) {
    this._hass = value;
    const darkMode = value?.themes?.darkMode;
    this.style?.setProperty("color-scheme", typeof darkMode === "boolean" ? darkMode ? "dark" : "light" : "light dark");
    if (!this._data && !this._loading) this.load();
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    if (this._hass && !this._data) this.load();
    if (!this._pollTimer) {
      this._pollTimer = window.setInterval(() => {
        if (document.hidden || this.hasActiveInput()) return;
        if (this._backgroundRenderPending) {
          this._backgroundRenderPending = false;
          this.render();
          return;
        }
        this.load(true);
      }, 5000);
    }
  }

  disconnectedCallback() {
    if (this._pollTimer) window.clearInterval(this._pollTimer);
    this._pollTimer = null;
    if (this._recovery?.blobUrl) URL.revokeObjectURL(this._recovery.blobUrl);
  }

  async api(method, path, body) {
    if (!this._hass) throw new Error("Home Assistant is not ready");
    return this._hass.callApi(method, `${API}/${path}`, body);
  }

  hasActiveInput() {
    const active = this.shadowRoot?.activeElement;
    return Boolean(
      active?.matches('input, select, textarea, [contenteditable="true"]'),
    );
  }

  settingScope(scope, key = "") {
    if (scope === "device") return `device:${this._selectedDeviceId}`;
    if (scope === "global") {
      if (TRAINER_SETTING_KEYS.has(key)) return "trainer";
      if (WAKE_VERIFIER_SETTING_KEYS.has(key)) return "verifier";
    }
    return scope;
  }

  markDirty(scope, key = "") {
    this._dirtyScopes.add(this.settingScope(scope, key));
    this._dirty = true;
    this.shadowRoot?.querySelectorAll("[data-draft-status]").forEach((node) => {
      node.textContent = this.isScopeDirty(node.dataset.draftStatus) ? "Unsaved changes" : "Settings synchronized";
    });
  }

  isScopeDirty(scope) {
    return this._dirtyScopes.has(this.settingScope(scope));
  }

  clearDirty(...scopes) {
    scopes.forEach((scope) => {
      const key = this.settingScope(scope);
      this._dirtyScopes.delete(key);
      if (key.startsWith("device:")) this._deviceDrafts.delete(key.slice(7));
    });
    this._dirty = this._dirtyScopes.size > 0;
  }

  rememberDeviceDraft() {
    if (!this._selectedDeviceId || !this.isScopeDirty("device")) return;
    this._deviceDrafts.set(this._selectedDeviceId, {
      draft: clone(this._deviceDraft), original: clone(this._deviceOriginal),
      pipeline: this._pipelineDraft,
    });
  }

  syncDrafts(data) {
    const fresh = this.prepareSettingsDraft(data.global_settings);
    if (!this._globalDraft) this._globalDraft = fresh;
    else Object.entries(fresh).forEach(([key, value]) => {
      if (!this._dirtyScopes.has(this.settingScope("global", key))) this._globalDraft[key] = value;
    });
    if (!this._wakeDraft || !this.isScopeDirty("wake")) {
      this._wakeDraft = this.prepareSettingsDraft(data.shared_wake_settings || data.wake_family_settings?.echo || data.wake_family_settings?.mww || {});
    }
    if (!this._taterDraft || !this.isScopeDirty("tater")) {
      this._taterDraft = clone(data.tater_assistant?.settings || {});
    }
    if (!this.isTaterModeSelected() && TATER_ONLY_PAGE_IDS.has(this._tab)) this._tab = "assistant";
    if (this._selectedDeviceId && !this.isScopeDirty("device")) this.prepareDeviceDraft(this._selectedDeviceId, false);
  }

  isTaterModeSelected() {
    return String(this._taterDraft?.assistant_mode || "home_assistant") === "tater";
  }

  visibleWorkspacePages() {
    return WORKSPACE_PAGES.filter((page) => this.isTaterModeSelected() || !TATER_ONLY_PAGE_IDS.has(page.id));
  }

  navigate(tab) {
    if (!this.visibleWorkspacePages().some((page) => page.id === tab)) return;
    this.rememberDeviceDraft();
    this._tab = tab;
    this._selectedDeviceId = "";
    this._dialog = "";
    this.render({ preserveView: false });
    this.scrollIntoView?.({ block: "start" });
    this.shadowRoot.querySelector(".workspace-main")?.scrollTo?.({ top: 0, left: 0 });
  }

  captureViewState() {
    const root = this.shadowRoot;
    if (!root?.querySelectorAll) return null;
    const scrollSelector = ".workspace-main, .assistant-test-thread, .entity-list, .workspace-dialog, .workspace-dialog-backdrop, pre";
    const internalScroll = [...root.querySelectorAll(scrollSelector)].map((node, index) => ({
      index,
      top: Number(node.scrollTop || 0),
      left: Number(node.scrollLeft || 0),
    })).filter((row) => row.top || row.left);
    const openDetails = [...root.querySelectorAll("details")]
      .map((node, index) => node.open ? index : -1)
      .filter((index) => index >= 0);
    const externalScroll = [];
    const seen = new Set();
    const remember = (node) => {
      if (!node || seen.has(node) || typeof node.scrollTop !== "number") return;
      seen.add(node);
      const top = Number(node.scrollTop || 0);
      const left = Number(node.scrollLeft || 0);
      if (top || left) externalScroll.push({ node, top, left });
    };
    let current = this;
    while (current && !seen.has(current)) {
      remember(current);
      if (current.parentNode) {
        current = current.parentNode;
      } else if (current.host) {
        current = current.host;
      } else {
        const currentRoot = current.getRootNode?.();
        current = currentRoot?.host || null;
      }
    }
    remember(this.ownerDocument?.scrollingElement || globalThis.document?.scrollingElement);
    return { scrollSelector, internalScroll, openDetails, externalScroll };
  }

  restoreViewState(state) {
    if (!state || !this.shadowRoot?.querySelectorAll) return;
    const internalNodes = [...this.shadowRoot.querySelectorAll(state.scrollSelector)];
    state.internalScroll.forEach(({ index, top, left }) => {
      const node = internalNodes[index];
      if (!node) return;
      node.scrollTop = top;
      node.scrollLeft = left;
    });
    const details = [...this.shadowRoot.querySelectorAll("details")];
    state.openDetails.forEach((index) => {
      if (details[index]) details[index].open = true;
    });
    state.externalScroll.forEach(({ node, top, left }) => {
      if (!node?.isConnected && node !== this.ownerDocument?.scrollingElement) return;
      node.scrollTop = top;
      node.scrollLeft = left;
    });
  }

  confirmAction(title, message, label, action) {
    this._dialogFocus = this.shadowRoot.activeElement;
    this._confirmation = { title, message, label, action };
    this.render();
  }

  closeDialog() {
    const focus = this._dialogFocus;
    const action = focus?.dataset?.action;
    const setting = focus?.dataset?.pickSetting;
    this._dialog = "";
    this._confirmation = null;
    this._picker = null;
    this.render();
    const candidates = this.shadowRoot.querySelectorAll("button");
    [...candidates].find((button) => setting ? button.dataset.pickSetting === setting : action && button.dataset.action === action)?.focus();
  }

  handleDialogKeydown(event) {
    const dialog = this.shadowRoot.querySelector(".workspace-dialog");
    if (!dialog) return;
    if (event.key === "Escape") { event.preventDefault(); this.closeDialog(); return; }
    if (event.key !== "Tab") return;
    const controls = [...dialog.querySelectorAll("button, input, select, textarea, a[href], summary")].filter((node) => !node.disabled && node.getClientRects().length);
    const first = controls[0], last = controls.at(-1), active = this.shadowRoot.activeElement;
    if (event.shiftKey && (active === first || !dialog.contains(active))) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && (active === last || !dialog.contains(active))) { event.preventDefault(); first?.focus(); }
  }

  async load(background = false) {
    if (this._loading) return;
    this._loading = true;
    if (!background) this.render();
    try {
      const data = await this.api("GET", "manage");
      const catalogOptions = this._wakeWordCatalog?.options;
      const catalogUnavailable =
        !Array.isArray(catalogOptions) || catalogOptions.length === 0;
      const catalogRetryDue =
        Date.now() - this._wakeWordCatalogLastAttempt >= 30_000;
      if (!this._wakeWordCatalog || (catalogUnavailable && catalogRetryDue)) {
        this._wakeWordCatalogLastAttempt = Date.now();
        try {
          this._wakeWordCatalog = await this.api("GET", "wake-word/catalog");
        } catch (error) {
          this._wakeWordCatalog = {
            options: [],
            warning: formatApiError(error),
          };
        }
      }
      this._data = data;
      this._error = "";
      this.syncDrafts(data);
    } catch (error) {
      this._error = formatApiError(error);
    } finally {
      this._loading = false;
      if (!background || !this.hasActiveInput()) {
        this._backgroundRenderPending = false;
        this.render();
      } else {
        this._backgroundRenderPending = true;
      }
    }
  }

  async run(action, successMessage = "", savedScopes = []) {
    const savedKeys = savedScopes.map((scope) => this.settingScope(scope));
    this._error = "";
    this._notice = "";
    this._loading = true;
    this.render();
    try {
      await action();
      this._notice = successMessage;
      this.clearDirty(...savedKeys);
      this._loading = false;
      await this.load(true);
    } catch (error) {
      this._error = formatApiError(error);
      this._loading = false;
      this.render();
    }
  }

  render({ preserveView = true } = {}) {
    if (!this.shadowRoot) return;
    const viewState = preserveView ? this.captureViewState() : null;
    const renderRevision = ++this._renderRevision;
    if (this._dialog === "picker" && !(this._data?.settings_schema || []).some((section) => section.fields?.some((field) => field.key === this._picker?.key))) {
      this._dialog = "";
      this._picker = null;
    }
    this.shadowRoot.innerHTML = `
      <style>${this.styles()}${this.workspaceStyles()}</style>
      <div class="bridge-workspace">
        <header class="workspace-topbar"><span class="workspace-brand">Tater</span><span class="muted">/</span><span>Home Assistant bridge</span>
          <span class="workspace-connection">${this.renderIcon("home-assistant")} Home Assistant</span>
        </header>
        <div class="workspace-shell">
          ${this.renderNavigation()}
          <main class="workspace-main" ${this._dialog || this._confirmation ? "inert" : ""}>
            ${this.renderHeader()}
            ${this._error ? `<div class="banner error" role="alert">${escapeHtml(this._error)}</div>` : ""}
            ${this._notice ? `<div class="banner success" role="status">${escapeHtml(this._notice)}</div>` : ""}
            ${!this._data ? this.renderLoading() : this.renderBody()}
          </main>
        </div>
      </div>
      ${this.renderDialog()}
    `;
    this.bindEvents();
    this.applyDeviceFilter();
    this.shadowRoot.querySelector("[data-dialog-initial]")?.focus();
    this.restoreViewState(viewState);
    window.requestAnimationFrame?.(() => {
      if (this._renderRevision === renderRevision) this.restoreViewState(viewState);
    });
  }

  renderIcon(name) {
    return `<ha-icon icon="mdi:${escapeHtml(name)}" aria-hidden="true"></ha-icon>`;
  }

  renderNavigation() {
    const pages = this.visibleWorkspacePages();
    return `<aside class="workspace-sidebar" ${this._dialog || this._confirmation ? "inert" : ""}>
      <nav aria-label="Bridge sections">${["Tater assistant", "Your home", "Voice & wake", "Maintenance"].map((group) => `
        <div class="workspace-nav-group"><span class="workspace-eyebrow">${group}</span>
          ${pages.filter((page) => page.group === group).map((page) => `
            <button type="button" class="workspace-nav-item" data-tab="${page.id}" ${this._tab === page.id ? 'aria-current="page"' : ""}>
              ${this.renderIcon(page.icon)}<span>${page.label}</span>${this.pageHasDraft(page.id) ? '<span class="draft-dot" aria-label="Unsaved changes"></span>' : ""}
            </button>`).join("")}
        </div>`).join("")}</nav>
      <div class="workspace-sidebar-footer"><strong>${this.renderIcon("home-assistant")} Home Assistant</strong><span>Native Assist satellites</span><span>Local connection</span></div>
    </aside>`;
  }

  pageHasDraft(tab) {
    if (["assistant", "models", "home-control", "hydra"].includes(tab)) return this.isScopeDirty("tater");
    if (tab === "satellites") return [...this._dirtyScopes].some((scope) => scope.startsWith("device:"));
    if (tab === "defaults") return this.isScopeDirty("wake") || this.isScopeDirty("global");
    return this.isScopeDirty(tab === "audio" ? "stereo" : tab);
  }

  renderDraftFooter(scope, buttons) {
    return `<footer class="sticky-actions workspace-save-bar"><div><strong data-draft-status="${scope}">${this.isScopeDirty(scope) ? "Unsaved changes" : "Settings synchronized"}</strong><span>${scope === "device" ? "Applies to this satellite." : "Applies to the shared profile."}</span></div><div class="row-actions">${buttons}</div></footer>`;
  }

  renderDialog() {
    if (!this._dialog && !this._confirmation) return "";
    let title = "", content = "";
    if (this._confirmation) {
      title = this._confirmation.title;
      content = `<p class="muted">${escapeHtml(this._confirmation.message)}</p><div class="row-actions dialog-actions"><button type="button" data-action="close-dialog">Cancel</button><button type="button" class="primary" data-action="confirm-dialog">${escapeHtml(this._confirmation.label)}</button></div>`;
    } else if (["server", "pairing"].includes(this._dialog)) {
      const pairing = this._data?.pairing || {};
      title = this._dialog === "pairing" ? "Add a satellite" : "Server & pairing";
      content = `<p class="muted">Use this Home Assistant address in the satellite’s setup page. The firmware adds the connection path automatically.</p>
        <div class="workspace-server">${escapeHtml(this._data?.server_address || "Unavailable")}</div>
        <div class="row-actions"><button type="button" data-copy-trainer-url="${escapeHtml(this._data?.server_address || "")}">Copy address</button></div>
        ${this._loading ? '<p class="muted" role="status">Generating pairing code…</p>' : pairing.active ? `
          <span class="workspace-eyebrow">Pairing code</span><div class="pair-code" aria-label="Pairing code">${escapeHtml(pairing.code)}</div>
          <button type="button" data-copy-pairing-code="${escapeHtml(pairing.code)}">Copy code</button>
          <ol class="trainer-steps"><li>Put the satellite into setup mode.</li><li>Enter the Home Assistant address and this pairing code.</li><li>Save and let the satellite reconnect.</li></ol>
        ` : '<button type="button" class="primary" data-action="pair">Generate pairing code</button>'}
        <details><summary>Connection details</summary><div class="workspace-server">${escapeHtml(this._data?.websocket_path || "/api/tater/satellite/v1/ws")}</div></details>`;
    } else if (this._dialog === "stereo") {
      title = "Create stereo pair";
      content = this.renderStereoPairEditor();
    } else if (this._dialog === "groups") {
      title = "Multi-room playback";
      content = `<ol class="trainer-steps"><li>Choose a Home Assistant media player as the group leader.</li><li>Use Join media players to add satellites or saved stereo pairs.</li><li>Use Unjoin media player to return a player to independent playback.</li></ol><p class="muted">Saved pairs retain left/right routing. Standalone satellites play mono in the group. Music Assistant can also discover compatible devices as Sendspin players.</p>`;
    } else if (this._dialog === "picker") {
      const field = (this._data?.settings_schema || []).flatMap((section) => section.fields || []).find((row) => row.key === this._picker?.key);
      if (!field) return "";
      const scope = this._picker.scope;
      const values = { wake: this._wakeDraft, global: this._globalDraft, device: this._deviceDraft }[scope] || {};
      title = `Choose ${field.label.toLowerCase()}`;
      content = `<p class="muted">Choose an option, then save settings to apply it.</p><input type="search" data-picker-search data-dialog-initial aria-label="Find ${escapeHtml(field.label.toLowerCase())}" placeholder="Find an option" value="${escapeHtml(this._pickerQuery)}">${this.renderField(field, values, scope, true)}<p class="muted" data-picker-empty hidden>No matching options. Try another search or refresh the bridge.</p>`;
    }
    return `<div class="workspace-dialog-backdrop" data-dialog-backdrop><section class="workspace-dialog" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}"><header><h2>${escapeHtml(title)}</h2><button type="button" data-action="close-dialog" ${this._dialog === "picker" && !this._confirmation ? "" : "data-dialog-initial"} aria-label="Close dialog">${this.renderIcon("close")}</button></header>${this._error ? `<div class="banner error" role="alert">${escapeHtml(this._error)}</div>` : ""}${content}</section></div>`;
  }

  workspaceStyles() {
    return `
      :host {
        color-scheme: light dark;
        --workspace-bg: light-dark(#f5f3ef, #111213);
        --workspace-nav: light-dark(#eeece7, #171819);
        --workspace-panel: light-dark(#ffffff, #1b1c1e);
        --workspace-field: light-dark(#f7f6f3, #222426);
        --workspace-text: light-dark(#292622, #f1eee8);
        --workspace-muted: light-dark(#6d665d, #b0a79c);
        --workspace-line: light-dark(#ddd8d0, #343536);
        --workspace-action: light-dark(#b94b1a, #e87b40);
        --workspace-action-text: light-dark(#ffffff, #211207);
        --workspace-good: light-dark(#277348, #82c9a0);
        --tater-accent: light-dark(#ae4316, #ee8954);
        --tater-accent-soft: light-dark(#f5e7de, #34271f);
        --primary-text-color: var(--workspace-text);
        --secondary-text-color: var(--workspace-muted);
        --primary-background-color: var(--workspace-bg);
        --secondary-background-color: var(--workspace-field);
        --card-background-color: var(--workspace-panel);
        --divider-color: var(--workspace-line);
        --input-fill-color: var(--workspace-field);
        --error-color: light-dark(#ae3434, #f0a09b);
        background: var(--workspace-bg); color: var(--workspace-text);
        font: 400 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      [hidden] { display: none !important; }
      ha-icon { --mdc-icon-size: 18px; width: 18px; height: 18px; flex: none; vertical-align: middle; }
      button, input, select, textarea, .field, .card { min-width: 0; }
      :is(h1, h2, h3, p) { margin: 0; overflow-wrap: anywhere; }
      :is(h1, h2, h3, strong, b) { font-weight: 500; }
      h1 { font-size: 25px; letter-spacing: -.6px; }
      h2 { font-size: 20px; }
      h3 { font-size: 16px; }
      button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 35px; padding: 7px 11px; border-radius: 8px; font-size: 12px; font-weight: 500; }
      button:hover:not(:disabled) { background: var(--workspace-field); border-color: var(--workspace-line); }
      button.primary, .firmware-hosted-flasher-link { background: var(--workspace-action); color: var(--workspace-action-text); border-color: transparent; }
      button.primary:hover:not(:disabled), .firmware-hosted-flasher-link:hover { background: color-mix(in srgb, var(--workspace-action) 88%, var(--workspace-text)); filter: none; }
      button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid var(--tater-accent); outline-offset: 3px; }
      input, select, textarea { min-height: 38px; padding: 9px 10px; border: 1px solid var(--workspace-line); border-radius: 7px; background: var(--workspace-field); color: var(--workspace-text); font: inherit; font-size: 13px; }
      textarea { width: 100%; resize: vertical; line-height: 1.5; }
      input[type=checkbox], input[type=radio] { accent-color: var(--tater-accent); }
      .bridge-workspace { container: tater-bridge / inline-size; min-height: 100vh; }
      .workspace-topbar { display: flex; align-items: center; flex-wrap: wrap; gap: 13px; min-height: 68px; padding: 16px 24px; border-bottom: 1px solid var(--workspace-line); background: var(--workspace-nav); font-size: 13px; }
      .workspace-brand { color: var(--tater-accent); font: 500 25px/1 "Marker Felt", "Segoe Print", "Trebuchet MS", sans-serif; }
      .workspace-connection { display: flex; align-items: center; gap: 7px; margin-left: auto; color: var(--workspace-muted); font-size: 11px; }
      .workspace-shell { display: grid; grid-template-columns: 190px minmax(0, 1fr); align-items: start; }
      .workspace-sidebar { position: sticky; top: 0; min-height: calc(100vh - 68px); padding: 24px 12px; border-right: 1px solid var(--workspace-line); background: var(--workspace-nav); }
      .workspace-nav-group { display: grid; gap: 4px; margin-bottom: 24px; }
      .workspace-eyebrow { display: block; color: var(--workspace-muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
      .workspace-nav-group > .workspace-eyebrow { margin: 0 9px 6px; }
      .workspace-nav-item { justify-content: flex-start; padding: 9px; gap: 10px; background: transparent; border-color: transparent; color: var(--workspace-muted); text-align: left; }
      .workspace-nav-item[aria-current] { color: var(--tater-accent); background: var(--tater-accent-soft); border-color: color-mix(in srgb, var(--tater-accent) 24%, transparent); }
      .draft-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--tater-accent); margin-left: auto; flex: none; }
      .workspace-sidebar-footer { display: grid; gap: 3px; padding-top: 16px; margin: 28px 9px 0; border-top: 1px solid var(--workspace-line); color: var(--workspace-muted); font-size: 11px; }
      .workspace-sidebar-footer strong { color: var(--workspace-text); margin-bottom: 3px; }
      .workspace-sidebar-footer ha-icon { width: 16px; height: 16px; --mdc-icon-size: 16px; margin-right: 4px; }
      main.workspace-main { max-width: none; min-width: 0; width: 100%; margin: 0; padding: 24px 24px 90px; }
      .topbar { gap: 16px; flex-wrap: wrap; margin-bottom: 25px; }
      .topbar h1 { margin: 3px 0 5px; }
      .topbar p { color: var(--workspace-muted); max-width: 560px; font-size: 12px; }
      .top-actions, .row-actions { gap: 7px; align-items: center; }
      .workspace-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 6px; }
      .workspace-summary { display: flex; align-items: center; gap: 13px; flex-wrap: wrap; color: var(--workspace-muted); font-size: 12px; }
      .connection-status { display: inline-flex; align-items: center; gap: 6px; color: var(--workspace-muted); font-size: 11px; white-space: nowrap; }
      .connection-status i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
      .connection-status.online { color: var(--workspace-good); }
      .workspace-filters { display: flex; gap: 8px; flex-wrap: wrap; }
      .workspace-filters input { width: 170px; }
      .workspace-filters select { width: auto; max-width: 210px; }
      .workspace-device-list { display: grid; }
      .workspace-device-row { display: grid; grid-template-columns: 37px minmax(0, 1fr) auto; gap: 13px; align-items: start; padding: 23px 0; border-bottom: 1px solid var(--workspace-line); }
      .workspace-device-icon { display: grid; place-items: center; height: 43px; width: 37px; border: 1px solid var(--workspace-line); border-radius: 11px; background: var(--workspace-panel); color: var(--workspace-muted); }
      .workspace-device-icon ha-icon { --mdc-icon-size: 20px; width: 20px; height: 20px; }
      .workspace-device-copy { min-width: 0; }
      .workspace-device-name { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0 0 4px; }
      .workspace-device-name h2 { font-size: 14px; margin: 0; }
      .workspace-device-meta { font-size: 11px; color: var(--workspace-muted); margin-bottom: 3px; overflow-wrap: anywhere; }
      .workspace-device-actions { display: grid; justify-items: end; gap: 10px; }
      .secondary-actions button { min-height: 24px; border: 0; padding: 1px 3px; color: var(--workspace-muted); background: transparent; font-size: 11px; }
      .secondary-actions button.danger { color: var(--error-color); }
      .workspace-device-progress { grid-column: 2 / -1; font-size: 11px; }
      .workspace-device-row .device-volume { max-width: 340px; padding: 0; margin: 12px 0 0; border: 0; border-radius: 0; background: transparent; }
      .workspace-device-row .device-volume-icon { display: none; }
      .workspace-device-row .device-volume-head strong, .workspace-device-row .device-volume-head output { font-size: 11px; font-weight: 400; color: var(--workspace-muted); }
      .workspace-device-row .device-volume-range { grid-template-columns: minmax(0, 1fr); }
      .workspace-device-row .device-volume-range > span { display: none; }
      .workspace-filter-empty { padding: 24px 0; }
      .workspace-profile-strip { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 18px 0; margin-top: 25px; border-top: 1px solid var(--workspace-line); border-bottom: 1px solid var(--workspace-line); font-size: 12px; }
      .workspace-profile-strip strong, .workspace-profile-strip span { display: block; }
      .workspace-profile-strip span { font-size: 11px; margin-top: 3px; }
      .workspace-section-nav { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 22px; }
      .workspace-section-nav button { color: var(--workspace-muted); }
      .workspace-section-nav button[aria-current] { background: var(--tater-accent-soft); border-color: var(--tater-accent); color: var(--tater-accent); }
      .workspace-back { margin-bottom: 18px; padding-left: 0; border-color: transparent; background: transparent; color: var(--workspace-muted); }
      .workspace-editor-head h2 { font-size: 23px; letter-spacing: -.4px; margin: 3px 0 5px; }
      .workspace-editor-head p { font-size: 12px; }
      .card { border-radius: 11px; padding: 20px; box-shadow: none; overflow-wrap: anywhere; }
      .card > h2, .card > h3 { margin-bottom: 6px; }
      .card > p, .section-description { color: var(--workspace-muted); font-size: 12px; }
      .section-card { margin-bottom: 20px; }
      .grid { grid-template-columns: repeat(auto-fit, minmax(min(290px, 100%), 1fr)); margin-bottom: 20px; }
      .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 22px; margin: 20px 0; font-size: 13px; }
      .fact { min-width: 0; }
      .fact label { font-weight: 400; text-transform: none; letter-spacing: 0; }
      .fact span { margin-top: 4px; }
      .badge { border-radius: 5px; padding: 3px 6px; font-size: 11px; }
      .badge.online { color: var(--workspace-good); background: color-mix(in srgb, var(--workspace-good) 12%, var(--workspace-panel)); }
      .badge.fail-open { color: var(--tater-accent); background: var(--tater-accent-soft); }
      .settings-grid { grid-template-columns: repeat(auto-fit, minmax(min(230px, 100%), 1fr)); gap: 17px; }
      .field > span, .percentage-range-head span { font-weight: 500; font-size: 12px; }
      .field > small, .section-description, .wake-tuning-card small { font-size: 11px; line-height: 1.55; }
      .toggle-field { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; background: var(--workspace-field); border-radius: 8px; font-size: 12px; }
      .toggle-field input { width: 17px; height: 17px; min-height: 17px; flex: none; }
      .asset-row { grid-template-columns: minmax(0, 1fr) auto; }
      .workspace-selection { grid-column: 1 / -1; }
      .workspace-selection-row { display: flex; align-items: center; justify-content: space-between; gap: 13px; padding: 13px 0; border-top: 1px solid var(--workspace-line); border-bottom: 1px solid var(--workspace-line); }
      .workspace-selection-row strong { min-width: 0; overflow-wrap: anywhere; }
      .workspace-selection-row button { flex: none; }
      .wake-mode-option { grid-template-columns: 32px minmax(0, 1fr) 12px; padding: 12px; border-radius: 9px; font-size: 12px; font-weight: 500; }
      .wake-mode-option i { width: 32px; height: 32px; border-radius: 8px; font-weight: 500; }
      .wake-mode-option.active { background: var(--tater-accent-soft); box-shadow: none; }
      .wake-tuning-card { border-radius: 9px; }
      .wake-tuning-title { flex-wrap: wrap; }
      .wake-tuning-switch { font-weight: 500; }
      .wake-boundary-card { grid-template-columns: 34px minmax(0, 1fr); }
      .wake-boundary-card > .badge { grid-column: 2; justify-self: start; }
      .device-volume { background: var(--workspace-field); border-color: var(--workspace-line); border-radius: 9px; padding: 13px; }
      .device-volume-icon { background: var(--workspace-panel); border-color: var(--workspace-line); }
      .device-volume-range { grid-template-columns: auto minmax(0, 1fr) auto; }
      .device-volume-head output, .percentage-range-head output { font-weight: 500; }
      .sticky-actions.workspace-save-bar { bottom: 0; border: 0; border-top: 1px solid var(--workspace-line); border-radius: 0; padding: 17px 0; margin-top: 24px; background: var(--workspace-bg); backdrop-filter: none; justify-content: space-between; align-items: center; flex-wrap: wrap; }
      .workspace-save-bar > div:first-child { min-width: 0; }
      .workspace-save-bar strong, .workspace-save-bar span { display: block; font-size: 12px; }
      .workspace-save-bar span { font-size: 11px; margin-top: 3px; color: var(--workspace-muted); }
      .workspace-section-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin: 0 0 20px; }
      .workspace-section-heading h2 { font-size: 18px; margin-bottom: 5px; }
      .workspace-section-heading p { font-size: 12px; }
      .workspace-wide { grid-column: 1 / -1; }
      .assistant-mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
      .assistant-mode-card { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 13px; padding: 18px; text-align: left; background: var(--workspace-panel); }
      .assistant-mode-card > span:nth-child(2) { display: grid; gap: 4px; }
      .assistant-mode-card strong { font-size: 17px; }
      .assistant-mode-card small { color: var(--workspace-muted); line-height: 1.45; font-weight: 400; }
      .assistant-mode-card > b, .home-scope-card > b { color: var(--workspace-muted); font-size: 11px; font-weight: 500; }
      .assistant-mode-card.active, .home-scope-card.active { border-color: var(--tater-accent); background: var(--tater-accent-soft); box-shadow: inset 0 0 0 1px var(--tater-accent); }
      .assistant-mode-card.active > b, .home-scope-card.active > b { color: var(--tater-accent); }
      .assistant-mode-icon { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid var(--workspace-line); border-radius: 11px; background: var(--workspace-field); color: var(--workspace-muted); }
      .assistant-mode-icon.tater { color: var(--workspace-action-text); background: var(--tater-accent); border-color: var(--tater-accent); font: 600 20px/1 "Marker Felt", "Segoe Print", sans-serif; }
      .assistant-flow-card, .assistant-test-card, .provider-card, .home-tool-card { margin-bottom: 16px; }
      .assistant-flow { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr auto 1fr; gap: 10px; align-items: center; }
      .assistant-flow > span { display: grid; justify-items: center; gap: 8px; min-height: 84px; padding: 15px 8px; border: 1px solid var(--workspace-line); border-radius: 9px; background: var(--workspace-field); font-size: 12px; text-align: center; }
      .assistant-flow > span ha-icon { color: var(--tater-accent); }
      .assistant-flow > i { color: var(--workspace-muted); font-style: normal; }
      .assistant-test-thread { display: grid; gap: 9px; max-height: 340px; overflow: auto; margin-bottom: 13px; }
      .assistant-test-message { max-width: 82%; padding: 11px 13px; border: 1px solid var(--workspace-line); border-radius: 10px; background: var(--workspace-field); }
      .assistant-test-message.user { justify-self: end; background: var(--tater-accent-soft); border-color: color-mix(in srgb, var(--tater-accent) 35%, var(--workspace-line)); }
      .assistant-test-message span { color: var(--workspace-muted); font-size: 10px; text-transform: uppercase; letter-spacing: .07em; }
      .assistant-test-message p { margin: 4px 0 0; font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
      .assistant-test-compose { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 9px; }
      .provider-status { display: inline-flex; align-items: center; gap: 6px; color: var(--workspace-muted); font-size: 11px; }
      .provider-status ha-icon { --mdc-icon-size: 17px; width: 17px; height: 17px; }
      .provider-choice { display: inline-flex; gap: 4px; margin-bottom: 16px; padding: 4px; border: 1px solid var(--workspace-line); border-radius: 9px; background: var(--workspace-field); }
      .provider-choice button { min-height: 30px; border-color: transparent; background: transparent; color: var(--workspace-muted); }
      .provider-choice button[aria-current] { background: var(--workspace-panel); border-color: var(--workspace-line); color: var(--tater-accent); }
      .home-scope-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
      .home-scope-card { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 12px; align-items: start; padding: 17px; text-align: left; background: var(--workspace-field); }
      .home-scope-card > span { grid-row: 1 / span 2; color: var(--tater-accent); }
      .home-scope-card > strong { font-size: 14px; }
      .home-scope-card > small { color: var(--workspace-muted); line-height: 1.45; font-weight: 400; }
      .home-scope-card > b { grid-column: 3; grid-row: 1 / span 2; }
      .home-scope-note { display: flex; gap: 9px; align-items: flex-start; margin-top: 14px; padding: 12px; border-radius: 8px; background: var(--workspace-field); color: var(--workspace-muted); font-size: 11px; line-height: 1.5; }
      .home-scope-note ha-icon { flex: none; color: var(--workspace-good); --mdc-icon-size: 18px; width: 18px; height: 18px; }
      .entity-preview-list { display: grid; }
      .entity-preview-list > div { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 11px; align-items: center; padding: 11px 0; border-top: 1px solid var(--workspace-line); }
      .entity-preview-list > div > span { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 8px; background: var(--workspace-field); color: var(--workspace-muted); }
      .entity-preview-list p, .entity-preview-list strong, .entity-preview-list small { display: block; margin: 0; }
      .entity-preview-list small { margin-top: 2px; color: var(--workspace-muted); font-size: 10px; }
      .entity-preview-list > div > b { color: var(--workspace-muted); font-size: 11px; font-weight: 500; }
      .hydra-toggle-list { display: grid; gap: 10px; margin-top: 18px; }
      .hydra-toggle-list .toggle-field { padding: 14px; }
      .hydra-toggle-list .toggle-field span { display: grid; gap: 3px; }
      .hydra-toggle-list .toggle-field small { color: var(--workspace-muted); font-weight: 400; line-height: 1.45; }
      .hydra-metrics-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
      .hydra-metrics-grid > div { display: grid; gap: 5px; padding: 15px; border: 1px solid var(--workspace-line); border-radius: 9px; background: var(--workspace-panel); }
      .hydra-metrics-grid span { color: var(--workspace-muted); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
      .hydra-metrics-grid strong { font-size: 23px; font-weight: 500; }
      .hydra-ledger, .conversation-data-list { display: grid; gap: 9px; }
      .hydra-ledger details, .conversation-data-list > div { border: 1px solid var(--workspace-line); border-radius: 9px; background: var(--workspace-field); }
      .hydra-ledger summary { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 13px; cursor: pointer; }
      .hydra-ledger summary > span { color: var(--workspace-good); font-size: 10px; text-transform: uppercase; }
      .hydra-ledger summary > strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
      .hydra-ledger summary > b { color: var(--workspace-muted); font-size: 10px; font-weight: 500; }
      .hydra-ledger details > dl, .hydra-ledger details > section { margin: 0 13px 13px; padding-top: 12px; border-top: 1px solid var(--workspace-line); }
      .hydra-ledger dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 12px; font-size: 11px; }
      .hydra-ledger dt { color: var(--workspace-muted); }
      .hydra-ledger dd { margin: 0; overflow-wrap: anywhere; }
      .hydra-ledger section > .badge { margin-left: 8px; }
      .hydra-ledger section > p { margin: 8px 0; color: var(--workspace-muted); font-size: 11px; }
      .hydra-ledger pre { max-height: 260px; overflow: auto; white-space: pre-wrap; }
      .conversation-data-list > div { padding: 13px; }
      .conversation-data-list span { color: var(--tater-accent); font-size: 10px; text-transform: uppercase; }
      .conversation-data-list p { margin: 6px 0; white-space: pre-wrap; font-size: 12px; }
      .conversation-data-list small { color: var(--workspace-muted); }
      .trainer-hero::after, .device-card::before { display: none; }
      .trainer-mark, .bluetooth-mark { background: var(--tater-accent-soft); color: var(--tater-accent); border-radius: 10px; font-weight: 500; font-size: 18px; width: 40px; height: 40px; }
      .trainer-head h2, .bluetooth-hero h2 { font-size: 18px; }
      .trainer-head .muted, .bluetooth-hero .muted, .editor-head .muted { font-size: 12px; }
      .bluetooth-hero { background: var(--workspace-panel); }
      .bluetooth-pair-grid { grid-template-columns: minmax(0, 1fr) minmax(0, .8fr) auto; }
      .bluetooth-paired-row { gap: 12px; flex-wrap: wrap; }
      .verifier-note { background: var(--workspace-field); border-color: var(--workspace-line); border-radius: 8px; font-size: 12px; }
      .percentage-range-field { padding: 15px; border-radius: 9px; border-color: var(--workspace-line); background: var(--workspace-field); }
      .percentage-range-head output { background: transparent; padding: 0; min-width: auto; }
      .percentage-range-field input[type=range] { border: 0; padding: 0; min-height: 24px; background: transparent; }
      .percentage-range-footer { flex-wrap: wrap; }
      .firmware-hosted-flasher { border-color: var(--workspace-line); background: var(--workspace-field); }
      .firmware-hosted-flasher-link { border-radius: 8px; font-size: 12px; font-weight: 500; }
      .firmware-mode-icon, .firmware-recovery-step-head b { font-weight: 500; }
      .banner { margin: 0 0 20px; border: 1px solid var(--workspace-line); border-radius: 8px; font-size: 12px; }
      .banner.success { background: color-mix(in srgb, var(--workspace-good) 9%, var(--workspace-panel)); color: var(--workspace-good); }
      .banner.error { color: var(--error-color); }
      details { font-size: 12px; }
      summary { font-weight: 500; }
      pre { font-size: 11px; border: 1px solid var(--workspace-line); color: var(--workspace-text); border-radius: 8px; }
      .workspace-loading { display: grid; justify-items: center; gap: 10px; padding: 38px 15px; font-size: 13px; }
      .workspace-loading .spinner { margin: 0 0 10px; }
      .workspace-dialog-backdrop { position: fixed; inset: 0; z-index: 1000; display: flex; justify-content: center; align-items: flex-start; padding: 7vh 18px 20px; background: rgb(5 8 13 / 72%); backdrop-filter: blur(5px); overflow-y: auto; overscroll-behavior: contain; }
      .workspace-dialog { width: min(640px, 100%); max-height: 86dvh; overflow-y: auto; padding: 23px; border: 1px solid var(--workspace-line); border-radius: 13px; background: var(--workspace-panel); box-shadow: 0 25px 70px rgb(0 0 0 / 25%); overscroll-behavior: contain; }
      .workspace-dialog > header { display: flex; justify-content: space-between; align-items: center; gap: 15px; margin-bottom: 20px; }
      .workspace-dialog > header h2 { font-size: 20px; }
      .workspace-dialog p { font-size: 13px; margin-bottom: 16px; }
      .workspace-dialog .row-actions { margin: 16px 0; }
      .workspace-dialog .section-card { padding: 0; border: 0; margin: 0; background: transparent; }
      .workspace-dialog .section-card > h3 { display: none; }
      .workspace-dialog .pair-code { font-size: clamp(28px, 6vw, 40px); font-weight: 500; margin: 12px 0; white-space: normal; }
      .workspace-dialog .workspace-eyebrow { margin-top: 22px; }
      .workspace-server { font: 12px/1.7 ui-monospace, SFMono-Regular, monospace; padding: 12px; border: 1px solid var(--workspace-line); border-radius: 7px; background: var(--workspace-field); overflow-wrap: anywhere; }
      .workspace-picker-options { display: grid; gap: 7px; margin-top: 16px; }
      .workspace-picker-option { display: flex; gap: 11px; align-items: center; padding: 12px; border: 1px solid var(--workspace-line); border-radius: 8px; cursor: pointer; font-size: 13px; }
      .workspace-picker-option:has(input:checked) { background: var(--tater-accent-soft); border-color: var(--tater-accent); }
      .workspace-picker-option input { width: 16px; min-height: 16px; height: 16px; margin: 0; padding: 0; flex: none; }
      .workspace-picker-option span { min-width: 0; overflow-wrap: anywhere; }
      .workspace-picker-option:has(input:disabled) { opacity: .55; cursor: not-allowed; }
      @container tater-bridge (max-width: 850px) {
        .workspace-shell { grid-template-columns: 158px minmax(0, 1fr); }
        .workspace-sidebar { padding-inline: 8px; }
        main.workspace-main { padding-inline: 18px; }
        .workspace-device-row { grid-template-columns: 34px minmax(0, 1fr); gap: 11px; }
        .workspace-device-actions { grid-column: 2; justify-items: start; display: flex; align-items: center; flex-wrap: wrap; }
        .workspace-device-actions > .connection-status { margin-right: auto; }
        .workspace-device-copy .device-volume { max-width: none; }
        .workspace-filters { width: 100%; }
        .workspace-filters input { flex: 1; width: 150px; }
        .firmware-board, .bluetooth-hero, .bluetooth-pair-grid { grid-template-columns: 1fr; }
        .bluetooth-mark { display: none; }
      }
      @container tater-bridge (max-width: 620px) {
        .workspace-topbar { padding: 18px 15px; gap: 10px; }
        .workspace-connection { display: none; }
        .workspace-shell { grid-template-columns: minmax(0, 1fr); }
        .workspace-sidebar { position: static; min-height: 0; border-right: 0; border-bottom: 1px solid var(--workspace-line); padding: 12px; }
        .workspace-sidebar nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px; }
        .workspace-nav-group { display: contents; }
        .workspace-nav-group > .workspace-eyebrow, .workspace-sidebar-footer { display: none; }
        .workspace-nav-item { font-size: 11px; padding: 8px 6px; }
        main.workspace-main { padding: 18px 15px 90px; }
        .topbar { display: flex; }
        .topbar h1 { font-size: 23px; }
        .workspace-filters select { max-width: 145px; }
        .workspace-editor-head { flex-wrap: wrap; }
        .card { padding: 16px; }
        .facts { gap: 14px; }
        .firmware-hosted-flasher { flex-direction: column; align-items: stretch; }
        .firmware-hosted-flasher-link { text-align: center; }
        .firmware-mode-grid { grid-template-columns: 1fr; }
        .workspace-save-bar .row-actions { width: 100%; }
        .trainer-identity { gap: 10px; }
        .trainer-mark { display: none; }
        .workspace-section-nav button { font-size: 11px; padding: 7px 9px; }
        .assistant-mode-grid, .home-scope-grid { grid-template-columns: 1fr; }
        .assistant-flow { grid-template-columns: 1fr; }
        .assistant-flow > i { transform: rotate(90deg); justify-self: center; }
        .hydra-metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @container tater-bridge (max-width: 480px) {
        .wake-mode-grid, .wake-mode-grid.dual, .settings-grid, .wake-tuning-grid { grid-template-columns: minmax(0, 1fr); }
        .workspace-selection-row { flex-wrap: wrap; }
        .workspace-filters input { width: 120px; }
        .assistant-mode-card, .home-scope-card { grid-template-columns: auto minmax(0, 1fr); }
        .assistant-mode-card > b, .home-scope-card > b { grid-column: 2; grid-row: auto; }
        .assistant-test-compose { grid-template-columns: 1fr; }
        .hydra-metrics-grid { grid-template-columns: 1fr; }
      }
      @media (max-width: 500px) { .workspace-dialog-backdrop { padding: 18px 10px; } .workspace-dialog { padding: 17px; max-height: calc(100dvh - 36px); } .workspace-dialog .settings-grid { grid-template-columns: minmax(0, 1fr); } }
      @media (pointer: coarse) { button, .workspace-nav-item { min-height: 44px; } input:not([type=range]):not([type=checkbox]):not([type=radio]), select, textarea { min-height: 44px; font-size: 16px; } }
      @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
    `;
  }

  styles() {
    return `
      :host {
        display: block;
        color: var(--primary-text-color);
        background: var(--primary-background-color);
        min-height: 100vh;
        --tater-accent: ${ACCENT};
        --tater-accent-soft: color-mix(in srgb, ${ACCENT} 16%, transparent);
      }
      * { box-sizing: border-box; }
      main { max-width: 1220px; margin: 0 auto; padding: 24px 22px 80px; }
      h1, h2, h3, p { margin-top: 0; }
      h1 { margin-bottom: 5px; font-size: 28px; }
      h2 { margin-bottom: 8px; font-size: 21px; }
      h3 { margin-bottom: 7px; font-size: 16px; }
      .muted { color: var(--secondary-text-color); }
      .topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
      .top-actions, .row-actions, .tabs { display: flex; gap: 9px; flex-wrap: wrap; }
      button {
        appearance: none;
        border: 1px solid var(--divider-color);
        border-radius: 9px;
        padding: 9px 14px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font: inherit;
        font-weight: 600;
        cursor: pointer;
      }
      button:hover:not(:disabled) { border-color: var(--tater-accent); }
      button.primary { color: #fff; background: var(--tater-accent); border-color: var(--tater-accent); }
      button.danger { color: var(--error-color); }
      button:disabled { opacity: .48; cursor: not-allowed; }
      .tabs { margin: 25px 0 18px; border-bottom: 1px solid var(--divider-color); }
      .tab { border: 0; border-radius: 0; background: transparent; padding: 10px 15px 12px; color: var(--secondary-text-color); }
      .tab.active { color: var(--tater-accent); border-bottom: 3px solid var(--tater-accent); }
      .banner { margin: 16px 0; padding: 12px 14px; border-radius: 10px; }
      .banner.error { background: color-mix(in srgb, var(--error-color) 14%, transparent); color: var(--error-color); }
      .banner.success { background: color-mix(in srgb, #2eae67 15%, transparent); color: #20844c; }
      .card {
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 14px;
        padding: 18px;
        box-shadow: var(--ha-card-box-shadow, none);
      }
      .pair-card { display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: center; margin-top: 18px; }
      .server { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
      .pair-code { font-size: 30px; font-weight: 800; letter-spacing: .12em; color: var(--tater-accent); white-space: nowrap; }
      .trainer-hero { position: relative; overflow: hidden; }
      .trainer-hero::after {
        content: "";
        position: absolute;
        width: 190px;
        height: 190px;
        border-radius: 50%;
        right: -70px;
        top: -95px;
        background: var(--tater-accent-soft);
        pointer-events: none;
      }
      .trainer-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; position: relative; z-index: 1; }
      .trainer-identity { display: flex; align-items: center; gap: 13px; }
      .trainer-mark {
        width: 46px;
        height: 46px;
        display: grid;
        place-items: center;
        flex: 0 0 auto;
        border-radius: 13px;
        color: #fff;
        background: var(--tater-accent);
        font-size: 22px;
        font-weight: 850;
      }
      .trainer-status-grid { margin-top: 18px; }
      .trainer-code-card { border-color: color-mix(in srgb, var(--tater-accent) 48%, var(--divider-color)); }
      .trainer-code {
        margin: 12px 0;
        color: var(--tater-accent);
        font-size: clamp(30px, 7vw, 48px);
        font-weight: 850;
        letter-spacing: .14em;
      }
      .trainer-steps { margin: 14px 0 0; padding-left: 22px; color: var(--secondary-text-color); }
      .trainer-steps li { margin: 7px 0; padding-left: 4px; }
      .verifier-note {
        margin-top: 16px;
        padding: 12px 14px;
        border-radius: 10px;
        border: 1px solid color-mix(in srgb, #1cb8f2 38%, var(--divider-color));
        background: color-mix(in srgb, #1cb8f2 9%, transparent);
        color: var(--secondary-text-color);
      }
      .percentage-range-field {
        display: grid;
        gap: 9px;
        padding: 13px 14px;
        border: 1px solid color-mix(in srgb, var(--tater-accent) 34%, var(--divider-color));
        border-radius: 12px;
        background: color-mix(in srgb, var(--tater-accent-soft) 45%, var(--secondary-background-color));
      }
      .percentage-range-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
      .percentage-range-head span { font-size: 13px; font-weight: 700; }
      .percentage-range-head output {
        min-width: 58px;
        padding: 5px 9px;
        border-radius: 999px;
        color: var(--tater-accent);
        background: var(--tater-accent-soft);
        text-align: center;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
      }
      .percentage-range-field input[type="range"] { width: 100%; accent-color: var(--tater-accent); }
      .percentage-range-scale { display: flex; justify-content: space-between; gap: 12px; color: var(--secondary-text-color); font-size: 11px; }
      .percentage-range-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
      .percentage-range-footer small { color: var(--secondary-text-color); line-height: 1.4; }
      .percentage-range-footer button { flex: 0 0 auto; }
      .verifier-device.rejected { border-color: color-mix(in srgb, var(--error-color) 55%, var(--divider-color)); }
      .verifier-device.fail-open { border-color: color-mix(in srgb, #e5a323 55%, var(--divider-color)); }
      .badge.rejected { color: var(--error-color); background: color-mix(in srgb, var(--error-color) 14%, transparent); }
      .badge.fail-open { color: #b57800; background: color-mix(in srgb, #e5a323 16%, transparent); }
      .transcript {
        margin-top: 12px;
        padding: 10px 12px;
        border-radius: 9px;
        background: var(--secondary-background-color);
        font-style: italic;
        overflow-wrap: anywhere;
      }
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; }
      .device-card { position: relative; overflow: hidden; }
      .device-card::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--divider-color); }
      .device-card.online::before { background: var(--tater-accent); }
      .device-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
      .badges { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0 13px; }
      .badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 999px; background: var(--secondary-background-color); font-size: 12px; }
      .badge.online { color: #228b50; background: color-mix(in srgb, #2eae67 14%, transparent); }
      .badge.update { color: var(--tater-accent); background: var(--tater-accent-soft); }
      .bluetooth-hero {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 18px;
        align-items: center;
        overflow: hidden;
        background:
          radial-gradient(circle at 100% 0, var(--tater-accent-soft), transparent 42%),
          var(--card-background-color);
      }
      .bluetooth-mark {
        display: grid;
        place-items: center;
        width: 54px;
        height: 54px;
        border-radius: 16px;
        color: #fff;
        background: var(--tater-accent);
        font-size: 27px;
        font-weight: 800;
      }
      .bluetooth-proxies { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 13px; }
      .bluetooth-device { display: grid; gap: 13px; }
      .bluetooth-device-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
      .bluetooth-address { margin-top: 3px; font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--secondary-text-color); }
      .bluetooth-signal { color: var(--tater-accent); font-weight: 750; white-space: nowrap; }
      .bluetooth-pair-grid { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(120px, .65fr) auto; gap: 9px; align-items: end; }
      .bluetooth-paired-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
      .bluetooth-paired-copy { min-width: 0; }
      .facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; margin: 12px 0 16px; }
      .fact label { display: block; color: var(--secondary-text-color); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
      .fact span { display: block; margin-top: 2px; overflow-wrap: anywhere; }
      .section-card { margin-bottom: 14px; }
      .section-description { color: var(--secondary-text-color); margin-bottom: 15px; font-size: 14px; }
      .settings-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(245px, 1fr)); gap: 13px; }
      .wake-tuning { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--divider-color); }
      .wake-tuning-head { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; margin-bottom: 12px; }
      .wake-tuning-head h3 { margin: 0 0 4px; }
      .wake-boundary-card { display: grid; grid-template-columns: auto 1fr auto; gap: 11px; align-items: center; margin: 0 0 12px; padding: 12px 13px; border: 1px solid color-mix(in srgb, var(--tater-accent) 35%, var(--divider-color)); border-radius: 12px; background: color-mix(in srgb, var(--tater-accent-soft) 55%, var(--secondary-background-color)); }
      .wake-boundary-card.missing { border-color: var(--divider-color); background: var(--secondary-background-color); }
      .wake-boundary-card i { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--tater-accent-soft); color: var(--tater-accent); font-style: normal; font-weight: 850; }
      .wake-boundary-card span:not(.badge) { display: grid; gap: 2px; }
      .wake-boundary-card small { color: var(--secondary-text-color); line-height: 1.35; }
      .wake-tuning-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(225px, 1fr)); gap: 11px; }
      .wake-tuning-card { padding: 13px; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--secondary-background-color); }
      .wake-tuning-card.active { border-color: color-mix(in srgb, var(--tater-accent) 55%, var(--divider-color)); box-shadow: inset 0 0 0 1px var(--tater-accent-soft); }
      .wake-tuning-title { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 5px; }
      .wake-tuning-title strong { font-size: 14px; }
      .wake-tuning-card small { display: block; color: var(--secondary-text-color); line-height: 1.35; }
      .wake-tuning-switch { display: flex; gap: 10px; align-items: center; margin-top: 12px; font-size: 13px; font-weight: 650; }
      .wake-tuning-switch input { width: 18px; min-height: 18px; margin: 0; }
      .wake-tuning-inputs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin-top: 12px; }
      .wake-tuning-inputs .field span { font-size: 12px; }
      .wake-mode-picker { margin: 14px 0; }
      .wake-mode-label { margin: 11px 0 7px; color: var(--secondary-text-color); font-size: 11px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
      .wake-mode-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }
      .wake-mode-grid.dual { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .wake-mode-option { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; min-height: 62px; padding: 10px 12px; text-align: left; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--secondary-background-color); color: var(--primary-text-color); }
      .wake-mode-option i { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--tater-accent-soft); color: var(--tater-accent); font-style: normal; font-size: 12px; font-weight: 800; }
      .wake-mode-option span { display: grid; gap: 2px; }
      .wake-mode-option small { color: var(--secondary-text-color); font-size: 11px; }
      .wake-mode-option b { visibility: hidden; color: var(--tater-accent); }
      .wake-mode-option.active { border-color: var(--tater-accent); box-shadow: inset 0 0 0 1px var(--tater-accent); }
      .wake-mode-option.active b { visibility: visible; }
      @media (max-width: 640px) { .wake-mode-grid, .wake-mode-grid.dual { grid-template-columns: 1fr; } }
      .field { display: flex; flex-direction: column; gap: 6px; }
      .field > span { font-size: 13px; font-weight: 600; }
      .field > small { color: var(--secondary-text-color); line-height: 1.35; }
      input, select {
        width: 100%;
        min-height: 42px;
        border: 1px solid var(--divider-color);
        border-radius: 9px;
        background: var(--input-fill-color, var(--primary-background-color));
        color: var(--primary-text-color);
        padding: 8px 10px;
        font: inherit;
      }
      input[type="color"] { padding: 4px; }
      .device-volume {
        --device-volume-progress: 80%;
        display: flex;
        align-items: center;
        gap: 11px;
        margin: 14px 0 16px;
        padding: 11px 12px;
        border: 1px solid color-mix(in srgb, var(--tater-accent) 30%, var(--divider-color));
        border-radius: 12px;
        background:
          radial-gradient(circle at 0 50%, var(--tater-accent-soft), transparent 44%),
          var(--secondary-background-color);
      }
      .device-volume-icon {
        display: grid;
        place-items: center;
        flex: 0 0 37px;
        width: 37px;
        height: 37px;
        border: 1px solid color-mix(in srgb, var(--tater-accent) 38%, var(--divider-color));
        border-radius: 11px;
        color: var(--tater-accent);
        background: var(--tater-accent-soft);
      }
      .device-volume-icon svg { width: 21px; height: 21px; fill: currentColor; }
      .device-volume-main { display: grid; flex: 1 1 auto; gap: 7px; min-width: 0; }
      .device-volume-head { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
      .device-volume-head strong { font-size: 13px; }
      .device-volume-head output {
        min-width: 40px;
        color: var(--tater-accent);
        text-align: right;
        font-size: 13px;
        font-variant-numeric: tabular-nums;
        font-weight: 700;
      }
      .device-volume-feedback {
        flex: 1 1 auto;
        color: var(--secondary-text-color);
        text-align: right;
        font-size: 11px;
      }
      .device-volume-feedback.error { color: var(--error-color); }
      .device-volume-range {
        display: grid;
        grid-template-columns: auto minmax(90px, 1fr) auto;
        align-items: center;
        gap: 8px;
        color: var(--secondary-text-color);
        font-size: 10px;
        font-variant-numeric: tabular-nums;
      }
      .device-volume input[type="range"] {
        width: 100%;
        min-height: 18px;
        height: 18px;
        margin: 0;
        padding: 0;
        border: 0;
        outline: 0;
        border-radius: 0;
        appearance: none;
        -webkit-appearance: none;
        background: transparent;
        cursor: pointer;
      }
      .device-volume input[type="range"]::-webkit-slider-runnable-track {
        height: 6px;
        border-radius: 99px;
        background: linear-gradient(
          to right,
          var(--tater-accent) 0,
          var(--tater-accent) var(--device-volume-progress),
          color-mix(in srgb, var(--primary-text-color) 15%, transparent) var(--device-volume-progress),
          color-mix(in srgb, var(--primary-text-color) 15%, transparent) 100%
        );
      }
      .device-volume input[type="range"]::-moz-range-track {
        height: 6px;
        border-radius: 99px;
        background: color-mix(in srgb, var(--primary-text-color) 15%, transparent);
      }
      .device-volume input[type="range"]::-moz-range-progress {
        height: 6px;
        border-radius: 99px;
        background: var(--tater-accent);
      }
      .device-volume input[type="range"]::-webkit-slider-thumb {
        width: 18px;
        height: 18px;
        margin-top: -6px;
        border: 3px solid var(--tater-accent);
        border-radius: 50%;
        appearance: none;
        -webkit-appearance: none;
        background: var(--card-background-color);
        box-shadow: 0 2px 7px rgba(0, 0, 0, .28);
      }
      .device-volume input[type="range"]::-moz-range-thumb {
        width: 13px;
        height: 13px;
        border: 3px solid var(--tater-accent);
        border-radius: 50%;
        background: var(--card-background-color);
        box-shadow: 0 2px 7px rgba(0, 0, 0, .28);
      }
      .device-volume input[type="range"]:focus-visible::-webkit-slider-thumb {
        box-shadow: 0 0 0 4px var(--tater-accent-soft), 0 2px 7px rgba(0, 0, 0, .28);
      }
      .device-volume input[type="range"]:focus-visible::-moz-range-thumb {
        box-shadow: 0 0 0 4px var(--tater-accent-soft), 0 2px 7px rgba(0, 0, 0, .28);
      }
      .device-volume input[type="range"]:disabled { opacity: .55; cursor: wait; }
      .toggle-field { flex-direction: row; align-items: center; justify-content: space-between; min-height: 42px; padding: 8px 10px; border: 1px solid var(--divider-color); border-radius: 9px; }
      .toggle-field input { width: 42px; min-height: 22px; accent-color: var(--tater-accent); }
      .entity-list { display: grid; gap: 6px; max-height: 280px; overflow-y: auto; }
      .asset-row { display: grid; grid-template-columns: 1fr auto; gap: 7px; }
      .editor-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 15px; }
      .sticky-actions { position: sticky; bottom: 12px; z-index: 3; margin-top: 15px; padding: 12px; display: flex; justify-content: flex-end; gap: 9px; background: color-mix(in srgb, var(--card-background-color) 92%, transparent); backdrop-filter: blur(8px); border: 1px solid var(--divider-color); border-radius: 12px; }
      .firmware-board { display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center; }
      .firmware-recovery-grid { display: grid; gap: 15px; margin-top: 16px; }
      .firmware-recovery-step { display: grid; gap: 8px; }
      .firmware-recovery-step-head { display: flex; align-items: center; gap: 8px; }
      .firmware-recovery-step-head b {
        display: inline-grid;
        place-items: center;
        min-width: 28px;
        height: 28px;
        border-radius: 8px;
        color: var(--tater-accent);
        background: var(--tater-accent-soft);
        font-size: 12px;
      }
      .firmware-mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
      .firmware-mode-option {
        display: grid;
        grid-template-columns: 34px minmax(0, 1fr);
        gap: 10px;
        align-items: start;
        padding: 12px;
        text-align: left;
      }
      .firmware-mode-option.active {
        border-color: var(--tater-accent);
        background: var(--tater-accent-soft);
      }
      .firmware-mode-icon {
        display: grid;
        place-items: center;
        width: 32px;
        height: 32px;
        border-radius: 9px;
        color: var(--tater-accent);
        background: color-mix(in srgb, var(--tater-accent) 14%, var(--card-background-color));
        font-weight: 800;
      }
      .firmware-mode-copy { display: grid; gap: 4px; min-width: 0; }
      .firmware-mode-copy strong { font-size: 14px; }
      .firmware-mode-copy small { color: var(--secondary-text-color); line-height: 1.35; }
      .firmware-installer-ready {
        margin-top: 16px;
        padding: 14px;
        border: 1px solid color-mix(in srgb, var(--tater-accent) 42%, var(--divider-color));
        border-radius: 11px;
        background: var(--tater-accent-soft);
      }
      .firmware-hosted-flasher {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        margin-top: 14px;
        padding: 13px 14px;
        border: 1px solid color-mix(in srgb, var(--tater-accent) 38%, var(--divider-color));
        border-radius: 11px;
        background: var(--tater-accent-soft);
      }
      .firmware-hosted-flasher-copy { display: grid; gap: 4px; min-width: 0; }
      .firmware-hosted-flasher-copy small { color: var(--secondary-text-color); line-height: 1.4; }
      .firmware-hosted-flasher-link {
        flex: 0 0 auto;
        padding: 9px 14px;
        border: 1px solid var(--tater-accent);
        border-radius: 9px;
        color: #fff;
        background: var(--tater-accent);
        font-weight: 650;
        text-decoration: none;
      }
      .firmware-hosted-flasher-link:hover { filter: brightness(1.06); }
      .progress { height: 7px; border-radius: 99px; overflow: hidden; background: var(--secondary-background-color); margin-top: 10px; }
      .progress > span { display: block; height: 100%; background: var(--tater-accent); }
      details { margin-top: 12px; }
      summary { cursor: pointer; font-weight: 600; }
      pre {
        margin: 10px 0 0;
        max-height: 260px;
        overflow: auto;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        padding: 12px;
        border-radius: 9px;
        background: var(--secondary-background-color);
        color: var(--secondary-text-color);
        font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
      }
      .empty { text-align: center; padding: 42px 18px; }
      .spinner { width: 34px; height: 34px; border-radius: 50%; border: 4px solid var(--divider-color); border-top-color: var(--tater-accent); animation: spin 1s linear infinite; margin: 40px auto; }
      @keyframes spin { to { transform: rotate(360deg); } }
      @media (max-width: 700px) {
        main { padding: 18px 12px 70px; }
        .topbar, .pair-card, .firmware-board { grid-template-columns: 1fr; display: grid; }
        .firmware-mode-grid { grid-template-columns: 1fr; }
        .firmware-hosted-flasher { align-items: stretch; flex-direction: column; }
        .firmware-hosted-flasher-link { text-align: center; }
        .bluetooth-hero, .bluetooth-pair-grid { grid-template-columns: 1fr; }
        .bluetooth-mark { display: none; }
        .bluetooth-paired-row { align-items: stretch; flex-direction: column; }
        .pair-code { font-size: 25px; }
        .facts { grid-template-columns: 1fr; }
      }
    `;
  }

  renderHeader() {
    const page = WORKSPACE_PAGES.find((row) => row.id === this._tab) || WORKSPACE_PAGES[0];
    return `
      <div class="topbar">
        <div>
          <span class="workspace-eyebrow">Home Assistant bridge</span>
          <h1>${page.label}</h1>
          <p class="muted">${page.description}</p>
        </div>
        <div class="top-actions">
          <button type="button" data-action="refresh" aria-label="Refresh bridge" ${this._loading ? "disabled" : ""}>${this.renderIcon("refresh")}</button>
          <button type="button" data-action="server" ${!this._data ? "disabled" : ""}>${this.renderIcon("link-variant")} Server & pairing</button>
          ${this._tab === "satellites" ? `<button type="button" class="primary" data-action="pair" ${this._loading ? "disabled" : ""}>${this.renderIcon("plus")} Add satellite</button>` : ""}
        </div>
      </div>
    `;
  }

  renderLoading() {
    return `<div class="workspace-loading" role="status"><div class="spinner"></div><strong>Connecting to your satellites</strong><span class="muted">Loading bridge settings and device status.</span></div>`;
  }

  renderBody() {
    return `
      ${this._tab === "assistant" ? this.renderAssistantChoice() : ""}
      ${this._tab === "models" ? this.renderModelsAndSpeech() : ""}
      ${this._tab === "home-control" ? this.renderHomeControl() : ""}
      ${this._tab === "hydra" ? this.renderHydra() : ""}
      ${this._tab === "defaults" ? this.renderVoiceDefaults() : ""}
      ${this._tab === "verifier" ? this.renderVerifier() : ""}
      ${this._tab === "trainer" ? this.renderTrainer() : ""}
      ${this._tab === "firmware" ? this.renderFirmware() : ""}
      ${this._tab === "audio" ? this.renderAudio() : ""}
      ${this._tab === "bluetooth" ? this.renderBluetooth() : ""}
      ${this._tab === "satellites" ? this.renderSatellites() : ""}
    `;
  }

  tabButton(key, label) {
    return `<button class="tab ${this._tab === key ? "active" : ""}" data-tab="${key}">${label}</button>`;
  }

  renderAssistantChoice() {
    const settings = this._taterDraft || {};
    const runtime = this._data.tater_assistant || {};
    const ready = runtime.ready || {};
    const mode = settings.assistant_mode || "home_assistant";
    const messages = (runtime.messages || []).slice(-6);
    return `
      <section class="assistant-mode-grid" aria-label="Conversation pipeline">
        <button type="button" class="assistant-mode-card ${mode === "home_assistant" ? "active" : ""}" data-assistant-mode="home_assistant">
          <span class="assistant-mode-icon">${this.renderIcon("home-assistant")}</span>
          <span><span class="workspace-eyebrow">Existing pipeline</span><strong>Home Assistant</strong><small>HA owns STT, the conversation agent, device tools, and TTS.</small></span>
          <b>${mode === "home_assistant" ? "Selected" : "Choose"}</b>
        </button>
        <button type="button" class="assistant-mode-card ${mode === "tater" ? "active" : ""}" data-assistant-mode="tater">
          <span class="assistant-mode-icon tater">T</span>
          <span><span class="workspace-eyebrow">Complete Tater pipeline</span><strong>Tater</strong><small>Tater owns speech, Hydra, home control, conversation memory, and playback.</small></span>
          <b>${mode === "tater" ? "Selected" : ready.ok ? "Choose" : "Setup needed"}</b>
        </button>
      </section>

      <section class="card assistant-flow-card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">${mode === "tater" ? "Tater mode" : "Home Assistant mode"}</span><h2>${mode === "tater" ? "A complete voice turn" : "Native Assist stays intact"}</h2><p class="muted">The selected pipeline applies to every connected Tater satellite.</p></div>
          <span class="badge ${mode === "tater" && !ready.ok ? "update" : "online"}">${mode === "tater" ? ready.ok ? "Ready" : "Setup needed" : "Ready"}</span>
        </div>
        <div class="assistant-flow">
          ${(mode === "tater"
            ? [["microphone", "Tater STT"], ["creation-outline", "Hydra"], ["home-automation", "Device control"], ["account-voice", "Tater TTS"]]
            : [["microphone", "HA STT"], ["message-processing-outline", "HA agent"], ["home-assistant", "HA tools"], ["account-voice", "HA TTS"]])
            .map(([icon, label], index) => `<span>${this.renderIcon(icon)}<b>${label}</b></span>${index < 3 ? '<i aria-hidden="true">→</i>' : ""}`).join("")}
        </div>
        ${mode === "tater" && !ready.ok ? `<div class="verifier-note"><strong>Finish Tater setup</strong><p>${escapeHtml((ready.missing || []).join(" · "))}</p><button type="button" data-tab="models">Open models & speech</button></div>` : ""}
      </section>

      <section class="card assistant-test-card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Text test</span><h2>Talk to mini Tater</h2><p class="muted">Verify the LLM, Hydra, and home-control tool before switching voice turns. No audio is recorded.</p></div></div>
        <div class="assistant-test-thread">${messages.length ? messages.map((message) => `<div class="assistant-test-message ${message.role === "assistant" ? "assistant" : "user"}"><span>${message.role === "assistant" ? escapeHtml(settings.assistant_name || "Tater") : "You"}</span><p>${escapeHtml(message.content || "")}</p></div>`).join("") : '<p class="muted">No test messages yet.</p>'}</div>
        <div class="assistant-test-compose"><input type="text" data-tater-test-message placeholder="Ask a question or control a device" value="${escapeHtml(this._testMessage)}" ${!ready.ok ? "disabled" : ""}><button type="button" class="primary" data-action="test-tater" ${!ready.ok || this._loading ? "disabled" : ""}>${this._loading ? "Working…" : "Send"}</button></div>
      </section>

      ${this.renderDraftFooter("tater", `<button type="button" data-action="reset-tater-draft">Discard</button><button type="button" class="primary" data-action="save-tater">Save assistant</button>`)}
    `;
  }

  taterField(key, label, options = {}) {
    const settings = this._taterDraft || {};
    const type = options.type || "text";
    const value = settings[key] ?? options.fallback ?? "";
    const saved = Boolean(settings[`${key}_set`]);
    const attributes = [
      options.min !== undefined ? `min="${options.min}"` : "",
      options.max !== undefined ? `max="${options.max}"` : "",
      options.step !== undefined ? `step="${options.step}"` : "",
      options.placeholder ? `placeholder="${escapeHtml(options.placeholder)}"` : "",
      options.autocomplete ? `autocomplete="${escapeHtml(options.autocomplete)}"` : "",
    ].filter(Boolean).join(" ");
    return `<label class="field"><span>${escapeHtml(label)}</span><input data-tater-setting="${escapeHtml(key)}" type="${escapeHtml(type)}" value="${type === "password" ? "" : escapeHtml(value)}" ${attributes}>${options.help ? `<small>${escapeHtml(options.help)}${type === "password" && saved ? " A key is saved." : ""}</small>` : type === "password" && saved ? '<small>A key is saved. Leave this blank to keep it.</small>' : ""}</label>`;
  }

  renderModelsAndSpeech() {
    const settings = this._taterDraft || {};
    const sttProvider = settings.stt_provider || "openai";
    const ttsProvider = settings.tts_provider || "openai";
    return `
      <section class="card provider-card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Hydra model</span><h2>Language model</h2><p class="muted">OpenAI or any compatible Chat Completions endpoint with function tools.</p></div><span class="provider-status">${settings.llm_api_key_set ? this.renderIcon("check-circle-outline") + " Key saved" : this.renderIcon("key-outline") + " Key not set"}</span></div>
        <div class="settings-grid">
          ${this.taterField("llm_base_url", "API base URL", { placeholder: "https://api.openai.com/v1" })}
          ${this.taterField("llm_model", "Model", { placeholder: "Enter a tool-capable model" })}
          ${this.taterField("llm_api_key", "API key", { type: "password", autocomplete: "new-password" })}
          ${this.taterField("llm_temperature", "Temperature", { type: "number", min: 0, max: 2, step: 0.1 })}
          ${this.taterField("assistant_name", "Assistant name", { placeholder: "Tater" })}
          <label class="field workspace-wide"><span>Personality</span><textarea data-tater-setting="personality" rows="4">${escapeHtml(settings.personality || "")}</textarea><small>Used for conversational style. Device permissions are always enforced separately.</small></label>
        </div>
      </section>

      <section class="card provider-card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Incoming speech</span><h2>Speech-to-text</h2><p class="muted">Tater sends satellite microphone audio directly to this provider.</p></div></div>
        <div class="provider-choice" role="group" aria-label="Speech-to-text provider"><button type="button" data-tater-provider="stt:openai" ${sttProvider === "openai" ? 'aria-current="true"' : ""}>OpenAI compatible</button><button type="button" data-tater-provider="stt:wyoming" ${sttProvider === "wyoming" ? 'aria-current="true"' : ""}>Wyoming</button></div>
        <div class="settings-grid">
          ${sttProvider === "openai" ? `
            ${this.taterField("stt_base_url", "STT API base URL", { placeholder: "https://api.openai.com/v1" })}
            ${this.taterField("stt_model", "Transcription model", { placeholder: "gpt-4o-transcribe" })}
            ${this.taterField("stt_api_key", "Separate STT key", { type: "password", autocomplete: "new-password", help: "Leave blank to use the LLM key." })}
            ${this.taterField("stt_language", "Language hint", { placeholder: "Optional, such as en" })}
          ` : `
            ${this.taterField("stt_wyoming_host", "Wyoming host", { placeholder: "192.168.1.50" })}
            ${this.taterField("stt_wyoming_port", "Wyoming port", { type: "number", min: 1, max: 65535 })}
            ${this.taterField("stt_wyoming_model", "Wyoming model name", { help: "Leave blank to use the Wyoming service default." })}
            ${this.taterField("stt_language", "Language hint", { placeholder: "Optional, such as en" })}
          `}
        </div>
      </section>

      <section class="card provider-card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Spoken reply</span><h2>Text-to-speech</h2><p class="muted">Tater creates the final audio and returns it to the originating satellite.</p></div></div>
        <div class="provider-choice" role="group" aria-label="Text-to-speech provider"><button type="button" data-tater-provider="tts:openai" ${ttsProvider === "openai" ? 'aria-current="true"' : ""}>OpenAI compatible</button><button type="button" data-tater-provider="tts:wyoming" ${ttsProvider === "wyoming" ? 'aria-current="true"' : ""}>Wyoming</button></div>
        <div class="settings-grid">
          ${ttsProvider === "openai" ? `
            ${this.taterField("tts_base_url", "TTS API base URL", { placeholder: "https://api.openai.com/v1" })}
            ${this.taterField("tts_model", "Speech model", { placeholder: "gpt-4o-tts" })}
            ${this.taterField("tts_voice", "Voice", { placeholder: "alloy" })}
            ${this.taterField("tts_api_key", "Separate TTS key", { type: "password", autocomplete: "new-password", help: "Leave blank to use the LLM key." })}
          ` : `
            ${this.taterField("tts_wyoming_host", "Wyoming host", { placeholder: "192.168.1.50" })}
            ${this.taterField("tts_wyoming_port", "Wyoming port", { type: "number", min: 1, max: 65535 })}
            ${this.taterField("tts_wyoming_voice", "Wyoming voice name", { help: "Leave blank to use the Wyoming service default." })}
          `}
        </div>
      </section>
      ${this.renderDraftFooter("tater", `<button type="button" data-action="reset-tater-draft">Discard</button><button type="button" class="primary" data-action="save-tater">Save models & speech</button>`)}
    `;
  }

  renderHomeControl() {
    const settings = this._taterDraft || {};
    const summary = this._data.tater_assistant?.home_control || {};
    const scope = settings.entity_scope || "exposed";
    const examples = summary.examples || [];
    return `
      <section class="card home-tool-card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">One built-in capability</span><h2>Home Assistant device control</h2><p class="muted">Hydra can read and control the home. Mini Tater includes no web, files, messaging, Cores, Portals, Shop, or downloadable Verbas.</p></div><span class="badge online">control_home</span></div>
        <div class="home-scope-grid">
          <button type="button" class="home-scope-card ${scope === "exposed" ? "active" : ""}" data-entity-scope="exposed"><span>${this.renderIcon("shield-home-outline")}</span><strong>Exposed to Assist</strong><small>Use the choices already managed in Home Assistant’s Voice Assistants settings.</small><b>${scope === "exposed" ? "Selected" : "Choose"}</b></button>
          <button type="button" class="home-scope-card ${scope === "all" ? "active" : ""}" data-entity-scope="all"><span>${this.renderIcon("home-group")}</span><strong>All HA entities</strong><small>Let Tater read supported sensors and control supported device domains.</small><b>${scope === "all" ? "Selected" : "Choose"}</b></button>
        </div>
        <div class="home-scope-note">${this.renderIcon("shield-check-outline")}<span>The selected scope is checked when Tater builds context, resolves a target, and immediately before every action. Entity names and states in this scope may be sent to the configured language model.</span></div>
      </section>
      <section class="card">
        <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Available now</span><h2>${Number(summary.entity_count || 0)} entities across ${Number(summary.areas || 0)} areas</h2><p class="muted">${escapeHtml((summary.domains || []).join(" · ") || "No entities are currently available in this scope.")}</p></div></div>
        <div class="entity-preview-list">${examples.length ? examples.map((row) => `<div><span>${this.renderIcon(row.domain === "light" ? "lightbulb-outline" : row.domain === "sensor" ? "gauge" : "devices")}</span><p><strong>${escapeHtml(row.name || row.entity_id)}</strong><small>${escapeHtml([row.area, row.entity_id].filter(Boolean).join(" · "))}</small></p><b>${escapeHtml(row.state || "unknown")}</b></div>`).join("") : '<p class="muted">Expose entities to Assist or select all entities to make device control available.</p>'}</div>
      </section>
      ${this.renderDraftFooter("tater", `<button type="button" data-action="reset-tater-draft">Discard</button><button type="button" class="primary" data-action="save-tater">Save home control</button>`)}
    `;
  }

  renderHydra() {
    const settings = this._taterDraft || {};
    const runtime = this._data.tater_assistant || {};
    const metrics = runtime.metrics || {};
    const ledger = runtime.ledger || [];
    const messages = runtime.messages || [];
    return `
      <nav class="workspace-section-nav" aria-label="Hydra sections">
        ${[["ledger", "Ledger"], ["behavior", "Behavior"], ["conversations", "Conversation data"]].map(([id, label]) => `<button type="button" data-hydra-section="${id}" ${this._hydraSection === id ? 'aria-current="page"' : ""}>${label}</button>`).join("")}
      </nav>
      ${this._hydraSection === "behavior" ? `
        <section class="card">
          <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Conversation windows</span><h2>Hydra behavior</h2><p class="muted">The same display, storage, model-context, and ledger limits used by Tater.</p></div></div>
          <div class="settings-grid">
            ${this.taterField("max_display", "Messages shown", { type: "number", min: 1, max: 100 })}
            ${this.taterField("max_store", "Maximum stored messages", { type: "number", min: 0, max: 10000, help: "Use 0 for unlimited storage." })}
            ${this.taterField("max_llm", "Messages sent to LLM", { type: "number", min: 1, max: 100 })}
            ${this.taterField("hydra_max_ledger_items", "Maximum ledger items", { type: "number", min: 1, max: 10000 })}
          </div>
          <div class="hydra-toggle-list">
            <label class="toggle-field"><span><strong>Astraeus second plan check</strong><small>Review a proposed device action before it runs. This adds one model call and some latency.</small></span><input data-tater-setting="hydra_astraeus_plan_review_enabled" type="checkbox" ${settings.hydra_astraeus_plan_review_enabled ? "checked" : ""}></label>
            <label class="toggle-field"><span><strong>Auto-continue incomplete final response</strong><small>Ask the model once more when a tool turn does not produce a spoken answer.</small></span><input data-tater-setting="hydra_auto_continue_incomplete_final_enabled" type="checkbox" ${settings.hydra_auto_continue_incomplete_final_enabled ? "checked" : ""}></label>
          </div>
        </section>
        ${this.renderDraftFooter("tater", `<button type="button" data-action="reset-tater-draft">Discard</button><button type="button" class="primary" data-action="save-tater">Save Hydra behavior</button>`)}
      ` : this._hydraSection === "conversations" ? `
        <section class="card">
          <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Stored messages</span><h2>Conversation data</h2><p class="muted">Recent user and assistant messages retained for follow-up context.</p></div><button type="button" class="danger" data-action="clear-hydra-conversations" ${messages.length ? "" : "disabled"}>Clear conversations</button></div>
          <div class="conversation-data-list">${messages.length ? messages.slice().reverse().map((row) => `<div><span>${escapeHtml(row.role || "message")}</span><p>${escapeHtml(row.content || "")}</p><small>${escapeHtml(row.conversation_id || "")}</small></div>`).join("") : '<p class="muted">No Tater conversations are stored yet.</p>'}</div>
        </section>
      ` : `
        <section class="hydra-metrics-grid">
          ${[["Turns", metrics.turns], ["Completed", metrics.completed], ["Failed", metrics.failed], ["Device calls", metrics.tool_calls], ["Conversations", metrics.conversations]].map(([label, value]) => `<div><span>${label}</span><strong>${Number(value || 0)}</strong></div>`).join("")}
        </section>
        <section class="card">
          <div class="workspace-section-heading"><div><span class="workspace-eyebrow">Recent activity</span><h2>Hydra ledger</h2><p class="muted">Inspect the request, plan review, device result, final response, and timing.</p></div><button type="button" class="danger" data-action="clear-hydra-ledger" ${ledger.length ? "" : "disabled"}>Clear ledger</button></div>
          <div class="hydra-ledger">${ledger.length ? ledger.map((row) => `<details><summary><span>${escapeHtml(row.outcome || "unknown")}</span><strong>${escapeHtml(row.request || "Voice turn")}</strong><b>${Number(row.total_ms || 0)} ms</b></summary><dl><dt>Response</dt><dd>${escapeHtml(row.response || row.error || "—")}</dd><dt>Device</dt><dd>${escapeHtml(row.device_id || "—")}</dd><dt>Conversation</dt><dd>${escapeHtml(row.conversation_id || "—")}</dd></dl>${(row.tools || []).map((tool) => `<section><strong>${escapeHtml(tool.name || "control_home")}</strong><span class="badge ${tool.approved ? "online" : "update"}">${tool.approved ? "Approved" : "Blocked"}</span><p>${escapeHtml(tool.review || "")}</p><pre>${escapeHtml(JSON.stringify({ arguments: tool.arguments, result: tool.result }, null, 2))}</pre></section>`).join("")}</details>`).join("") : '<p class="muted">The ledger will appear after the first Tater conversation.</p>'}</div>
        </section>
      `}
    `;
  }

  renderSatellites() {
    const devices = this._data.devices || [];
    if (this._selectedDeviceId) {
      const device = devices.find((row) => row.device_id === this._selectedDeviceId);
      if (device) return this.renderDeviceEditor(device);
    }
    if (!devices.length) {
      return `
        <section class="card empty">
          <h2>No satellites paired yet</h2>
          <p class="muted">Generate a pairing code, put the satellite in setup mode, and point it at this Home Assistant instance.</p>
          <button class="primary" data-action="pair">Add Satellite</button>
        </section>
      `;
    }
    const rooms = [...new Set(devices.map((device) => String(device.room || "")).filter(Boolean))].sort();
    if (this._roomFilter && !rooms.includes(this._roomFilter)) this._roomFilter = "";
    const connected = devices.filter((device) => device.connected).length;
    const updates = devices.filter((device) => device.firmware?.update_available).length;
    const wake = this._data.shared_wake_settings || this._data.wake_family_settings?.echo || {};
    const mode = { mww: "MWW", oww: "OWW", nww: "NWW", mww_oww: "MWW + OWW", mww_nww: "MWW + NWW" }[wake.wake_detector_mode] || "MWW";
    return `
      <div class="workspace-toolbar">
        <div class="workspace-summary"><span class="connection-status online"><i></i>${connected} online</span><span>${devices.length - connected} offline</span><span>${updates} ${updates === 1 ? "update" : "updates"}</span></div>
        <div class="workspace-filters"><input type="search" data-device-search aria-label="Find a satellite" placeholder="Find a satellite" value="${escapeHtml(this._deviceQuery)}">
          ${rooms.length > 1 ? `<select data-room-filter aria-label="Filter satellites by room"><option value="">All rooms</option>${rooms.map((room) => `<option value="${escapeHtml(room)}" ${room === this._roomFilter ? "selected" : ""}>${escapeHtml(room)}</option>`).join("")}</select>` : ""}
        </div>
      </div>
      <div class="workspace-device-list">${devices.map((device) => this.renderDeviceCard(device)).join("")}</div>
      <p class="muted workspace-filter-empty" hidden>No satellites match your search.</p>
      <div class="workspace-profile-strip"><div><strong>Shared wake profile</strong><span class="muted">${mode} · Shared voice defaults for your satellites</span></div><button type="button" data-tab="defaults">Voice defaults ${this.renderIcon("arrow-top-right")}</button></div>
    `;
  }

  applyDeviceFilter() {
    let visible = 0;
    this.shadowRoot.querySelectorAll("[data-device-search-text]").forEach((row) => {
      row.hidden = !row.dataset.deviceSearchText.includes(this._deviceQuery.trim().toLowerCase()) || Boolean(this._roomFilter && row.dataset.deviceRoom !== this._roomFilter);
      if (!row.hidden) visible++;
    });
    const empty = this.shadowRoot.querySelector(".workspace-filter-empty");
    if (empty) empty.hidden = visible > 0;
  }

  renderBluetooth() {
    const bluetooth = this._data.bluetooth || {};
    const scanners = bluetooth.scanners || [];
    const paired = bluetooth.paired || [];
    const grouped = new Map();
    for (const row of bluetooth.nearby || []) {
      if (paired.some((item) => item.address === row.address)) continue;
      const current = grouped.get(row.address);
      if (!current) {
        grouped.set(row.address, { ...row, paths: [row] });
      } else {
        current.paths.push(row);
        if (Number(row.rssi) > Number(current.rssi)) Object.assign(current, row, { paths: current.paths });
      }
    }
    const nearby = [...grouped.values()];
    const scannerBadges = scanners.length
      ? scanners.map((scanner) => {
          const capacity = scanner.slots
            ? `${scanner.free}/${scanner.slots} connections free`
            : "Bluetooth ready";
          return `<span class="badge online">${escapeHtml(scanner.satellite_name)} · ${escapeHtml(capacity)}</span>`;
        }).join("")
      : `<span class="badge">No compatible Echo connected</span>`;
    const pairedCards = paired.length
      ? paired.map((device) => `
          <section class="card bluetooth-paired-row">
            <div class="bluetooth-paired-copy">
              <h3>${escapeHtml(device.name || device.address)}</h3>
              <div class="bluetooth-address">${escapeHtml(device.address)}</div>
              <div class="muted" style="margin-top:6px">Bond stored on ${escapeHtml(device.satellite_name || device.satellite_id || "Echo satellite")}. The PIN is not stored.</div>
            </div>
            <button class="danger" data-action="bluetooth-unpair" data-address="${escapeHtml(device.address)}" data-satellite-id="${escapeHtml(device.satellite_id || "")}" ${this._loading ? "disabled" : ""}>Unpair</button>
          </section>
        `).join("")
      : `<section class="card empty"><h3>No paired Bluetooth devices</h3><p class="muted">Nearby devices appear below when a compatible Echo can hear them.</p></section>`;
    const nearbyCards = nearby.length
      ? nearby.map((device) => {
          const paths = [...device.paths].sort((a, b) => Number(b.rssi) - Number(a.rssi));
          const options = paths.map((path) => `<option value="${escapeHtml(path.satellite_id)}">${escapeHtml(path.satellite_name)} · ${escapeHtml(path.rssi)} dBm</option>`).join("");
          return `
            <section class="card bluetooth-device" data-bluetooth-device="${escapeHtml(device.address)}">
              <div class="bluetooth-device-head">
                <div><h3>${escapeHtml(device.name || "Unknown Bluetooth device")}</h3><div class="bluetooth-address">${escapeHtml(device.address)}</div></div>
                <div class="bluetooth-signal">${escapeHtml(device.rssi)} dBm</div>
              </div>
              <div class="bluetooth-pair-grid">
                <label class="field"><span>Echo satellite</span><select data-bluetooth-satellite>${options}</select></label>
                <label class="field"><span>Six-digit PIN</span><input data-bluetooth-pin inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="123456"></label>
                <button class="primary" data-action="bluetooth-pair" data-address="${escapeHtml(device.address)}" ${this._loading ? "disabled" : ""}>Pair</button>
              </div>
            </section>`;
        }).join("")
      : `<section class="card empty"><h3>No nearby devices yet</h3><p class="muted">Keep this page open near the device, make sure it is advertising, then refresh.</p></section>`;
    return `
      <section class="card section-card bluetooth-hero">
        <div>
          <h2>Echo Bluetooth Proxy</h2>
          <p class="muted">Compatible Echo satellites now act as native Home Assistant Bluetooth scanners. Home Assistant automatically selects the best available path for normal Bluetooth integrations.</p>
          <div class="bluetooth-proxies">${scannerBadges}</div>
        </div>
        <div class="bluetooth-mark">ᛒ</div>
      </section>
      <div class="device-head" style="margin:22px 0 10px"><div><h2>Paired devices</h2><div class="muted">PIN-protected bonds saved on an Echo satellite.</div></div></div>
      <div class="grid">${pairedCards}</div>
      <div class="device-head" style="margin:24px 0 10px"><div><h2>Nearby devices</h2><div class="muted">Choose a path or leave the strongest Echo selected.</div></div><button data-action="refresh" ${this._loading ? "disabled" : ""}>Refresh nearby</button></div>
      <div class="grid">${nearbyCards}</div>
    `;
  }

  renderAudio() {
    const devices = this._data.devices || [];
    const pairs = this._data.stereo_pairs || [];
    const intercom = this._data.intercom || {};
    const latestIntercom = intercom.recent?.[0] || null;
    return `
      <div class="workspace-section-heading"><div><h2>Saved stereo pairs</h2><p class="muted">Pairs appear as Home Assistant media players and keep left/right routing.</p></div><button type="button" class="primary" data-action="new-stereo" ${devices.length < 2 ? "disabled" : ""}>${this.renderIcon("plus")} Create stereo pair</button></div>
      <div class="grid">
        ${pairs.map((pair) => `
          <article class="card device-card ${pair.ready ? "online" : ""}">
            <div class="device-head">
              <div><h2>${escapeHtml(pair.name)}</h2><div class="muted">Sendspin stereo pair</div></div>
              <span class="badge ${pair.ready ? "online" : ""}">${pair.ready ? "Ready" : "Unavailable"}</span>
            </div>
            <div class="facts">
              <div class="fact"><label>Left</label><span>${escapeHtml(pair.members?.[0]?.name || pair.left_device_id)}</span></div>
              <div class="fact"><label>Right</label><span>${escapeHtml(pair.members?.[1]?.name || pair.right_device_id)}</span></div>
              <div class="fact"><label>Left trim</label><span>${Number(pair.left_volume_percent ?? 100)}% · ${Number(pair.left_delay_ms || 0)} ms</span></div>
              <div class="fact"><label>Right trim</label><span>${Number(pair.right_volume_percent ?? 100)}% · ${Number(pair.right_delay_ms || 0)} ms</span></div>
            </div>
            <div class="row-actions"><button class="danger" data-remove-stereo="${escapeHtml(pair.id)}">Delete pair</button></div>
          </article>
        `).join("")}
      </div>
      ${!pairs.length ? `<section class="card section-card empty"><h3>No stereo pairs yet</h3><p class="muted">${devices.length < 2 ? "Pair at least two satellites to create stereo." : "Choose two satellites to create a left/right pair."}</p></section>` : ""}
      <section class="card section-card" style="margin-top:14px">
        <div class="device-head">
          <div><h3>Push-to-talk intercom</h3><div class="muted">Hold the satellite action button, speak, and release to broadcast to every other connected Tater satellite.</div></div>
          <span class="badge ${intercom.ready ? "online" : ""}">${intercom.ready ? "Ready" : "Needs two satellites"}</span>
        </div>
        <div class="facts">
          <div class="fact"><label>Connected</label><span>${Number(intercom.connected_count || 0)} satellites</span></div>
          <div class="fact"><label>Recording</label><span>${Number(intercom.active_count || 0) ? `${Number(intercom.active_count)} active` : "Idle"}</span></div>
          <div class="fact"><label>Latest</label><span>${latestIntercom ? `${escapeHtml(latestIntercom.phase)} · ${Number(latestIntercom.sent_count || 0)} delivered` : "No broadcasts yet"}</span></div>
          <div class="fact"><label>Privacy</label><span>Temporary memory only</span></div>
        </div>
        <p class="muted" style="margin-bottom:0">Intercom audio bypasses the Assist pipeline. Music is ducked with a firmware overlay when supported, and recordings expire automatically.</p>
      </section>
      <div class="workspace-profile-strip"><div><strong>Multi-room playback</strong><span class="muted">Group satellites and saved pairs with Home Assistant’s Join action.</span></div><button type="button" data-action="grouping-help">Grouping help ${this.renderIcon("arrow-top-right")}</button></div>
    `;
  }

  renderStereoPairEditor() {
    const devices = this._data.devices || [];
    const options = (selected = "") => devices.map((device) => `<option value="${escapeHtml(device.device_id)}" ${device.device_id === selected ? "selected" : ""}>${escapeHtml(device.name)}${device.connected ? "" : " (offline)"}</option>`).join("");
    return `
      ${devices.length >= 2 ? `
        <section class="card section-card" style="margin-top:14px">
          <h3>Create a stereo pair</h3>
          <div class="section-description">Choose the speaker that should reproduce each channel. Fine-tune delay only when the physical placement or hardware path needs compensation.</div>
          <div class="settings-grid">
            <label class="field"><span>Pair name</span><input data-stereo-name maxlength="80" placeholder="Office Stereo" value="${escapeHtml(this._stereoDraft.name || "")}"></label>
            <label class="field"><span>Left satellite</span><select data-stereo-left><option value="">Choose left speaker</option>${options(this._stereoDraft.left || "")}</select></label>
            <label class="field"><span>Right satellite</span><select data-stereo-right><option value="">Choose right speaker</option>${options(this._stereoDraft.right || "")}</select></label>
            <label class="field"><span>Left channel trim (%)</span><input data-stereo-left-volume type="number" min="0" max="100" value="${escapeHtml(this._stereoDraft.leftVolume ?? 100)}"></label>
            <label class="field"><span>Right channel trim (%)</span><input data-stereo-right-volume type="number" min="0" max="100" value="${escapeHtml(this._stereoDraft.rightVolume ?? 100)}"></label>
            <label class="field"><span>Left delay (ms)</span><input data-stereo-left-delay type="number" min="0" max="250" value="${escapeHtml(this._stereoDraft.leftDelay ?? 0)}"></label>
            <label class="field"><span>Right delay (ms)</span><input data-stereo-right-delay type="number" min="0" max="250" value="${escapeHtml(this._stereoDraft.rightDelay ?? 0)}"></label>
          </div>
          <div class="row-actions" style="margin-top:15px"><button type="button" data-action="discard-stereo">Discard pair draft</button><button type="button" class="primary" data-action="save-stereo" ${this._loading ? "disabled" : ""}>Create stereo media player</button></div>
        </section>
      ` : `<section class="card empty" style="margin-top:14px"><h3>Pair two satellites first</h3><p class="muted">At least two paired satellites are required for stereo.</p></section>`}
    `;
  }

  renderDeviceCard(device) {
    const firmware = device.firmware || {};
    const board = String(firmware.label || device.board || "Satellite");
    const hasScreen = device.capabilities?.display || /show|spot|box|crown|athena|rook|checkers/i.test(board);
    const searchText = [device.name, device.room, board, device.device_id].join(" ").toLowerCase();
    return `
      <article class="workspace-device-row" data-device-search-text="${escapeHtml(searchText)}" data-device-room="${escapeHtml(device.room || "")}">
        <span class="workspace-device-icon">${this.renderIcon(hasScreen ? "monitor" : "speaker")}</span>
        <div class="workspace-device-copy">
          <div class="workspace-device-name"><h2>${escapeHtml(device.name)}</h2>${firmware.update_available ? '<span class="badge update">Update available</span>' : ""}</div>
          <div class="workspace-device-meta">${device.room ? `${escapeHtml(device.room)} · ` : ""}${escapeHtml(board)}</div>
          <div class="workspace-device-meta">${escapeHtml(device.state || "offline")} · ${device.connected ? `${device.wifi_rssi ?? "—"} dBm` : `Last seen ${formatAge(device.last_seen)}`}</div>
          ${this.renderDeviceVolume(device)}
        </div>
        <div class="workspace-device-actions">
          <span class="connection-status ${device.connected ? "online" : ""}"><i></i>${device.connected ? "Online" : "Offline"}</span>
          <div class="row-actions"><button type="button" data-identify="${escapeHtml(device.device_id)}" ${device.connected ? "" : "disabled"}>Identify</button><button type="button" data-configure="${escapeHtml(device.device_id)}">Open ${this.renderIcon("arrow-right")}</button></div>
          <div class="row-actions secondary-actions">${firmware.has_ota && device.connected ? `<button type="button" data-ota="${escapeHtml(device.device_id)}">${firmware.update_available ? "Update" : "Reinstall"}</button>` : ""}${!device.connected ? `<button type="button" class="danger" data-forget="${escapeHtml(device.device_id)}">Forget</button>` : ""}</div>
        </div>
        ${
          device.ota?.in_progress
            ? `<div class="workspace-device-progress"><div class="progress"><span style="width:${Math.max(0, Math.min(100, Number(device.ota.progress || 0)))}%"></span></div><div class="muted">${escapeHtml(device.ota.message || "Updating…")}</div></div>`
            : ""
        }
      </article>
    `;
  }

  renderDeviceVolume(device) {
    if (device.capabilities?.speaker === false) return "";
    const rawValue = Number(device.settings?.volume_percent ?? 80);
    const value = Math.max(0, Math.min(100, Number.isFinite(rawValue) ? Math.round(rawValue) : 80));
    return `
      <div class="device-volume" style="--device-volume-progress:${value}%">
        <span class="device-volume-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M4 9v6h4l5 4V5L8 9H4zm12.5 3a4.5 4.5 0 0 0-2.1-3.8v7.6a4.5 4.5 0 0 0 2.1-3.8zm-2.1-8.2v2.1a7 7 0 0 1 0 12.2v2.1a9 9 0 0 0 0-16.4z"></path>
          </svg>
        </span>
        <label class="device-volume-main">
          <span class="device-volume-head">
            <strong>Volume</strong>
            <span class="device-volume-feedback" data-volume-feedback></span>
            <output data-volume-output>${value}%</output>
          </span>
          <span class="device-volume-range">
            <span aria-hidden="true">0</span>
            <input type="range" min="0" max="100" step="1" value="${value}"
              aria-label="${escapeHtml(device.name)} speaker volume"
              data-device-volume="${escapeHtml(device.device_id)}" data-volume-last="${value}">
            <span aria-hidden="true">100</span>
          </span>
        </label>
      </div>
    `;
  }

  prepareSettingsDraft(settings) {
    const draft = clone(settings);
    if (draft.wake_detector_mode === "dual") draft.wake_detector_mode = "mww_oww";
    if (
      draft.wake_detector_mode === "mww" &&
      draft.oww_wake_word === "custom_url" &&
      String(draft.oww_wake_word_url || "").split("?", 1)[0].endsWith(".wake-bundle.json")
    ) {
      draft.wake_word = "custom_url";
      draft.wake_word_url = draft.oww_wake_word_url;
    }
    if (
      draft.wake_word === "custom_url" &&
      !draft.wake_model_asset_id &&
      isWakeWordCatalogUrl(draft.wake_word_url)
    ) {
      draft.wake_word = "catalog";
      draft.wake_word_catalog_url = draft.wake_word_url;
    } else {
      draft.wake_word_catalog_url = "";
    }
    if (
      draft.oww_wake_word === "custom_url" &&
      isWakeWordCatalogUrl(draft.oww_wake_word_url)
    ) {
      draft.oww_wake_word = "catalog";
      draft.oww_wake_word_catalog_url = draft.oww_wake_word_url;
    } else {
      draft.oww_wake_word_catalog_url = "";
    }
    return draft;
  }

  prepareDeviceDraft(deviceId, markDirty = false) {
    const device = (this._data?.devices || []).find((row) => row.device_id === deviceId);
    if (!device) return;
    if (deviceId !== this._selectedDeviceId) this.rememberDeviceDraft();
    this._selectedDeviceId = deviceId;
    const saved = this._deviceDrafts.get(deviceId);
    if (saved && this.isScopeDirty("device")) {
      this._deviceDraft = clone(saved.draft);
      this._deviceOriginal = clone(saved.original);
      this._pipelineDraft = saved.pipeline;
      return;
    }
    this._deviceDraft = this.prepareSettingsDraft(device.settings);
    this._deviceOriginal = this.prepareSettingsDraft(device.settings);
    this._pipelineDraft = device.pipeline_id || "";
    if (markDirty) this.markDirty("device");
  }

  deviceSettingGroups(device) {
    const sections = this.settingsSectionsFor(this._deviceDraft, "device", device);
    const available = new Set(sections.map((section) => section.section));
    const groups = DEVICE_SETTING_GROUPS.filter((group) => ["voice", "diagnostics"].includes(group.id) || (group.id === "audio" && device.capabilities?.speaker !== false) || group.sections.some((section) => available.has(section)));
    const covered = new Set(DEVICE_SETTING_GROUPS.flatMap((group) => group.sections));
    const other = [...available].filter((section) => !covered.has(section));
    return [{ id: "overview", label: "Overview", sections: [] }, ...groups, ...(other.length ? [{ id: "other", label: "Other settings", sections: other }] : [])];
  }

  renderSectionNavigation(groups, active, attribute, label) {
    return `<nav class="workspace-section-nav" aria-label="${label}">${groups.map((group) => `<button type="button" ${attribute}="${group.id}" ${active === group.id ? 'aria-current="page"' : ""}>${group.label}</button>`).join("")}</nav>`;
  }

  renderDeviceEditor(device) {
    const pipelines = this._data.pipelines || [];
    const groups = this.deviceSettingGroups(device);
    const active = groups.find((group) => group.id === this._deviceSection) || groups[0];
    this._deviceSection = active.id;
    return `
      <button type="button" class="workspace-back" data-action="back">${this.renderIcon("arrow-left")} All satellites</button>
      <div class="editor-head workspace-editor-head">
        <div>
          <span class="workspace-eyebrow">${escapeHtml(device.room || "Satellite workspace")}</span>
          <h2>${escapeHtml(device.name)}</h2>
          <p class="muted">${escapeHtml(device.firmware?.label || device.board)} · Settings for this satellite</p>
        </div>
        <span class="connection-status ${device.connected ? "online" : ""}"><i></i>${device.connected ? "Online" : "Offline"}</span>
      </div>
      ${this.renderSectionNavigation(groups, active.id, "data-device-section", "Satellite settings")}
      ${active.id === "overview" ? this.renderDeviceOverview(device) : ""}
      ${active.id === "voice" ? `
      <section class="card section-card">
        <h3>Home Assistant Voice</h3>
        <div class="settings-grid">
          <label class="field">
            <span>Assist pipeline</span>
            <select data-special="pipeline">
              <option value="" ${!this._pipelineDraft ? "selected" : ""}>Preferred pipeline</option>
              ${pipelines.map((row) => `<option value="${escapeHtml(row.id)}" ${row.id === this._pipelineDraft ? "selected" : ""}>${escapeHtml(row.name)}</option>`).join("")}
            </select>
          </label>
        </div>
      </section>
      ` : ""}
      ${active.id !== "overview" ? this.renderSettingsSections(this._deviceDraft, "device", device, { include: active.sections }) : ""}
      ${active.id === "audio" ? this.renderDeviceVolume(device) : ""}
      ${active.id === "diagnostics" ? this.renderDeviceDiagnostics(device) : ""}
      ${active.id !== "overview" ? this.renderDraftFooter("device", `
        <button data-sync-settings="${escapeHtml(device.device_id)}" ${device.connected ? "" : "disabled"}>Resend live settings</button>
        <button data-action="reset-device">Use all shared defaults</button>
        <button class="primary" data-action="save-device" ${this._loading ? "disabled" : ""}>Save satellite</button>
      `) : ""}
    `;
  }

  renderDeviceOverview(device) {
    const firmware = device.firmware || {};
    return `<section class="card section-card"><h3>At a glance</h3><p class="muted">This satellite uses your shared voice defaults unless you override a setting.</p>
      <div class="facts">
        <div class="fact"><label>Hardware</label><span>${escapeHtml(firmware.label || device.board)}</span></div>
        <div class="fact"><label>Firmware</label><span>${escapeHtml(device.firmware_version || "Unknown")}</span></div>
        <div class="fact"><label>Wi-Fi</label><span>${device.wifi_rssi ?? "—"}${device.wifi_rssi != null ? " dBm" : ""}</span></div>
        <div class="fact"><label>Free memory</label><span>${formatBytes(device.free_heap)}</span></div>
        <div class="fact"><label>Last seen</label><span>${formatAge(device.last_seen)}</span></div>
        <div class="fact"><label>Voice state</label><span>${escapeHtml(device.state || "offline")}</span></div>
      </div>
      ${this.renderDeviceVolume(device)}
      <div class="row-actions"><button type="button" data-identify="${escapeHtml(device.device_id)}" ${device.connected ? "" : "disabled"}>${this.renderIcon("star-four-points-outline")} Identify satellite</button><button type="button" data-device-section="diagnostics">View diagnostics</button>${firmware.has_ota && device.connected ? `<button type="button" data-ota="${escapeHtml(device.device_id)}">${firmware.update_available ? "Install update" : "Reinstall latest"}</button>` : ""}${!device.connected ? `<button type="button" class="danger" data-forget="${escapeHtml(device.device_id)}">Forget satellite</button>` : ""}</div>
    </section>`;
  }

  renderDeviceDiagnostics(device) {
    const xmos = device.xmos_firmware || {};
    const transport = device.transport || {};
    const sync = device.settings_sync || {};
    const wake = device.wake_model || {};
    const syncLabel = {
      never: "Not sent",
      sending: "Sending",
      sent: "Awaiting confirmation",
      confirmed: "Confirmed",
      timeout: "Not confirmed",
      failed: "Failed",
      offline: "Offline",
    }[sync.state] || String(sync.state || "Unknown");
    const wakeState = wake.downloading
      ? "Downloading"
      : wake.matches
        ? "Active"
        : wake.last_error
          ? `Not active — ${wake.last_error}`
          : "Not active";
    const appliedWakeSound =
      wake.wake_sound_enabled == null ? "Not reported by this board" : wake.wake_sound_enabled ? "Enabled" : "Disabled";
    const logs = (device.logs || [])
      .map((row) => {
        const when = row.ts ? new Date(Number(row.ts) * 1000).toLocaleTimeString() : "";
        return `${when} [${String(row.level || "info").toUpperCase()}] ${row.message || ""}`;
      })
      .join("\n");
    return `
      <section class="card section-card">
        <h3>Satellite Diagnostics</h3>
        <div class="facts">
          <div class="fact"><label>Firmware</label><span>${escapeHtml(device.firmware_version || "Unknown")}</span></div>
          <div class="fact"><label>Wi-Fi</label><span>${device.wifi_rssi ?? "—"}${device.wifi_rssi != null ? " dBm" : ""}</span></div>
          <div class="fact"><label>Free memory</label><span>${formatBytes(device.free_heap)}</span></div>
          <div class="fact"><label>Audio drops</label><span>${Number(device.audio_drops || 0)}</span></div>
          <div class="fact"><label>Settings sync</label><span>${escapeHtml(syncLabel)}</span></div>
          <div class="fact"><label>Settings generation</label><span>${Number(sync.generation || 0)}</span></div>
          <div class="fact"><label>Desired wake word</label><span>${escapeHtml(wake.desired || "Unknown")}</span></div>
          <div class="fact"><label>Active wake model</label><span>${escapeHtml(wake.active_label || wake.active || "None")}</span></div>
          <div class="fact"><label>Wake model state</label><span>${escapeHtml(wakeState)}</span></div>
          <div class="fact"><label>Desired wake sound</label><span>${wake.desired_wake_sound_enabled ? "Enabled" : "Disabled"}</span></div>
          <div class="fact"><label>Applied wake sound</label><span>${escapeHtml(appliedWakeSound)}</span></div>
          <div class="fact"><label>XMOS firmware</label><span>${escapeHtml(xmos.installed_version || "Not reported")}</span></div>
          <div class="fact"><label>TX queue</label><span>${escapeHtml(transport.audio_tx_queue_depth ?? "—")}</span></div>
        </div>
        ${sync.message ? `<div class="verifier-note">${escapeHtml(sync.message)}</div>` : ""}
        <details>
          <summary>Recent satellite log</summary>
          <pre>${escapeHtml(logs || "No satellite log messages have been received.")}</pre>
        </details>
      </section>
    `;
  }

  renderSettingsEditor(title, values, scope, sectionFilter = {}) {
    return `
      <div class="editor-head">
        <div>
          <h2>${escapeHtml(title)}</h2>
          <div class="muted">Changes are pushed live and confirmed by every connected satellite. A changed shared wake model or wake sound replaces conflicting per-satellite overrides.</div>
        </div>
      </div>
      ${this.renderSettingsSections(values || {}, scope, null, sectionFilter)}
      <div class="sticky-actions">
        <button data-action="reset-draft">Discard changes</button>
        <button class="primary" data-action="save-global" ${this._loading ? "disabled" : ""}>Save and update all</button>
      </div>
    `;
  }

  renderVoiceDefaults() {
    const sections = this.settingsSectionsFor(this._globalDraft || {}, "global", null, { exclude: ["wake", "feedback", "verifier"] });
    const available = new Set(sections.map((section) => section.section));
    const covered = new Set(SHARED_SETTING_GROUPS.flatMap((group) => group.sections));
    const other = [...available].filter((section) => !covered.has(section));
    const groups = [{ id: "wake", label: "Wake profile", sections: [] }, ...SHARED_SETTING_GROUPS.filter((group) => group.sections.some((section) => available.has(section))), ...(other.length ? [{ id: "other", label: "Other settings", sections: other }] : [])];
    const active = groups.find((group) => group.id === this._voiceSection) || groups[0];
    this._voiceSection = active.id;
    return `
      ${this.renderSectionNavigation(groups, active.id, "data-voice-section", "Shared voice sections")}
      ${active.id === "wake" ? this.renderSharedWakeEditor(this._wakeDraft || {}) : `
      ${this.renderSettingsSections(this._globalDraft || {}, "global", null, { include: active.sections })}
      ${this.renderDraftFooter("global", `
        <button data-action="reset-draft">Discard shared changes</button>
        <button class="primary" data-action="save-global" ${this._loading ? "disabled" : ""}>Save shared settings</button>
      `)}
      `}
    `;
  }

  renderSharedWakeEditor(values) {
    const connected = (this._data.devices || []).filter((device) => device.connected).length;
    return `
      <section class="card section-card">
        <div class="device-head">
          <div>
            <div class="workspace-eyebrow">Shared wake profile</div>
            <h3 style="margin-top:6px">How should satellites wake?</h3>
          </div>
          <span class="badge ${connected ? "online" : ""}">${connected} connected</span>
        </div>
        ${this.renderWakeModePicker(values)}
        ${this.renderSettingsSections(values, "wake", null, { include: ["wake"], wakeFamily: "echo", bare: true })}
        ${this.renderWakeTuningOverrides(values)}
        ${this.renderDraftFooter("wake", `
          <button data-reset-shared-wake>Discard wake changes</button>
          <button class="primary" data-save-shared-wake ${this._loading ? "disabled" : ""}>Save and update all satellites</button>
        `)}
      </section>
    `;
  }

  renderWakeModePicker(values) {
    const selected = String(values?.wake_detector_mode || "mww_oww");
    const rows = [
      {
        label: "Single model",
        className: "",
        options: [
          ["mww", "MWW", "microWakeWord on every satellite"],
          ["oww", "OWW", "openWakeWord where supported"],
          ["nww", "NWW", "NanoWakeWord where supported"],
        ],
      },
      {
        label: "Dual model",
        className: "dual",
        options: [
          ["mww_oww", "MWW + OWW", "Both models must agree"],
          ["mww_nww", "MWW + NWW", "Both models must agree"],
        ],
      },
    ];
    return `
      <div class="wake-mode-picker">
        ${rows.map((row) => `
          <div class="wake-mode-label">${row.label}</div>
          <div class="wake-mode-grid ${row.className}">
            ${row.options.map(([value, label, description]) => `
              <button type="button" class="wake-mode-option ${selected === value ? "active" : ""}" data-wake-mode="${value}" aria-pressed="${selected === value}">
                <i>${value === "mww_oww" ? "M+O" : value === "mww_nww" ? "M+N" : label}</i>
                <span><strong>${label}</strong><small>${description}</small></span><b>✓</b>
              </button>
            `).join("")}
          </div>
        `).join("")}
      </div>
    `;
  }

  renderWakeTuningOverrides(values) {
    const mode = String(values?.wake_detector_mode || "mww_oww");
    const active = {
      mww: ["mww", "mww_oww", "mww_nww"].includes(mode),
      oww: ["oww", "mww_oww"].includes(mode),
      nww: ["nww", "mww_nww"].includes(mode),
    };
    const architecture = String(values?.nww_architecture || "cnn").toLowerCase();
    const owwDual = mode === "mww_oww";
    const models = [
      {
        key: "mww",
        title: "microWakeWord",
        enabled: "mww_tuning_override_enabled",
        threshold: "mww_threshold_override",
        patience: "mww_sliding_window_override",
        patienceLabel: "Sliding window",
        baseThreshold: values?.wake_profile_threshold ?? 0.98,
        basePatience: values?.wake_profile_sliding_window ?? 5,
      },
      {
        key: "oww",
        title: "openWakeWord",
        enabled: "oww_tuning_override_enabled",
        threshold: "oww_threshold_override",
        patience: "oww_patience_override",
        patienceLabel: "Patience",
        baseThreshold: owwDual
          ? values?.oww_profile_confirmation_threshold ?? 0.92
          : values?.oww_profile_threshold ?? 0.99,
        basePatience: owwDual
          ? values?.oww_profile_confirmation_patience ?? 3
          : values?.oww_profile_patience ?? 3,
      },
      {
        key: "nww",
        title: `NanoWakeWord ${architecture.toUpperCase()}`,
        enabled: "nww_tuning_override_enabled",
        threshold: "nww_threshold_override",
        patience: "nww_patience_override",
        patienceLabel: "Patience",
        baseThreshold:
          values?.[`nww_${architecture}_profile_threshold`] ??
          values?.nww_profile_threshold ??
          0.99,
        basePatience:
          values?.[`nww_${architecture}_profile_patience`] ??
          values?.nww_profile_patience ??
          3,
      },
    ].filter((model) => active[model.key]);
    if (!models.length) return "";
    const bundleSchema = Number(values?.wake_bundle_schema_version || 0);
    const boundaryAvailable = Boolean(values?.wake_boundary_available);
    const boundaryDetails = bundleSchema >= 4
      ? `Schema V${bundleSchema} · ${boundaryAvailable
        ? `threshold ${values?.wake_boundary_threshold ?? "—"} · ${formatBytes(values?.wake_boundary_model_size_bytes)}`
        : "no endpoint model included"}`
      : "";
    return `
      <div class="wake-tuning">
        <div class="wake-tuning-head">
          <div>
            <h3>Wake model tuning</h3>
            <div class="muted">Bundle values stay active until you enable an override for that model.</div>
          </div>
        </div>
        ${bundleSchema >= 4 ? `
          <div class="wake-boundary-card ${boundaryAvailable ? "" : "missing"}">
            <i>END</i>
            <span><strong>Wake boundary model</strong><small>${escapeHtml(boundaryDetails)}. Echo firmware keeps this model loaded to separate the wake phrase from immediate speech.</small></span>
            <span class="badge ${boundaryAvailable ? "online" : ""}">${boundaryAvailable ? "Included" : "Unavailable"}</span>
          </div>
        ` : ""}
        <div class="wake-tuning-grid">
          ${models.map((model) => {
            const enabled = Boolean(values?.[model.enabled]);
            return `
              <article class="wake-tuning-card ${enabled ? "active" : ""}">
                <div class="wake-tuning-title"><strong>${escapeHtml(model.title)}</strong><span class="badge">Bundle ${escapeHtml(model.baseThreshold)} · ${escapeHtml(model.basePatience)}</span></div>
                <small>Override the trainer-tested values for built-in, catalog, and custom wake bundles.</small>
                <label class="wake-tuning-switch">
                  <input type="checkbox" data-setting="${model.enabled}" data-scope="wake" ${enabled ? "checked" : ""}>
                  <span>Override bundle values</span>
                </label>
                ${enabled ? `
                  <div class="wake-tuning-inputs">
                    <label class="field"><span>Threshold</span><input type="number" min="0.01" max="${model.key === "mww" ? "0.99" : "1"}" step="0.01" value="${escapeHtml(values?.[model.threshold] ?? model.baseThreshold)}" data-setting="${model.threshold}" data-scope="wake"></label>
                    <label class="field"><span>${escapeHtml(model.patienceLabel)}</span><input type="number" min="1" max="${model.key === "mww" ? "10" : "20"}" step="1" value="${escapeHtml(values?.[model.patience] ?? model.basePatience)}" data-setting="${model.patience}" data-scope="wake"></label>
                  </div>
                ` : ""}
              </article>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  capabilityRequirementMet(definition, device, boardKey) {
    const required = String(definition?.required_capability || "").trim();
    if (!required) return true;
    if ((definition.capability_fallback_boards || []).includes(boardKey)) return true;
    const raw = device?.capabilities?.[required];
    const current = raw === true ? 1 : Number(raw || 0);
    const minimum = Number(definition.minimum_capability_version || 1);
    return Number.isFinite(current) && current >= minimum;
  }

  settingsSectionsFor(values, scope, device = null, sectionFilter = {}) {
    const boardKey = String(device?.board_key || device?.board || "")
      .trim()
      .toLowerCase()
      .replaceAll("-", "_");
    return (this._data.settings_schema || [])
      .filter((section) => !section.scopes || section.scopes.includes(scope))
      .filter(
        (section) =>
          !(section.include_boards || []).length ||
          section.include_boards.includes(boardKey),
      )
      .filter((section) => !(section.exclude_boards || []).includes(boardKey))
      .filter((section) => this.capabilityRequirementMet(section, device, boardKey))
      .filter((section) => !(sectionFilter.exclude || []).includes(section.section))
      .filter((section) => !(sectionFilter.include || []).length || sectionFilter.include.includes(section.section))
      .map(
        (section) => {
          const wakeFamily = sectionFilter.wakeFamily || device?.wake_family || "";
          const fields = (section.fields || [])
            .filter((field) => !(field.scopes || []).length || field.scopes.includes(scope))
            .filter((field) => !field.override_control)
            .filter((field) => !(scope === "wake" && field.key === "wake_detector_mode"))
            .filter((field) => !(field.include_boards || []).length || field.include_boards.includes(boardKey))
            .filter((field) => !(field.exclude_boards || []).includes(boardKey))
            .filter((field) => this.capabilityRequirementMet(field, device, boardKey))
            .filter((field) => !(field.wake_families || []).length || field.wake_families.includes(wakeFamily))
            .filter((field) => !(field.detector_modes || []).length || field.detector_modes.includes(String(values?.wake_detector_mode || "mww")))
            .filter((field) => this.fieldVisible(field, values));
          return { ...section, fields };
        },
      )
      .filter((section) => section.fields.length);
  }

  renderSettingsSections(values, scope, device = null, sectionFilter = {}) {
    return this.settingsSectionsFor(values, scope, device, sectionFilter)
      .map((section) => {
          const contents = `
            ${sectionFilter.bare ? "" : `<h3>${escapeHtml(section.title)}</h3>`}
            ${sectionFilter.bare ? "" : `<div class="section-description">${escapeHtml(section.description || "")}</div>`}
            <div class="settings-grid">
              ${section.fields.map((field) => this.renderField(field, values, scope)).join("")}
            </div>
          `;
          return sectionFilter.bare ? contents : `<section class="card section-card">${contents}</section>`;
        })
      .join("");
  }

  renderTrainer() {
    const trainer = this._data.trainer_link || {};
    const pairing = trainer.pairing || {};
    const linked = Boolean(trainer.linked);
    return `
      <section class="card section-card trainer-hero">
        <div class="trainer-head">
          <div class="trainer-identity">
            <div class="trainer-mark" aria-hidden="true">W</div>
            <div>
              <h2>Wake Word Trainer</h2>
              <div class="muted">Securely publish newly trained wake words to every paired satellite.</div>
            </div>
          </div>
          <span class="badge ${linked ? "online" : ""}">${linked ? "Linked" : "Not linked"}</span>
        </div>
        ${
          linked
            ? `
              <div class="facts trainer-status-grid">
                <div class="fact"><label>Trainer</label><span>${escapeHtml(trainer.trainer_name || "Wake Word Trainer")}</span></div>
                <div class="fact"><label>Address</label><span>${escapeHtml(trainer.trainer_url || "Not reported")}</span></div>
                <div class="fact"><label>Linked</label><span>${escapeHtml(formatDateTime(trainer.linked_at))}</span></div>
                <div class="fact"><label>Last publish</label><span>${escapeHtml(trainer.last_publish_at ? `${trainer.last_wake_word || "Wake word"} · ${formatDateTime(trainer.last_publish_at)}` : "No wake word published yet")}</span></div>
              </div>
              <div class="row-actions">
                <button data-action="trainer-pair">Relink Trainer</button>
                <button class="danger" data-action="trainer-unlink">Unlink</button>
              </div>
            `
            : `
              <p class="muted" style="margin:18px 0">No trainer is linked. Generate a short-lived code here, then enter it in the trainer’s Auto tab.</p>
              <button class="primary" data-action="trainer-pair">Link Trainer</button>
            `
        }
      </section>
      ${
        pairing.active
          ? `
            <section class="card section-card trainer-code-card">
              <div class="muted">Trainer pairing code</div>
              <div class="trainer-code">${escapeHtml(pairing.display_code)}</div>
              <div class="row-actions">
                <button data-copy-trainer-code="${escapeHtml(pairing.display_code)}">Copy code</button>
                <button data-copy-trainer-url="${escapeHtml(this._data.server_address)}">Copy Home Assistant address</button>
              </div>
              <ol class="trainer-steps">
                <li>Open the Wake Word Trainer and select the <strong>Auto</strong> tab.</li>
                <li>Select <strong>Link Tater</strong> and enter <span class="server">${escapeHtml(this._data.server_address)}</span>.</li>
                <li>Enter this code. It expires in about ${Math.max(1, Math.ceil(Number(pairing.expires_in_s || 0) / 60))} minute(s).</li>
              </ol>
            </section>
          `
          : ""
      }
      ${this.renderSettingsSections(this._globalDraft || {}, "global", null, { include: ["feedback"] })}
      ${this.renderDraftFooter("trainer", `
        <button data-action="reset-draft">Discard changes</button>
        <button class="primary" data-action="save-trainer" ${this._loading ? "disabled" : ""}>Save trainer settings</button>
      `)}
    `;
  }

  renderVerifier() {
    const devices = this._data.devices || [];
    const mode = String(this._globalDraft?.wake_verifier_mode || "off");
    const labels = { off: "Disabled", observe: "Observe", enforce: "Enabled" };
    const totals = devices.reduce(
      (summary, device) => {
        const verifier = device.wake_verifier || {};
        summary.checks += Number(verifier.count || 0);
        summary.accepted += Number(verifier.accepted || 0);
        summary.rejected += Number(verifier.rejections || 0);
        summary.failOpen += Number(verifier.fail_open || 0);
        return summary;
      },
      { checks: 0, accepted: 0, rejected: 0, failOpen: 0 },
    );
    return `
      <section class="card section-card trainer-hero">
        <div class="trainer-head">
          <div class="trainer-identity">
            <div class="trainer-mark" aria-hidden="true">STT</div>
            <div>
              <h2>STT Wake Verification</h2>
              <div class="muted">Use each satellite’s selected Assist pipeline to confirm the locally detected wake word before listening starts.</div>
            </div>
          </div>
          <span class="badge ${mode !== "off" ? "online" : ""}">${escapeHtml(labels[mode] || "Disabled")}</span>
        </div>
        <div class="facts trainer-status-grid">
          <div class="fact"><label>Checks</label><span>${totals.checks}</span></div>
          <div class="fact"><label>Accepted</label><span>${totals.accepted}</span></div>
          <div class="fact"><label>Rejected</label><span>${totals.rejected}</span></div>
          <div class="fact"><label>Fail-open</label><span>${totals.failOpen}</span></div>
        </div>
        <div class="verifier-note">
          <strong>Observe</strong> records results without blocking wakes. <strong>Enabled</strong> rejects transcript mismatches and blocks custom models whose phrase is unknown, but still opens listening for transient STT errors or a missed 500 ms deadline. The expected phrase follows the active wake word, a custom JSON manifest, or the latest trainer publish automatically.
        </div>
      </section>
      ${this.renderSettingsSections(this._globalDraft || {}, "global", null, { include: ["verifier"] })}
      <div class="editor-head">
        <div>
          <h2>Results by Satellite</h2>
          <div class="muted">Results refresh automatically. Counts reset when the satellite and Home Assistant runtime counters both restart.</div>
        </div>
      </div>
      ${
        devices.length
          ? `<div class="grid">${devices.map((device) => this.renderVerifierDevice(device)).join("")}</div>`
          : `<section class="card empty"><h3>No satellites paired yet</h3><p class="muted">Pair a satellite to begin observing wake checks.</p></section>`
      }
      ${this.renderDraftFooter("verifier", `
        <button data-action="reset-draft">Discard changes</button>
        <button class="primary" data-action="save-verifier" ${this._loading ? "disabled" : ""}>Apply to all satellites</button>
      `)}
    `;
  }

  renderVerifierDevice(device) {
    const verifier = device.wake_verifier || {};
    const last = verifier.last || {};
    const pipeline = verifier.pipeline || {};
    const mode = String(verifier.mode || "off");
    const appliedMode = String(verifier.applied_mode || "");
    const hasLast = Boolean(last.reason);
    const failOpen = hasLast && last.available === false;
    const rejected = hasLast && last.available !== false && last.accepted === false;
    const lastLabel =
      mode === "off" ? "Verification off" : !hasLast ? "No result" : failOpen ? "Fail-open" : rejected ? "Rejected" : "Accepted";
    const lastClass = mode === "off" ? "" : failOpen ? "fail-open" : rejected ? "rejected" : "online";
    const modePending = mode !== "off" && appliedMode !== mode;
    const status =
      !device.connected
        ? "Offline"
        : !verifier.supported
          ? "Firmware update needed"
          : mode === "off"
            ? "Disabled"
            : modePending
              ? "Applying settings"
              : "Ready";
    const reason = String(last.reason || "—").replaceAll("_", " ");
    return `
      <article class="card verifier-device ${failOpen ? "fail-open" : rejected ? "rejected" : ""}">
        <div class="device-head">
          <div>
            <h3>${escapeHtml(device.name)}</h3>
            <div class="muted">${escapeHtml(pipeline.name || "Preferred Assist pipeline")}</div>
          </div>
          <span class="badge ${device.connected && verifier.supported ? "online" : ""}">${escapeHtml(status)}</span>
        </div>
        <div class="badges">
          <span class="badge ${lastClass}">${escapeHtml(lastLabel)}</span>
          <span class="badge">${Number(verifier.count || 0)} checks</span>
        </div>
        <div class="facts">
          <div class="fact"><label>Expected phrase</label><span>${escapeHtml(verifier.target_phrase || "Unknown — blocked when Enabled")}</span></div>
          <div class="fact"><label>STT engine</label><span>${escapeHtml(pipeline.stt_engine || "Not configured")}</span></div>
          <div class="fact"><label>Accepted</label><span>${Number(verifier.accepted || 0)}</span></div>
          <div class="fact"><label>Rejected</label><span>${Number(verifier.rejections || 0)}</span></div>
          <div class="fact"><label>Fail-open</label><span>${Number(verifier.fail_open || 0)}</span></div>
          <div class="fact"><label>Last match</label><span>${hasLast && last.available !== false ? `${Math.round(Number(last.score || 0) * 100)}% match · ${Math.round(Number(last.threshold ?? this._globalDraft?.wake_verifier_threshold ?? 0.85) * 100)}% required` : "—"}</span></div>
          <div class="fact"><label>STT latency</label><span>${hasLast ? `${Number(last.stt_ms || 0).toFixed(1)} ms` : "—"}</span></div>
          <div class="fact"><label>Reason</label><span>${escapeHtml(reason)}</span></div>
        </div>
        <div class="transcript">${escapeHtml(last.transcript ? `“${last.transcript}”` : "No transcript yet")}</div>
      </article>
    `;
  }

  fieldVisible(field, values) {
    const condition = field.show_when;
    if (!condition) return true;
    return values?.[condition.key] === condition.equals;
  }

  wakeWordCatalogOptions(currentValue = "", modelType = "mww") {
    const sourceKey = modelType === "nww" ? "nww_options" : modelType === "oww" ? "oww_options" : "options";
    const options = clone(this._wakeWordCatalog?.[sourceKey] || []);
    if (
      currentValue &&
      isWakeWordCatalogUrl(currentValue) &&
      !options.some((option) => String(option.value) === String(currentValue))
    ) {
      const path = new URL(currentValue).pathname.split("/");
      const version = path.at(-2)?.replace("microWakeWords", "") || "Catalog";
      const label = decodeURIComponent(path.at(-1) || "wake_word.json")
        .replace(/\.json$/i, "")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
      options.unshift({ value: currentValue, label: `${label} [${version}]` });
    }
    if (!options.length) {
      options.push({ value: "", label: "Catalog unavailable" });
    }
    return options;
  }

  wakeWordCatalogDescription(field, modelType = "mww") {
    const catalog = this._wakeWordCatalog || {};
    const count = modelType === "mww"
      ? Number(catalog.count || 0)
      : this.wakeWordCatalogOptions("", modelType).filter((option) => option.value).length;
    const versions = Array.isArray(catalog.versions) ? catalog.versions : [];
    const range = versions.length
      ? versions.length === 1
        ? `V${versions[0]}`
        : `V${versions[0]}–V${versions.at(-1)}`
      : "";
    const summary = count
      ? `${count} official wake models${range ? ` across ${range}` : ""}.`
      : String(field.description || "");
    return [summary, catalog.warning].filter(Boolean).join(" ");
  }

  renderField(field, values, scope, inPicker = false) {
    const value = values?.[field.key] ?? "";
    const common = `data-setting="${escapeHtml(field.key)}" data-scope="${scope}"`;
    if (field.type === "percentage_range") {
      const minimum = Number(field.min ?? 0.5);
      const maximum = Number(field.max ?? 1);
      const step = Number(field.step ?? 0.01);
      const defaultValue = Number(field.default ?? 0.85);
      const numericValue = Math.max(minimum, Math.min(maximum, Number(value || defaultValue)));
      return `
        <div class="percentage-range-field">
          <div class="percentage-range-head"><span>${escapeHtml(field.label)}</span><output>${Math.round(numericValue * 100)}%</output></div>
          <input type="range" ${common} min="${minimum}" max="${maximum}" step="${step}" value="${numericValue}">
          <div class="percentage-range-scale"><span>${Math.round(minimum * 100)}% · more tolerant</span><span>${Math.round(maximum * 100)}% · exact match</span></div>
          <div class="percentage-range-footer">
            <small>${escapeHtml(field.description || "")}</small>
            <button type="button" data-reset-setting="${escapeHtml(field.key)}" data-reset-scope="${scope}" data-reset-value="${defaultValue}" ${numericValue === defaultValue ? "disabled" : ""}>Reset to ${Math.round(defaultValue * 100)}%</button>
          </div>
        </div>
      `;
    }
    if (field.type === "boolean") {
      return `
        <label class="toggle-field">
          <span>${escapeHtml(field.label)}</span>
          <input type="checkbox" ${common} ${value ? "checked" : ""}>
        </label>
      `;
    }
    if (field.type === "entity_list") {
      const selected = String(value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const limit = Number(field.max_items || 0);
      const full = limit > 0 && selected.length >= limit;
      const options = clone(field.options || []);
      return `
        <div class="field">
          <span>${escapeHtml(field.label)}${limit ? ` (${selected.length}/${limit})` : ""}</span>
          <div class="entity-list">
            ${options.length
              ? options.map((option) => {
                  const checked = selected.includes(String(option.value));
                  return `
                    <label class="toggle-field">
                      <span>${escapeHtml(option.label)}</span>
                      <input type="checkbox" data-setting-list="${escapeHtml(field.key)}" data-scope="${scope}"
                        value="${escapeHtml(option.value)}" ${checked ? "checked" : ""} ${full && !checked ? "disabled" : ""}>
                    </label>
                  `;
                }).join("")
              : `<small>${escapeHtml(field.empty_label || "Nothing to choose from.")}</small>`}
          </div>
          ${field.description ? `<small>${escapeHtml(field.description)}</small>` : ""}
        </div>
      `;
    }
    if (field.type === "select") {
      const mode = String(values?.wake_detector_mode || "mww_oww");
      const catalogType = ["nww", "mww_nww"].includes(mode) ? "nww" : "oww";
      let options = field.key === "wake_word_catalog_url"
        ? this.wakeWordCatalogOptions(value, "mww")
        : field.key === "oww_wake_word_catalog_url"
          ? this.wakeWordCatalogOptions(value, catalogType)
          : clone(field.options || []);
      if (field.key === "nww_architecture") {
        const available = new Set(
          String(values?.nww_available_architectures || "")
            .split(",")
            .map((item) => item.trim().toLowerCase())
            .filter(Boolean),
        );
        const waitingForBundle =
          String(values?.oww_wake_word || "hey_tater") !== "hey_tater" &&
          available.size === 0;
        options = options.map((option) => ({
          ...option,
          disabled:
            waitingForBundle ||
            (available.size > 0 && !available.has(String(option.value).toLowerCase())),
        }));
      }
      const description =
        field.key === "wake_word_catalog_url"
          ? this.wakeWordCatalogDescription(field, "mww")
          : field.key === "oww_wake_word_catalog_url"
            ? this.wakeWordCatalogDescription(field, catalogType)
          : field.description || "";
      if (PICKER_SETTING_KEYS.has(field.key)) {
        if (inPicker && !options.length) return '<p class="muted">No options are available. Refresh the bridge to try again.</p>';
        if (inPicker) return `<div class="workspace-picker-options">${options.map((option) => `
          <label class="workspace-picker-option" data-picker-text="${escapeHtml(String(option.label).toLowerCase())}" ${!String(option.label).toLowerCase().includes(this._pickerQuery.toLowerCase()) ? "hidden" : ""}>
            <input type="radio" name="workspace-picker" ${common} value="${escapeHtml(option.value)}" ${String(option.value) === String(value) ? "checked" : ""} ${option.disabled ? "disabled" : ""}><span>${escapeHtml(option.label)}${option.disabled ? " — not in bundle" : ""}</span>
          </label>`).join("")}</div>`;
        const selected = options.find((option) => String(option.value) === String(value));
        return `<div class="field workspace-selection"><span>${escapeHtml(field.label)}</span><div class="workspace-selection-row"><strong>${escapeHtml(selected?.label || value || "Choose an option")}</strong><button type="button" data-pick-setting="${escapeHtml(field.key)}" data-pick-scope="${scope}" aria-label="Choose ${escapeHtml(field.label.toLowerCase())}">Choose ${this.renderIcon("arrow-top-right")}</button></div>${description ? `<small>${escapeHtml(description)}</small>` : ""}</div>`;
      }
      return `
        <label class="field">
          <span>${escapeHtml(field.label)}</span>
          <select ${common}>
            ${options.map((option) => `<option value="${escapeHtml(option.value)}" ${String(option.value) === String(value) ? "selected" : ""} ${option.disabled ? "disabled" : ""}>${escapeHtml(option.label)}${option.disabled ? " — not in bundle" : ""}</option>`).join("")}
          </select>
          ${description ? `<small>${escapeHtml(description)}</small>` : ""}
        </label>
      `;
    }
    if (field.type === "wake_model_asset" || field.type === "wake_sound_asset") {
      const kind = field.type === "wake_model_asset" ? "wake_model" : "wake_sound";
      const assets = (this._data.assets || []).filter((row) => row.kind === kind);
      return `
        <label class="field">
          <span>${escapeHtml(field.label)}</span>
          <div class="asset-row">
            <select ${common}>
              <option value="">Use external URL</option>
              ${assets.map((asset) => `<option value="${escapeHtml(asset.id)}" ${asset.id === value ? "selected" : ""}>${escapeHtml(asset.label)}</option>`).join("")}
            </select>
            <button type="button" data-upload-kind="${kind}" data-upload-key="${escapeHtml(field.key)}" data-upload-scope="${escapeHtml(scope)}">Upload</button>
          </div>
        </label>
      `;
    }
    const type =
      field.type === "color"
        ? "color"
        : field.type === "number"
          ? "number"
          : field.type === "time"
            ? "time"
            : "text";
    return `
      <label class="field">
        <span>${escapeHtml(field.label)}</span>
        <input type="${type}" ${common}
          value="${escapeHtml(value)}"
          ${field.min != null ? `min="${field.min}"` : ""}
          ${field.max != null ? `max="${field.max}"` : ""}
          ${field.step != null ? `step="${field.step}"` : ""}
          ${field.placeholder ? `placeholder="${escapeHtml(field.placeholder)}"` : ""}>
      </label>
    `;
  }

  renderFirmware() {
    const catalog = this._data.firmware || {};
    const browserCapability = browserUsbCapability();
    const devices = this._data.devices || [];
    const boardRows = Object.values(catalog.devices || {}).filter(
      (row) => row.browser_usb_supported !== false,
    );
    const boardValues = boardRows.map((row) => String(row.board || row.key));
    if (!boardValues.includes(this._recoveryBoard)) {
      this._recoveryBoard = boardValues[0] || "";
    }
    const recoveryBoardInfo = boardRows.find(
      (row) => String(row.board || row.key) === this._recoveryBoard,
    ) || {};
    if (
      (this._recoveryFlashKind === "ota" && !recoveryBoardInfo.has_ota) ||
      (this._recoveryFlashKind === "factory" && !recoveryBoardInfo.has_factory)
    ) {
      this._recoveryFlashKind = recoveryBoardInfo.has_factory ? "factory" : "ota";
    }
    const keepsSettings = this._recoveryFlashKind === "ota";
    return `
      ${this.renderSectionNavigation([{ id: "updates", label: "Updates" }, { id: "usb", label: "USB recovery" }], this._firmwareSection, "data-firmware-section", "Firmware sections")}
      ${this._firmwareSection === "updates" ? `
      <section class="card section-card">
        <div class="firmware-board">
          <div>
            <h2>Satellite Firmware</h2>
            <div class="muted">Release catalogs: ${escapeHtml(catalog.version || "Unavailable")}</div>
            ${catalog.last_error ? `<div class="banner error">${escapeHtml(catalog.last_error)}</div>` : ""}
          </div>
          <button data-action="refresh-firmware">Check for updates</button>
        </div>
      </section>
      <div class="grid">
        ${devices.map((device) => this.renderFirmwareDevice(device)).join("")}
      </div>
      ` : `
      <section class="card section-card" style="margin-top:14px">
        <h2>Browser USB Flasher</h2>
        <p class="muted">Connect the satellite directly to this computer and use Chrome or Edge to open its USB device picker.</p>
        <p class="muted">Echo devices use their model-specific Echo factory installers. ThirdReality S420 factory installation and recovery use Tater Local USB with the debug board. Their verified Wi-Fi OTA updates appear above.</p>
        <p class="muted">${escapeHtml(browserCapability.message)}</p>
        <div class="firmware-hosted-flasher">
          <span class="firmware-hosted-flasher-copy">
            <strong>Secure Tater USB Flasher</strong>
            <small>Use Tater’s HTTPS website to install the latest Factory or Keep Settings firmware when this Home Assistant page cannot access Browser USB.</small>
          </span>
          <a
            class="firmware-hosted-flasher-link"
            href="${escapeHtml(TATER_HOSTED_USB_FLASHER_URL)}"
            target="_blank"
            rel="noopener noreferrer"
          >Open Web Flasher ↗</a>
        </div>
        <div class="firmware-recovery-grid">
          <div class="firmware-recovery-step">
            <div class="firmware-recovery-step-head"><b>1</b><strong>Choose the satellite hardware</strong></div>
            <label class="field">
              <span>Satellite hardware</span>
              <select data-recovery-board>
                ${boardRows.map((row) => {
                  const board = String(row.board || row.key);
                  return `<option value="${escapeHtml(board)}" ${board === this._recoveryBoard ? "selected" : ""}>${escapeHtml(row.label)} · ${escapeHtml(row.flash_size)}</option>`;
                }).join("")}
              </select>
            </label>
          </div>
          <div class="firmware-recovery-step">
            <div class="firmware-recovery-step-head"><b>2</b><strong>Choose the USB flash type</strong></div>
            <div class="firmware-mode-grid" role="radiogroup" aria-label="USB flash type">
              <button
                class="firmware-mode-option ${this._recoveryFlashKind === "factory" ? "active" : ""}"
                data-recovery-kind="factory"
                role="radio"
                aria-checked="${this._recoveryFlashKind === "factory" ? "true" : "false"}"
                ${recoveryBoardInfo.has_factory ? "" : "disabled"}>
                <span class="firmware-mode-icon">↻</span>
                <span class="firmware-mode-copy"><strong>Factory</strong><small>Fresh installation. Erases Wi-Fi, pairing, and saved settings.</small></span>
              </button>
              <button
                class="firmware-mode-option ${this._recoveryFlashKind === "ota" ? "active" : ""}"
                data-recovery-kind="ota"
                role="radio"
                aria-checked="${this._recoveryFlashKind === "ota" ? "true" : "false"}"
                ${recoveryBoardInfo.has_ota ? "" : "disabled"}>
                <span class="firmware-mode-icon">✓</span>
                <span class="firmware-mode-copy"><strong>OTA Update · Keep Settings</strong><small>Updates over USB without erasing Wi-Fi, pairing, or saved settings.</small></span>
              </button>
            </div>
          </div>
          <div class="firmware-recovery-step">
            <div class="firmware-recovery-step-head"><b>3</b><strong>Prepare the verified installer</strong></div>
            <button class="primary" data-action="prepare-recovery">
              ${keepsSettings ? "Prepare OTA USB Update" : "Prepare Factory USB Installer"}
            </button>
          </div>
        </div>
        ${
          this._recovery?.blobUrl &&
          this._recovery.board === this._recoveryBoard &&
          this._recovery.flashKind === this._recoveryFlashKind
            ? `<div class="firmware-installer-ready"><esp-web-install-button manifest="${escapeHtml(this._recovery.blobUrl)}"></esp-web-install-button><div class="muted" style="margin-top:7px">Select Connect, choose the satellite USB serial port, then follow the ${keepsSettings ? "keep-settings update" : "factory installation"}.</div></div>`
            : ""
        }
      </section>
      `}
    `;
  }

  renderFirmwareDevice(device) {
    const firmware = device.firmware || {};
    return `
      <article class="card">
        <div class="device-head">
          <div><h3>${escapeHtml(device.name)}</h3><div class="muted">${escapeHtml(firmware.label || device.board)}</div></div>
          <span class="badge ${device.connected ? "online" : ""}">${device.connected ? "Online" : "Offline"}</span>
        </div>
        <div class="facts">
          <div class="fact"><label>Installed</label><span>${escapeHtml(device.firmware_version || "Unknown")}</span></div>
          <div class="fact"><label>Available</label><span>${escapeHtml(firmware.firmware_version || "Unknown")}</span></div>
        </div>
        <button class="${firmware.update_available ? "primary" : ""}" data-ota="${escapeHtml(device.device_id)}" ${device.connected && firmware.has_ota ? "" : "disabled"}>
          ${firmware.update_available ? "Install update" : "Reinstall latest"}
        </button>
        ${device.ota?.in_progress ? `<div class="progress"><span style="width:${Number(device.ota.progress || 0)}%"></span></div>` : ""}
      </article>
    `;
  }

  async saveDeviceVolume(input) {
    const deviceId = input.dataset.deviceVolume || "";
    const wrap = input.closest(".device-volume");
    const output = wrap?.querySelector("[data-volume-output]");
    const feedback = wrap?.querySelector("[data-volume-feedback]");
    const previous = Number(input.dataset.volumeLast ?? input.value ?? 80);
    const volume = Math.max(0, Math.min(100, Math.round(Number(input.value || 0))));
    if (!deviceId || input.disabled || volume === previous) return;
    input.disabled = true;
    if (feedback) {
      feedback.textContent = "Saving…";
      feedback.classList.remove("error");
    }
    try {
      const response = await this.api("POST", `settings/device/${deviceId}`, {
        settings: { volume_percent: volume },
      });
      const updated = response?.device;
      if (updated?.device_id) {
        this._data.devices = (this._data.devices || []).map((device) =>
          device.device_id === updated.device_id ? updated : device,
        );
      }
      const savedValue = Math.max(
        0,
        Math.min(100, Math.round(Number(updated?.settings?.volume_percent ?? volume))),
      );
      input.value = String(savedValue);
      input.dataset.volumeLast = String(savedValue);
      wrap?.style.setProperty("--device-volume-progress", `${savedValue}%`);
      if (output) output.textContent = `${savedValue}%`;
      if (feedback) {
        feedback.textContent = "Saved";
        window.setTimeout(() => {
          if (feedback.isConnected && feedback.textContent === "Saved") feedback.textContent = "";
        }, 2200);
      }
    } catch (error) {
      input.value = String(previous);
      wrap?.style.setProperty("--device-volume-progress", `${previous}%`);
      if (output) output.textContent = `${previous}%`;
      if (feedback) {
        feedback.textContent = "Couldn’t save";
        feedback.classList.add("error");
      }
      this._error = `Could not save satellite volume: ${formatApiError(error)}`;
    } finally {
      if (input.isConnected) input.disabled = false;
    }
  }

  bindEvents() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => this.navigate(button.dataset.tab));
    });
    root.querySelector("[data-device-search]")?.addEventListener("input", (event) => {
      this._deviceQuery = event.target.value;
      this.applyDeviceFilter();
    });
    root.querySelector("[data-room-filter]")?.addEventListener("change", (event) => {
      this._roomFilter = event.target.value;
      this.applyDeviceFilter();
    });
    for (const [attribute, property] of [["device-section", "_deviceSection"], ["voice-section", "_voiceSection"], ["firmware-section", "_firmwareSection"]]) {
      root.querySelectorAll(`[data-${attribute}]`).forEach((button) => button.addEventListener("click", () => {
        this[property] = button.getAttribute(`data-${attribute}`);
        this.render();
      }));
    }
    root.querySelectorAll("[data-hydra-section]").forEach((button) => button.addEventListener("click", () => {
      this._hydraSection = button.dataset.hydraSection;
      this.render();
    }));
    root.querySelectorAll("[data-assistant-mode]").forEach((button) => button.addEventListener("click", () => {
      this._taterDraft.assistant_mode = button.dataset.assistantMode;
      this.markDirty("tater");
      this.render();
    }));
    root.querySelectorAll("[data-tater-provider]").forEach((button) => button.addEventListener("click", () => {
      const [kind, provider] = String(button.dataset.taterProvider || "").split(":");
      if (!["stt", "tts"].includes(kind) || !["openai", "wyoming"].includes(provider)) return;
      this._taterDraft[`${kind}_provider`] = provider;
      this.markDirty("tater");
      this.render();
    }));
    root.querySelectorAll("[data-entity-scope]").forEach((button) => button.addEventListener("click", () => {
      this._taterDraft.entity_scope = button.dataset.entityScope;
      this.markDirty("tater");
      this.render();
    }));
    root.querySelectorAll("[data-tater-setting]").forEach((input) => {
      const update = () => {
        let value = input.type === "checkbox" ? input.checked : input.value;
        if (input.type === "number") value = Number(value);
        this._taterDraft[input.dataset.taterSetting] = value;
        this.markDirty("tater");
      };
      input.addEventListener(input.tagName === "TEXTAREA" ? "input" : "change", update);
    });
    root.querySelector("[data-tater-test-message]")?.addEventListener("input", (event) => {
      this._testMessage = event.target.value;
    });
    root.querySelector('[data-action="save-tater"]')?.addEventListener("click", () => {
      const settings = clone(this._taterDraft);
      Object.keys(settings).filter((key) => key.endsWith("_set")).forEach((key) => delete settings[key]);
      this.run(async () => {
        const result = await this.api("POST", "tater/settings", { settings });
        this._data.tater_assistant.settings = result.settings;
        this._taterDraft = clone(result.settings);
      }, "Tater assistant settings saved.", ["tater"]);
    });
    root.querySelector('[data-action="reset-tater-draft"]')?.addEventListener("click", () => {
      this.clearDirty("tater");
      this._taterDraft = clone(this._data.tater_assistant?.settings || {});
      this.render();
    });
    root.querySelector('[data-action="test-tater"]')?.addEventListener("click", () => {
      const text = String(root.querySelector("[data-tater-test-message]")?.value || "").trim();
      if (!text) return;
      this.run(async () => {
        const result = await this.api("POST", "tater/test", { text, conversation_id: this._testConversationId });
        this._testConversationId = result.conversation_id || this._testConversationId;
        this._testMessage = "";
      }, "Tater completed the test turn.");
    });
    root.querySelector('[data-action="clear-hydra-ledger"]')?.addEventListener("click", () => {
      this.confirmAction("Clear Hydra ledger?", "Remove all stored mini-Tater execution records?", "Clear ledger", () => this.run(
        () => this.api("POST", "tater/hydra/clear", { ledger: true, conversations: false }),
        "Hydra ledger cleared.",
      ));
    });
    root.querySelector('[data-action="clear-hydra-conversations"]')?.addEventListener("click", () => {
      this.confirmAction("Clear Tater conversations?", "Remove all stored follow-up context and test messages?", "Clear conversations", () => this.run(
        () => this.api("POST", "tater/hydra/clear", { ledger: false, conversations: true }),
        "Tater conversation data cleared.",
      ));
    });
    for (const [action, dialog] of [["server", "server"], ["new-stereo", "stereo"], ["grouping-help", "groups"]]) {
      root.querySelectorAll(`[data-action="${action}"]`).forEach((button) => button.addEventListener("click", () => {
        this._dialogFocus = button;
        this._dialog = dialog;
        this.render();
      }));
    }
    root.querySelectorAll('[data-action="close-dialog"]').forEach((button) => button.addEventListener("click", () => this.closeDialog()));
    root.querySelector('[data-action="confirm-dialog"]')?.addEventListener("click", () => {
      const action = this._confirmation?.action;
      this._confirmation = null;
      action?.();
    });
    root.querySelector('[data-action="discard-stereo"]')?.addEventListener("click", () => {
      this._stereoDraft = {};
      this.clearDirty("stereo");
      this.render();
    });
    root.querySelector("[data-dialog-backdrop]")?.addEventListener("click", (event) => {
      if (event.target === event.currentTarget) this.closeDialog();
    });
    root.querySelectorAll("[data-pick-setting]").forEach((button) => button.addEventListener("click", () => {
      this._dialogFocus = button;
      this._picker = { key: button.dataset.pickSetting, scope: button.dataset.pickScope };
      this._pickerQuery = "";
      this._dialog = "picker";
      this.render();
    }));
    root.querySelector("[data-picker-search]")?.addEventListener("input", (event) => {
      this._pickerQuery = event.target.value;
      root.querySelectorAll("[data-picker-text]").forEach((option) => { option.hidden = !option.dataset.pickerText.includes(this._pickerQuery.toLowerCase()); });
      const empty = root.querySelector("[data-picker-empty]");
      if (empty) empty.hidden = [...root.querySelectorAll("[data-picker-text]")].some((option) => !option.hidden);
    });
    for (const [attribute, key] of [["name", "name"], ["left", "left"], ["right", "right"], ["left-volume", "leftVolume"], ["right-volume", "rightVolume"], ["left-delay", "leftDelay"], ["right-delay", "rightDelay"]]) {
      root.querySelector(`[data-stereo-${attribute}]`)?.addEventListener("input", (event) => {
        this._stereoDraft[key] = event.target.value;
        this.markDirty("stereo");
      });
    }
    root.querySelectorAll('[data-action="refresh"]').forEach((button) =>
      button.addEventListener("click", () => this.load()),
    );
    root.querySelectorAll('[data-action="pair"]').forEach((button) =>
      button.addEventListener("click", () => {
        this._dialogFocus = button;
        this._dialog = "pairing";
        this.run(async () => {
          const pairing = await this.api("POST", "pairing", {});
          this._data.pairing = pairing;
        }, "Pairing mode started. Enter the code during satellite setup.");
      }),
    );
    root.querySelectorAll('[data-action="bluetooth-pair"]').forEach((button) =>
      button.addEventListener("click", () => {
        const card = button.closest("[data-bluetooth-device]");
        const pin = String(card?.querySelector("[data-bluetooth-pin]")?.value || "").replace(/\D/g, "");
        const satelliteId = String(card?.querySelector("[data-bluetooth-satellite]")?.value || "");
        if (pin.length !== 6) {
          this._error = "Enter the Bluetooth device’s six-digit PIN.";
          this.render();
          return;
        }
        this.run(
          () => this.api("POST", "bluetooth/pair", {
            address: button.dataset.address,
            satellite_id: satelliteId,
            pin,
          }),
          "Bluetooth pairing completed. Home Assistant can now use this Echo for the device.",
        );
      }),
    );
    root.querySelectorAll('[data-action="bluetooth-unpair"]').forEach((button) =>
      button.addEventListener("click", () => {
        this.confirmAction("Unpair Bluetooth device?", `Remove ${button.dataset.address} from this Echo satellite?`, "Unpair device", () => this.run(
          () => this.api("POST", "bluetooth/unpair", {
            address: button.dataset.address,
            satellite_id: button.dataset.satelliteId,
          }),
          "Bluetooth device unpaired.",
        ));
      }),
    );
    root.querySelector('[data-action="save-stereo"]')?.addEventListener("click", () => {
      const value = (selector) => root.querySelector(selector)?.value ?? "";
      const name = String(value("[data-stereo-name]")).trim();
      const left = String(value("[data-stereo-left]"));
      const right = String(value("[data-stereo-right]"));
      if (!name || !left || !right) {
        this._error = "Enter a pair name and choose both satellites.";
        this.render();
        return;
      }
      if (left === right) {
        this._error = "Left and right satellites must be different.";
        this.render();
        return;
      }
      this.run(
        async () => { await this.api("POST", "stereo-pairs", {
          pair: {
            name,
            left_device_id: left,
            right_device_id: right,
            left_volume_percent: Number(value("[data-stereo-left-volume]") || 100),
            right_volume_percent: Number(value("[data-stereo-right-volume]") || 100),
            left_delay_ms: Number(value("[data-stereo-left-delay]") || 0),
            right_delay_ms: Number(value("[data-stereo-right-delay]") || 0),
          },
        }); this._dialog = ""; this._stereoDraft = {}; },
        "Stereo pair created. Its media player is ready in Home Assistant.",
        ["stereo"],
      );
    });
    root.querySelectorAll("[data-remove-stereo]").forEach((button) =>
      button.addEventListener("click", () => {
        this.confirmAction("Delete stereo pair?", "The physical satellite media players remain available.", "Delete pair", () => this.run(
          () => this.api("DELETE", `stereo-pairs/${encodeURIComponent(button.dataset.removeStereo)}`),
          "Stereo pair deleted.",
        ));
      }),
    );
    root.querySelectorAll("[data-device-volume]").forEach((input) => {
      const updateVisual = () => {
        const value = Math.max(0, Math.min(100, Math.round(Number(input.value || 0))));
        const wrap = input.closest(".device-volume");
        const output = wrap?.querySelector("[data-volume-output]");
        wrap?.style.setProperty("--device-volume-progress", `${value}%`);
        if (output) output.textContent = `${value}%`;
      };
      input.addEventListener("input", updateVisual);
      input.addEventListener("change", () => this.saveDeviceVolume(input));
      updateVisual();
    });
    root.querySelectorAll('[data-action="trainer-pair"]').forEach((button) =>
      button.addEventListener("click", () =>
        this.run(async () => {
          const pairing = await this.api("POST", "trainer/pairing", {});
          this._data.trainer_link = {
            ...(this._data.trainer_link || {}),
            pairing,
          };
        }, "Trainer pairing mode started. Enter the code in the trainer’s Auto tab."),
      ),
    );
    root.querySelectorAll('[data-action="trainer-unlink"]').forEach((button) =>
      button.addEventListener("click", () => {
        this.confirmAction("Unlink Wake Word Trainer?", "Publishing stops until the trainer is linked again.", "Unlink trainer", () => this.run(
          () => this.api("POST", "trainer/manage/unlink", {}),
          "Wake Word Trainer unlinked.",
        ));
      }),
    );
    root.querySelectorAll("[data-copy-trainer-code]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(button.dataset.copyTrainerCode || "");
          this._notice = "Trainer pairing code copied.";
        } catch (_error) {
          this._error = "Could not copy the pairing code. Select and copy it manually.";
        }
        this.render();
      }),
    );
    root.querySelectorAll("[data-copy-trainer-url]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(button.dataset.copyTrainerUrl || "");
          this._notice = "Home Assistant address copied.";
        } catch (_error) {
          this._error = "Could not copy the address. Select and copy it manually.";
        }
        this.render();
      }),
    );
    root.querySelectorAll("[data-copy-pairing-code]").forEach((button) => button.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(button.dataset.copyPairingCode || ""); this._notice = "Pairing code copied."; }
      catch { this._error = "Could not copy the pairing code. Select and copy it manually."; }
      this.render();
    }));
    root.querySelectorAll("[data-configure]").forEach((button) =>
      button.addEventListener("click", () => {
        this.prepareDeviceDraft(button.dataset.configure);
        this._deviceSection = "overview";
        this.render();
      }),
    );
    root.querySelectorAll("[data-identify]").forEach((button) =>
      button.addEventListener("click", () =>
        this.run(
          () => this.api("POST", `command/${button.dataset.identify}/identify`, {}),
          "Identify tone sent.",
        ),
      ),
    );
    root.querySelectorAll("[data-forget]").forEach((button) =>
      button.addEventListener("click", () => {
        this.confirmAction("Forget satellite?", "This revokes the saved credential. The satellite must pair again before it can reconnect.", "Forget satellite", () => this.run(
          () => this.api("DELETE", `device/${button.dataset.forget}`),
          "Satellite forgotten. Use a new pairing code to add it again.",
          [`device:${button.dataset.forget}`],
        ));
      }),
    );
    root.querySelectorAll("[data-ota]").forEach((button) =>
      button.addEventListener("click", () => {
        this.confirmAction("Install satellite firmware?", "The board-matched firmware will be installed wirelessly. The satellite restarts after flashing; Wi-Fi and pairing are kept.", "Install firmware", () => this.run(
          () => this.api("POST", `firmware/install/${button.dataset.ota}`, {}),
          "OTA update started. The satellite will reconnect after flashing.",
        ));
      }),
    );
    root.querySelectorAll("[data-sync-settings]").forEach((button) =>
      button.addEventListener("click", () =>
        this.run(
          () => this.api("POST", `command/${button.dataset.syncSettings}/sync-settings`, {}),
          "Live settings sent. Wake-model downloads continue in the background.",
        ),
      ),
    );
    root.querySelectorAll("[data-wake-mode]").forEach((button) =>
      button.addEventListener("click", () => {
        const target = this._wakeDraft;
        if (!target) return;
        const value = String(button.dataset.wakeMode || "mww_oww");
        target.wake_detector_mode = value;
        if (target.oww_wake_word === "catalog") {
          const catalogType = ["nww", "mww_nww"].includes(value) ? "nww" : "oww";
          const selected = this.wakeWordCatalogOptions("", catalogType).find((option) => option.value);
          target.oww_wake_word_catalog_url = selected?.value || "";
          target.oww_wake_word_url = selected?.value || "";
          target.nww_available_architectures = (selected?.architectures || []).join(",");
        }
        this.markDirty("wake");
        this.render();
      }),
    );
    root.querySelectorAll("[data-setting-list]").forEach((input) =>
      input.addEventListener("change", () => {
        const target = {
          global: this._globalDraft,
          wake: this._wakeDraft,
        }[input.dataset.scope] || this._deviceDraft;
        const key = input.dataset.settingList;
        target[key] = [...root.querySelectorAll("[data-setting-list]")]
          .filter((item) => item.dataset.settingList === key && item.checked)
          .map((item) => item.value)
          .join(",");
        this.markDirty(input.dataset.scope, key);
        this.render();
      }),
    );
    root.querySelectorAll("[data-reset-setting]").forEach((button) =>
      button.addEventListener("click", () => {
        const target = {
          global: this._globalDraft,
          wake: this._wakeDraft,
        }[button.dataset.resetScope] || this._deviceDraft;
        target[button.dataset.resetSetting] = Number(button.dataset.resetValue);
        this.markDirty(button.dataset.resetScope, button.dataset.resetSetting);
        this.render();
      }),
    );
    root.querySelectorAll("[data-setting]").forEach((input) => {
      input.addEventListener("change", () => {
        const target = {
          global: this._globalDraft,
          wake: this._wakeDraft,
        }[input.dataset.scope] || this._deviceDraft;
        let value = input.type === "checkbox" ? input.checked : input.value;
        if (input.type === "number" || input.type === "range") value = Number(value);
        target[input.dataset.setting] = value;
        if (input.dataset.setting === "wake_word") {
          if (value === "catalog") {
            const catalogUrl =
              target.wake_word_catalog_url ||
              this.wakeWordCatalogOptions()[0]?.value ||
              "";
            target.wake_word_catalog_url = catalogUrl;
            target.wake_word_url = catalogUrl;
            target.wake_model_asset_id = "";
          } else if (value === "custom_url") {
            if (isWakeWordCatalogUrl(target.wake_word_url)) {
              target.wake_word_url = "";
            }
            target.wake_word_catalog_url = "";
          } else {
            target.wake_word_catalog_url = "";
            target.wake_word_url = "";
            target.wake_model_asset_id = "";
            target.wake_model_revision = "";
          }
        } else if (input.dataset.setting === "wake_word_catalog_url") {
          target.wake_word = "catalog";
          target.wake_word_url = value;
          target.wake_model_asset_id = "";
        } else if (input.dataset.setting === "oww_wake_word") {
          if (value === "catalog") {
            const catalogType = ["nww", "mww_nww"].includes(String(target.wake_detector_mode)) ? "nww" : "oww";
            const selected = this.wakeWordCatalogOptions("", catalogType).find((option) => option.value);
            target.oww_wake_word_catalog_url = selected?.value || "";
            target.oww_wake_word_url = selected?.value || "";
            target.nww_available_architectures = (selected?.architectures || []).join(",");
          } else if (value === "custom_url") {
            target.oww_wake_word_catalog_url = "";
            target.oww_wake_word_url = "";
            target.nww_available_architectures = "";
          } else {
            target.oww_wake_word_catalog_url = "";
            target.oww_wake_word_url = "";
            target.nww_available_architectures = "cnn,gru";
          }
        } else if (input.dataset.setting === "oww_wake_word_catalog_url") {
          const catalogType = ["nww", "mww_nww"].includes(String(target.wake_detector_mode)) ? "nww" : "oww";
          const selected = this.wakeWordCatalogOptions(value, catalogType).find(
            (option) => String(option.value) === String(value),
          );
          target.oww_wake_word = "catalog";
          target.oww_wake_word_url = value;
          target.nww_available_architectures = (selected?.architectures || []).join(",");
        } else if (input.dataset.setting === "wake_detector_mode") {
          if (target.oww_wake_word === "catalog") {
            const catalogType = ["nww", "mww_nww"].includes(String(value)) ? "nww" : "oww";
            const selected = this.wakeWordCatalogOptions("", catalogType).find((option) => option.value);
            target.oww_wake_word_catalog_url = selected?.value || "";
            target.oww_wake_word_url = selected?.value || "";
            target.nww_available_architectures = (selected?.architectures || []).join(",");
          }
        }
        this.markDirty(input.dataset.scope, input.dataset.setting);
        if (input.type === "radio" && this._dialog === "picker") { this.closeDialog(); return; }
        const controlsConditionalFields = (this._data.settings_schema || []).some(
          (section) =>
            (section.fields || []).some(
              (field) => field.show_when?.key === input.dataset.setting,
            ),
        );
        if (
          controlsConditionalFields ||
          ["wake_word", "wake_detector_mode", "oww_wake_word", "oww_wake_word_catalog_url", "nww_architecture", "mww_tuning_override_enabled", "oww_tuning_override_enabled", "nww_tuning_override_enabled", "wake_sound", "aec_enabled", "wake_verifier_mode", "wake_verifier_threshold"].includes(
            input.dataset.setting,
          )
        ) {
          this.render();
        }
      });
    });
    root.querySelector('[data-special="pipeline"]')?.addEventListener("change", (event) => {
      this._pipelineDraft = event.target.value;
      this.markDirty("device");
    });
    root.querySelectorAll("[data-upload-kind]").forEach((button) =>
      button.addEventListener("click", () => this.uploadAsset(button)),
    );
    root.querySelector('[data-action="save-global"]')?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "settings/global", {
          settings: pickSettings(this._globalDraft, VOICE_DEFAULT_SETTING_KEYS),
        }),
        "Shared satellite settings saved and pushed live.",
        ["global"],
      ),
    );
    root.querySelector('[data-action="save-trainer"]')?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "settings/trainer", {
          settings: pickSettings(this._globalDraft, TRAINER_SETTING_KEYS),
        }),
        "Trainer settings saved and pushed live.",
        ["trainer"],
      ),
    );
    root.querySelector('[data-action="save-verifier"]')?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "settings/verifier", {
          settings: pickSettings(this._globalDraft, WAKE_VERIFIER_SETTING_KEYS),
        }),
        "STT wake verification updated for all satellites.",
        ["verifier"],
      ),
    );
    root.querySelector("[data-save-shared-wake]")?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "settings/wake", { settings: this._wakeDraft }),
        "Wake settings saved and pushed to all satellites.",
        ["wake"],
      ),
    );
    root.querySelector("[data-reset-shared-wake]")?.addEventListener("click", () => {
      const values =
        this._data.shared_wake_settings ||
        this._data.wake_family_settings?.echo ||
        this._data.wake_family_settings?.mww ||
        {};
      this._wakeDraft = this.prepareSettingsDraft(values);
      this.clearDirty("wake");
      this.render();
    });
    root.querySelector('[data-action="reset-draft"]')?.addEventListener("click", () => {
      const scope = { trainer: "trainer", verifier: "verifier" }[this._tab] || "global";
      this.clearDirty(scope);
      this.syncDrafts(this._data);
      this.render();
    });
    root.querySelector('[data-action="save-device"]')?.addEventListener("click", () => {
      const changes = {};
      Object.entries(this._deviceDraft || {}).forEach(([key, value]) => {
        if (JSON.stringify(value) !== JSON.stringify(this._deviceOriginal?.[key])) changes[key] = value;
      });
      this.run(
        () =>
          this.api("POST", `settings/device/${this._selectedDeviceId}`, {
            settings: changes,
            pipeline_id: this._pipelineDraft,
          }),
        "Satellite overrides saved and pushed live.",
        ["device"],
      );
    });
    root.querySelector('[data-action="reset-device"]')?.addEventListener("click", () => {
      this.confirmAction("Use all shared defaults?", "Remove all firmware setting overrides from this satellite?", "Use shared defaults", () => this.run(
        () => this.api("POST", `settings/device/${this._selectedDeviceId}/reset`, {}),
        "Satellite now follows all shared defaults.",
        ["device"],
      ));
    });
    root.querySelector('[data-action="back"]')?.addEventListener("click", () => {
      this.navigate("satellites");
    });
    root.querySelector('[data-action="refresh-firmware"]')?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "firmware/refresh", {}),
        "Firmware catalog refreshed.",
      ),
    );
    const recoveryBoard = root.querySelector("[data-recovery-board]");
    recoveryBoard?.addEventListener("change", () => {
      this._recoveryBoard = recoveryBoard.value;
      if (this._recovery && this._recovery.board !== this._recoveryBoard) {
        if (this._recovery.blobUrl) URL.revokeObjectURL(this._recovery.blobUrl);
        this._recovery = null;
      }
      this.render();
    });
    root.querySelectorAll("[data-recovery-kind]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) return;
        const flashKind = button.dataset.recoveryKind === "ota" ? "ota" : "factory";
        this._recoveryFlashKind = flashKind;
        if (this._recovery && this._recovery.flashKind !== flashKind) {
          if (this._recovery.blobUrl) URL.revokeObjectURL(this._recovery.blobUrl);
          this._recovery = null;
        }
        this.render();
      });
    });
    root.querySelector('[data-action="prepare-recovery"]')?.addEventListener("click", () =>
      this.prepareRecovery(),
    );
  }

  async uploadAsset(button) {
    const kind = button.dataset.uploadKind;
    const settingKey = button.dataset.uploadKey;
    const scope = button.dataset.uploadScope || (this._tab === "defaults" ? "global" : "device");
    const accept = kind === "wake_model" ? ".tflite,application/octet-stream" : ".wav,audio/wav";
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = accept;
    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      if (!file) return;
      const label = prompt("Name this wake asset", file.name.replace(/\.[^.]+$/, "")) || "";
      if (!label) return;
      const scopeKey = this.settingScope(scope, settingKey);
      const deviceId = this._selectedDeviceId;
      this.markDirty(scope, settingKey);
      this._error = "";
      this._notice = "";
      this._loading = true;
      this.render();
      try {
        const result = await this.api("POST", "assets", {
          kind,
          filename: file.name,
          label,
          data_b64: await fileToBase64(file),
        });
        this._loading = false;
        await this.load(true);
        const targets = scope === "device"
          ? [deviceId === this._selectedDeviceId ? this._deviceDraft : null, this._deviceDrafts.get(deviceId)?.draft]
          : [{ wake: this._wakeDraft, global: this._globalDraft }[scope]];
        targets.filter(Boolean).forEach((target) => {
          target[settingKey] = result.asset.id;
          if (kind === "wake_model") target.wake_word = "custom_url";
          if (kind === "wake_sound") target.wake_sound = "custom";
        });
        this._dirtyScopes.add(scopeKey);
        this._dirty = true;
        this._notice = `${label} uploaded. Save settings to publish it to satellites.`;
        this.render();
      } catch (error) {
        this._error = formatApiError(error);
        this._loading = false;
        this.render();
      }
    });
    picker.click();
  }

  async prepareRecovery() {
    const board = this.shadowRoot.querySelector("[data-recovery-board]")?.value;
    if (!board) return;
    this._recoveryBoard = board;
    const flashKind = this._recoveryFlashKind === "ota" ? "ota" : "factory";
    await this.run(async () => {
      const capability = browserUsbCapability();
      if (!capability.available) throw new Error(capability.message);
      const result = await this.api("POST", `firmware/recovery/${encodeURIComponent(board)}`, {
        flash_kind: flashKind,
      });
      if (this._recovery?.blobUrl) URL.revokeObjectURL(this._recovery.blobUrl);
      const blob = new Blob([JSON.stringify(result.manifest)], { type: "application/json" });
      this._recovery = { board, flashKind, blobUrl: URL.createObjectURL(blob) };
      const sources = [
        "https://unpkg.com/esp-web-tools@10/dist/web/install-button.js?module",
        "https://cdn.jsdelivr.net/npm/esp-web-tools@10/dist/web/install-button.js",
      ];
      let loaded = customElements.get("esp-web-install-button");
      for (const source of sources) {
        if (loaded) break;
        try {
          await import(source);
          loaded = customElements.get("esp-web-install-button");
        } catch (_error) {
          // Try the next CDN.
        }
      }
      if (!loaded) throw new Error("The browser USB installer could not be loaded.");
    }, flashKind === "ota"
      ? "Verified OTA firmware is ready for a USB update that keeps settings."
      : "Verified factory firmware is ready for browser USB recovery.");
  }
}

if (!customElements.get(PANEL_ELEMENT_NAME)) {
  customElements.define(PANEL_ELEMENT_NAME, TaterSatellitePanel);
}
