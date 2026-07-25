const API = "tater/satellite/v1";
const ACCENT = "#ff5a1f";

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const clone = (value) => JSON.parse(JSON.stringify(value ?? {}));

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
    this._globalDraft = null;
    this._deviceDraft = null;
    this._deviceOriginal = null;
    this._pipelineDraft = "";
    this._vadDraft = "default";
    this._dirty = false;
    this._loading = false;
    this._recovery = null;
    this._pollTimer = null;
  }

  set hass(value) {
    this._hass = value;
    if (!this._data && !this._loading) this.load();
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    if (this._hass && !this._data) this.load();
    if (!this._pollTimer) {
      this._pollTimer = window.setInterval(() => {
        if (!document.hidden && !this._dirty) this.load(true);
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

  async load(background = false) {
    if (this._loading) return;
    this._loading = true;
    if (!background) this.render();
    try {
      const data = await this.api("GET", "manage");
      this._data = data;
      this._error = "";
      if (!this._globalDraft || !this._dirty) {
        this._globalDraft = clone(data.global_settings);
      }
      if (this._selectedDeviceId && !this._dirty) {
        this.prepareDeviceDraft(this._selectedDeviceId, false);
      }
    } catch (error) {
      this._error = error?.message || String(error);
    } finally {
      this._loading = false;
      this.render();
    }
  }

  async run(action, successMessage = "") {
    this._error = "";
    this._notice = "";
    this._loading = true;
    this.render();
    try {
      await action();
      this._notice = successMessage;
      this._dirty = false;
      this._loading = false;
      await this.load(true);
    } catch (error) {
      this._error = error?.message || String(error);
      this._loading = false;
      this.render();
    }
  }

  render() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <style>${this.styles()}</style>
      <main>
        ${this.renderHeader()}
        ${this._error ? `<div class="banner error">${escapeHtml(this._error)}</div>` : ""}
        ${this._notice ? `<div class="banner success">${escapeHtml(this._notice)}</div>` : ""}
        ${!this._data ? this.renderLoading() : this.renderBody()}
      </main>
    `;
    this.bindEvents();
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
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; }
      .device-card { position: relative; overflow: hidden; }
      .device-card::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--divider-color); }
      .device-card.online::before { background: var(--tater-accent); }
      .device-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
      .badges { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0 13px; }
      .badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 999px; background: var(--secondary-background-color); font-size: 12px; }
      .badge.online { color: #228b50; background: color-mix(in srgb, #2eae67 14%, transparent); }
      .badge.update { color: var(--tater-accent); background: var(--tater-accent-soft); }
      .facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; margin: 12px 0 16px; }
      .fact label { display: block; color: var(--secondary-text-color); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
      .fact span { display: block; margin-top: 2px; overflow-wrap: anywhere; }
      .section-card { margin-bottom: 14px; }
      .section-description { color: var(--secondary-text-color); margin-bottom: 15px; font-size: 14px; }
      .settings-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(245px, 1fr)); gap: 13px; }
      .field { display: flex; flex-direction: column; gap: 6px; }
      .field > span { font-size: 13px; font-weight: 600; }
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
      .toggle-field { flex-direction: row; align-items: center; justify-content: space-between; min-height: 42px; padding: 8px 10px; border: 1px solid var(--divider-color); border-radius: 9px; }
      .toggle-field input { width: 42px; min-height: 22px; accent-color: var(--tater-accent); }
      .asset-row { display: grid; grid-template-columns: 1fr auto; gap: 7px; }
      .editor-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 15px; }
      .sticky-actions { position: sticky; bottom: 12px; z-index: 3; margin-top: 15px; padding: 12px; display: flex; justify-content: flex-end; gap: 9px; background: color-mix(in srgb, var(--card-background-color) 92%, transparent); backdrop-filter: blur(8px); border: 1px solid var(--divider-color); border-radius: 12px; }
      .firmware-board { display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center; }
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
        .pair-code { font-size: 25px; }
        .facts { grid-template-columns: 1fr; }
      }
    `;
  }

  renderHeader() {
    return `
      <div class="topbar">
        <div>
          <h1>Tater Satellites</h1>
          <div class="muted">Tater Native voice satellites connected directly to Home Assistant Assist.</div>
        </div>
        <div class="top-actions">
          <button data-action="refresh" ${this._loading ? "disabled" : ""}>Refresh</button>
          <button class="primary" data-action="pair" ${this._loading ? "disabled" : ""}>Add Satellite</button>
        </div>
      </div>
    `;
  }

  renderLoading() {
    return `<div class="spinner"></div>`;
  }

  renderBody() {
    const pairing = this._data.pairing || {};
    return `
      <section class="card pair-card">
        <div>
          <h3>Satellite server</h3>
          <div class="server">${escapeHtml(this._data.server_address)}${escapeHtml(this._data.websocket_path)}</div>
          <div class="muted" style="margin-top:6px">Use the Home Assistant address as the server during satellite setup. The firmware adds the WebSocket path automatically.</div>
        </div>
        <div>
          ${
            pairing.active
              ? `<div class="muted">Pairing code</div><div class="pair-code">${escapeHtml(pairing.code)}</div>`
              : `<button class="primary" data-action="pair">Generate pairing code</button>`
          }
        </div>
      </section>
      <nav class="tabs">
        ${this.tabButton("satellites", "Satellites")}
        ${this.tabButton("defaults", "Voice Defaults")}
        ${this.tabButton("trainer", "Wake Word Trainer")}
        ${this.tabButton("firmware", "Firmware & Recovery")}
      </nav>
      ${this._tab === "defaults" ? this.renderSettingsEditor("Shared Satellite Voice Settings", this._globalDraft, "global", { exclude: ["feedback"] }) : ""}
      ${this._tab === "trainer" ? this.renderTrainer() : ""}
      ${this._tab === "firmware" ? this.renderFirmware() : ""}
      ${this._tab === "satellites" ? this.renderSatellites() : ""}
    `;
  }

  tabButton(key, label) {
    return `<button class="tab ${this._tab === key ? "active" : ""}" data-tab="${key}">${label}</button>`;
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
    return `<div class="grid">${devices.map((device) => this.renderDeviceCard(device)).join("")}</div>`;
  }

  renderDeviceCard(device) {
    const firmware = device.firmware || {};
    return `
      <article class="card device-card ${device.connected ? "online" : ""}">
        <div class="device-head">
          <div>
            <h2>${escapeHtml(device.name)}</h2>
            <div class="muted">${escapeHtml(firmware.label || device.board)}</div>
          </div>
          <span class="badge ${device.connected ? "online" : ""}">${device.connected ? "Online" : "Offline"}</span>
        </div>
        <div class="badges">
          <span class="badge">${escapeHtml(device.state || "offline")}</span>
          ${firmware.update_available ? `<span class="badge update">Update available</span>` : ""}
          ${device.room ? `<span class="badge">${escapeHtml(device.room)}</span>` : ""}
        </div>
        <div class="facts">
          <div class="fact"><label>Firmware</label><span>${escapeHtml(device.firmware_version || "Unknown")}</span></div>
          <div class="fact"><label>Wi-Fi</label><span>${device.wifi_rssi ?? "—"}${device.wifi_rssi != null ? " dBm" : ""}</span></div>
          <div class="fact"><label>Free memory</label><span>${formatBytes(device.free_heap)}</span></div>
          <div class="fact"><label>Last seen</label><span>${formatAge(device.last_seen)}</span></div>
        </div>
        <div class="row-actions">
          <button class="primary" data-configure="${escapeHtml(device.device_id)}">Configure</button>
          <button data-identify="${escapeHtml(device.device_id)}" ${device.connected ? "" : "disabled"}>Identify</button>
          ${
            firmware.has_ota && device.connected
              ? `<button data-ota="${escapeHtml(device.device_id)}">${firmware.update_available ? "Update" : "Reinstall"}</button>`
              : ""
          }
          ${!device.connected ? `<button class="danger" data-forget="${escapeHtml(device.device_id)}">Forget</button>` : ""}
        </div>
        ${
          device.ota?.in_progress
            ? `<div class="progress"><span style="width:${Number(device.ota.progress || 0)}%"></span></div><div class="muted" style="margin-top:6px">${escapeHtml(device.ota.message || "Updating…")}</div>`
            : ""
        }
      </article>
    `;
  }

  prepareDeviceDraft(deviceId, markDirty = false) {
    const device = (this._data?.devices || []).find((row) => row.device_id === deviceId);
    if (!device) return;
    this._selectedDeviceId = deviceId;
    this._deviceDraft = clone(device.settings);
    this._deviceOriginal = clone(device.settings);
    this._pipelineDraft = device.pipeline_id || "";
    this._vadDraft = device.vad_sensitivity || "default";
    this._dirty = markDirty;
  }

  renderDeviceEditor(device) {
    const pipelines = this._data.pipelines || [];
    return `
      <div class="editor-head">
        <div>
          <button data-action="back">← All satellites</button>
          <h2 style="margin-top:15px">${escapeHtml(device.name)}</h2>
          <div class="muted">Settings here override the shared Voice Defaults only for this satellite.</div>
        </div>
        <span class="badge ${device.connected ? "online" : ""}">${device.connected ? "Online" : "Offline"}</span>
      </div>
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
          <label class="field">
            <span>End-of-speech sensitivity</span>
            <select data-special="vad">
              ${["default", "relaxed", "aggressive"].map((value) => `<option value="${value}" ${value === this._vadDraft ? "selected" : ""}>${value[0].toUpperCase()}${value.slice(1)}</option>`).join("")}
            </select>
          </label>
        </div>
      </section>
      ${this.renderSettingsSections(this._deviceDraft, "device", device)}
      ${this.renderDeviceDiagnostics(device)}
      <div class="sticky-actions">
        <button data-action="reset-device">Use all shared defaults</button>
        <button class="primary" data-action="save-device" ${this._loading ? "disabled" : ""}>Save satellite</button>
      </div>
    `;
  }

  renderDeviceDiagnostics(device) {
    const xmos = device.xmos_firmware || {};
    const transport = device.transport || {};
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
          <div class="fact"><label>XMOS firmware</label><span>${escapeHtml(xmos.installed_version || "Not reported")}</span></div>
          <div class="fact"><label>TX queue</label><span>${escapeHtml(transport.audio_tx_queue_depth ?? "—")}</span></div>
        </div>
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
          <div class="muted">Changes are pushed live to every connected satellite. Device overrides remain intact.</div>
        </div>
      </div>
      ${this.renderSettingsSections(values || {}, scope, null, sectionFilter)}
      <div class="sticky-actions">
        <button data-action="reset-draft">Discard changes</button>
        <button class="primary" data-action="save-global" ${this._loading ? "disabled" : ""}>Save and update all</button>
      </div>
    `;
  }

  renderSettingsSections(values, scope, device = null, sectionFilter = {}) {
    const boardKey = String(device?.board_key || device?.board || "")
      .trim()
      .toLowerCase()
      .replaceAll("-", "_");
    return (this._data.settings_schema || [])
      .filter((section) => !section.scopes || section.scopes.includes(scope))
      .filter((section) => !(section.exclude_boards || []).includes(boardKey))
      .filter((section) => !(sectionFilter.exclude || []).includes(section.section))
      .filter((section) => !(sectionFilter.include || []).length || sectionFilter.include.includes(section.section))
      .map(
        (section) => `
          <section class="card section-card">
            <h3>${escapeHtml(section.title)}</h3>
            <div class="section-description">${escapeHtml(section.description || "")}</div>
            <div class="settings-grid">
              ${(section.fields || [])
                .filter((field) => this.fieldVisible(field, values))
                .map((field) => this.renderField(field, values, scope))
                .join("")}
            </div>
          </section>
        `,
      )
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
      <div class="sticky-actions">
        <button data-action="reset-draft">Discard changes</button>
        <button class="primary" data-action="save-global" ${this._loading ? "disabled" : ""}>Save trainer settings</button>
      </div>
    `;
  }

  fieldVisible(field, values) {
    const condition = field.show_when;
    if (!condition) return true;
    return values?.[condition.key] === condition.equals;
  }

  renderField(field, values, scope) {
    const value = values?.[field.key] ?? "";
    const common = `data-setting="${escapeHtml(field.key)}" data-scope="${scope}"`;
    if (field.type === "boolean") {
      return `
        <label class="toggle-field">
          <span>${escapeHtml(field.label)}</span>
          <input type="checkbox" ${common} ${value ? "checked" : ""}>
        </label>
      `;
    }
    if (field.type === "select") {
      return `
        <label class="field">
          <span>${escapeHtml(field.label)}</span>
          <select ${common}>
            ${(field.options || []).map((option) => `<option value="${escapeHtml(option.value)}" ${String(option.value) === String(value) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}
          </select>
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
            <button type="button" data-upload-kind="${kind}" data-upload-key="${escapeHtml(field.key)}">Upload</button>
          </div>
        </label>
      `;
    }
    const type = field.type === "color" ? "color" : field.type === "number" ? "number" : "text";
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
    const devices = this._data.devices || [];
    const boardRows = Object.values(catalog.devices || {});
    return `
      <section class="card section-card">
        <div class="firmware-board">
          <div>
            <h2>Native Firmware</h2>
            <div class="muted">Latest release: ${escapeHtml(catalog.version || "Unavailable")}</div>
            ${catalog.last_error ? `<div class="banner error">${escapeHtml(catalog.last_error)}</div>` : ""}
          </div>
          <button data-action="refresh-firmware">Check for updates</button>
        </div>
      </section>
      <div class="grid">
        ${devices.map((device) => this.renderFirmwareDevice(device)).join("")}
      </div>
      <section class="card section-card" style="margin-top:14px">
        <h2>Browser USB Recovery</h2>
        <p class="muted">Use this for first flash or recovery. Web Serial requires Chrome or Edge on a secure Home Assistant connection.</p>
        <div class="settings-grid">
          <label class="field">
            <span>Satellite hardware</span>
            <select data-recovery-board>
              ${boardRows.map((row) => `<option value="${escapeHtml(row.board || row.key)}">${escapeHtml(row.label)} · ${escapeHtml(row.flash_size)}</option>`).join("")}
            </select>
          </label>
          <div class="field">
            <span>Factory installer</span>
            <button class="primary" data-action="prepare-recovery">Prepare USB installer</button>
          </div>
        </div>
        ${
          this._recovery?.blobUrl
            ? `<div style="margin-top:16px"><esp-web-install-button manifest="${escapeHtml(this._recovery.blobUrl)}"></esp-web-install-button><div class="muted" style="margin-top:7px">Select Connect, choose the satellite USB serial port, then follow the installer.</div></div>`
            : ""
        }
      </section>
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

  bindEvents() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        this._tab = button.dataset.tab;
        this._selectedDeviceId = "";
        this._dirty = false;
        this.render();
      });
    });
    root.querySelectorAll('[data-action="refresh"]').forEach((button) =>
      button.addEventListener("click", () => this.load()),
    );
    root.querySelectorAll('[data-action="pair"]').forEach((button) =>
      button.addEventListener("click", () =>
        this.run(async () => {
          const pairing = await this.api("POST", "pairing", {});
          this._data.pairing = pairing;
        }, "Pairing mode started. Enter the code during satellite setup."),
      ),
    );
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
        if (!confirm("Unlink this Wake Word Trainer? Publishing will stop until it is linked again.")) return;
        this.run(
          () => this.api("POST", "trainer/manage/unlink", {}),
          "Wake Word Trainer unlinked.",
        );
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
    root.querySelectorAll("[data-configure]").forEach((button) =>
      button.addEventListener("click", () => {
        this.prepareDeviceDraft(button.dataset.configure);
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
        if (!confirm("Forget this offline satellite and revoke its saved credential?")) return;
        this.run(
          () => this.api("DELETE", `device/${button.dataset.forget}`),
          "Satellite forgotten. Use a new pairing code to add it again.",
        );
      }),
    );
    root.querySelectorAll("[data-ota]").forEach((button) =>
      button.addEventListener("click", () => {
        if (!confirm("Install the board-matched Tater Native OTA image now?")) return;
        this.run(
          () => this.api("POST", `firmware/install/${button.dataset.ota}`, {}),
          "OTA update started. The satellite will reconnect after flashing.",
        );
      }),
    );
    root.querySelectorAll("[data-setting]").forEach((input) => {
      input.addEventListener("change", () => {
        const target = input.dataset.scope === "global" ? this._globalDraft : this._deviceDraft;
        let value = input.type === "checkbox" ? input.checked : input.value;
        if (input.type === "number") value = Number(value);
        target[input.dataset.setting] = value;
        this._dirty = true;
        if (["wake_word", "wake_sound", "aec_enabled"].includes(input.dataset.setting)) this.render();
      });
    });
    root.querySelector('[data-special="pipeline"]')?.addEventListener("change", (event) => {
      this._pipelineDraft = event.target.value;
      this._dirty = true;
    });
    root.querySelector('[data-special="vad"]')?.addEventListener("change", (event) => {
      this._vadDraft = event.target.value;
      this._dirty = true;
    });
    root.querySelectorAll("[data-upload-kind]").forEach((button) =>
      button.addEventListener("click", () => this.uploadAsset(button)),
    );
    root.querySelector('[data-action="save-global"]')?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "settings/global", { settings: this._globalDraft }),
        "Shared satellite settings saved and pushed live.",
      ),
    );
    root.querySelector('[data-action="reset-draft"]')?.addEventListener("click", () => {
      this._globalDraft = clone(this._data.global_settings);
      this._dirty = false;
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
            vad_sensitivity: this._vadDraft,
          }),
        "Satellite overrides saved and pushed live.",
      );
    });
    root.querySelector('[data-action="reset-device"]')?.addEventListener("click", () => {
      if (!confirm("Remove all firmware setting overrides from this satellite?")) return;
      this.run(
        () => this.api("POST", `settings/device/${this._selectedDeviceId}/reset`, {}),
        "Satellite now follows all shared defaults.",
      );
    });
    root.querySelector('[data-action="back"]')?.addEventListener("click", () => {
      this._selectedDeviceId = "";
      this._deviceDraft = null;
      this._dirty = false;
      this.render();
    });
    root.querySelector('[data-action="refresh-firmware"]')?.addEventListener("click", () =>
      this.run(
        () => this.api("POST", "firmware/refresh", {}),
        "Firmware catalog refreshed.",
      ),
    );
    root.querySelector('[data-action="prepare-recovery"]')?.addEventListener("click", () =>
      this.prepareRecovery(),
    );
  }

  async uploadAsset(button) {
    const kind = button.dataset.uploadKind;
    const settingKey = button.dataset.uploadKey;
    const scope = this._tab === "defaults" ? "global" : "device";
    const accept = kind === "wake_model" ? ".tflite,application/octet-stream" : ".wav,audio/wav";
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = accept;
    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      if (!file) return;
      const label = prompt("Name this wake asset", file.name.replace(/\.[^.]+$/, "")) || "";
      if (!label) return;
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
        this._dirty = false;
        await this.load(true);
        const target = scope === "global" ? this._globalDraft : this._deviceDraft;
        target[settingKey] = result.asset.id;
        if (kind === "wake_model") target.wake_word = "custom_url";
        if (kind === "wake_sound") target.wake_sound = "custom";
        this._dirty = true;
        this._notice = `${label} uploaded. Save settings to publish it to satellites.`;
        this.render();
      } catch (error) {
        this._error = error?.message || String(error);
        this._loading = false;
        this.render();
      }
    });
    picker.click();
  }

  async prepareRecovery() {
    const board = this.shadowRoot.querySelector("[data-recovery-board]")?.value;
    if (!board) return;
    await this.run(async () => {
      const result = await this.api("POST", `firmware/recovery/${encodeURIComponent(board)}`, {});
      if (this._recovery?.blobUrl) URL.revokeObjectURL(this._recovery.blobUrl);
      const blob = new Blob([JSON.stringify(result.manifest)], { type: "application/json" });
      this._recovery = { blobUrl: URL.createObjectURL(blob) };
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
    }, "Verified factory firmware is ready for browser USB recovery.");
  }
}

if (!customElements.get("tater-satellite-panel")) {
  customElements.define("tater-satellite-panel", TaterSatellitePanel);
}
