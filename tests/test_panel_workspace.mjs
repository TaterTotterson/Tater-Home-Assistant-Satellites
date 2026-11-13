import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

globalThis.HTMLElement = class {
  attachShadow() { this.shadowRoot = { querySelectorAll: () => [], querySelector: () => null }; }
};
globalThis.window = { isSecureContext: true };
let Panel;
globalThis.customElements = { get: () => undefined, define: (_, value) => { Panel = value; } };
await import(pathToFileURL(process.argv[2]).href);
const settings = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const copy = value => structuredClone(value);
function fixture() {
  const panel = new Panel();
  const device = (id, board) => ({ device_id: id, name: id, board, board_key: board, connected: true, settings: copy(settings.defaults), capabilities: { speaker: true, output_chain: 1, do_not_disturb: 1, screen_power_management: 1, screen_clock_format: 1, screen_climate: 1 }, wake_family: 'echo', firmware: {} });
  panel._data = { global_settings: copy(settings.defaults), shared_wake_settings: copy(settings.defaults), settings_schema: copy(settings.schema), devices: [device('one', 'crown'), device('two', 'satellite1')], pipelines: [], tater_assistant: { settings: { assistant_mode: 'home_assistant', llm_base_url: 'https://api.openai.com/v1', llm_model: '', llm_api_key_set: false, stt_provider: 'openai', stt_base_url: 'https://api.openai.com/v1', stt_model: 'gpt-4o-transcribe', stt_api_key_set: false, vad_backend: 'micro', tts_provider: 'openai', tts_base_url: 'https://api.openai.com/v1', tts_model: 'gpt-4o-tts', tts_voice: 'alloy', tts_api_key_set: false, entity_scope: 'exposed', assistant_name: 'Tater', personality: 'Warm', max_display: 8, max_store: 20, max_llm: 8, hydra_max_ledger_items: 1500, hydra_astraeus_plan_review_enabled: true, hydra_auto_continue_incomplete_final_enabled: false }, ready: { ok: true, missing: [] }, home_control: { entity_count: 2, areas: 1, domains: ['light'], examples: [{ entity_id: 'light.kitchen', name: 'Kitchen', area: 'Kitchen', state: 'off', domain: 'light' }] }, metrics: {}, ledger: [], messages: [] } };
  panel.syncDrafts(panel._data);
  panel.render = () => {};
  return panel;
}
function controls(panel, selectors) {
  panel.shadowRoot = { querySelectorAll: () => [], querySelector: selector => selectors[selector] || null };
  for (const control of Object.values(selectors)) {
    control.listeners = {};
    control.addEventListener = (type, fn) => { control.listeners[type] = fn; };
  }
  panel.bindEvents();
}

test('all bridge and Tater workspaces plus fallback settings remain reachable', () => {
  const panel = fixture();
  const nav = panel.renderNavigation();
  for (const id of ['assistant', 'models', 'home-control', 'hydra', 'satellites', 'audio', 'bluetooth', 'defaults', 'verifier', 'trainer', 'firmware']) assert.match(nav, new RegExp(`data-tab="${id}"`));
  panel._data.settings_schema.push({ section: 'future-section', title: 'Future settings', fields: [{ key: 'future-option', label: 'Future option', type: 'boolean' }] });
  for (const board of ['biscuit', 'crown', 'checkers', 'voice-pe', 'satellite1', 's3-box-3', 'thirdreality-s420']) {
    for (const mode of ['mww', 'oww', 'nww', 'mww_oww', 'mww_nww']) {
      for (const advanced of [false, true]) {
        const device = panel._data.devices[0];
        Object.assign(device, { board, board_key: board });
        Object.assign(device.settings, { wake_detector_mode: mode, wake_word: advanced ? 'custom_url' : 'hey_tater', oww_wake_word: advanced ? 'custom_url' : 'hey_tater', wake_sound: advanced ? 'custom' : 'default', aec_enabled: advanced });
        panel.prepareDeviceDraft(device.device_id);
        const eligible = panel.settingsSectionsFor(panel._deviceDraft, 'device', device);
        const groups = panel.deviceSettingGroups(device);
        const sections = groups.flatMap(group => group.sections);
        for (const section of eligible) assert.ok(sections.includes(section.section), `${board}/${mode}: ${section.section} must have a workspace`);
        assert.ok(groups.some(group => group.id === 'other'), 'new schema sections must get a visible fallback');
        const covered = new Set(groups.flatMap(group => group.id === 'overview' ? [] : panel.settingsSectionsFor(panel._deviceDraft, 'device', device, { include: group.sections }).flatMap(section => section.fields.map(field => field.key))));
        assert.deepEqual([...covered].sort(), [...new Set(eligible.flatMap(section => section.fields.map(field => field.key)))].sort());
      }
    }
  }
});

test('mini Tater pages retain the complete pipeline, one tool, and Hydra controls', () => {
  const panel = fixture();
  const assistant = panel.renderAssistantChoice();
  assert.match(assistant, /Home Assistant[\s\S]*Complete Tater pipeline[\s\S]*Tater/i);
  assert.doesNotMatch(assistant, /data-tater-test-message[^>]*disabled/);
  assert.match(panel.renderModelsAndSpeech(), /Language model[\s\S]*Speech-to-text[\s\S]*Voice activity detection[\s\S]*Neural VAD[\s\S]*WebRTC[\s\S]*Text-to-speech/);
  assert.match(panel.renderHomeControl(), /One built-in capability[\s\S]*control_home[\s\S]*Exposed to Assist[\s\S]*All HA entities/);
  panel._hydraSection = 'behavior';
  assert.match(panel.renderHydra(), /Maximum ledger items[\s\S]*Astraeus second plan check/);
});

test('mini Tater VAD model choice updates the saved assistant draft', () => {
  const panel = fixture();
  const option = { dataset: { taterVad: 'webrtc' }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
  panel.shadowRoot = {
    querySelectorAll: selector => selector === '[data-tater-vad]' ? [option] : [],
    querySelector: () => null,
  };
  panel.bindEvents();
  option.listeners.click();
  assert.equal(panel._taterDraft.vad_backend, 'webrtc');
  assert.equal(panel.isScopeDirty('tater'), true);
});

test('Tater setup guidance appears before changing the active HA pipeline', () => {
  const panel = fixture();
  panel._data.tater_assistant.ready = { ok: false, missing: ['LLM model', 'LLM API key'] };
  const assistant = panel.renderAssistantChoice();
  assert.match(assistant, /Setup needed[\s\S]*Finish Tater setup[\s\S]*LLM model · LLM API key/);
  assert.match(assistant, /data-tater-test-message[^>]*disabled/);
});

test('saving Tater settings never posts public key-state flags', async () => {
  const panel = fixture();
  panel._taterDraft.llm_model = 'test-model';
  panel._taterDraft.llm_api_key = 'new-secret';
  const save = {};
  controls(panel, { '[data-action="save-tater"]': save });
  let request;
  panel.api = async (...args) => { request = args; return { settings: panel._data.tater_assistant.settings }; };
  panel.run = async action => action();
  await save.listeners.click();
  assert.equal(request[0], 'POST');
  assert.equal(request[1], 'tater/settings');
  assert.equal(request[2].settings.llm_api_key, 'new-secret');
  assert.equal('llm_api_key_set' in request[2].settings, false);
});

test('device drafts and pipeline choices survive navigation and polling', () => {
  const panel = fixture();
  panel.prepareDeviceDraft('one');
  panel._deviceDraft.aec_enabled = true;
  panel._pipelineDraft = 'custom-pipeline';
  panel._vadDraft = 'aggressive';
  panel.markDirty('device');
  panel.navigate('defaults');
  panel.prepareDeviceDraft('two');
  panel._deviceDraft.logging_level = 'debug';
  panel.markDirty('device');
  panel.prepareDeviceDraft('one');
  panel.syncDrafts(panel._data);
  assert.equal(panel._deviceDraft.aec_enabled, true);
  assert.equal(panel._pipelineDraft, 'custom-pipeline');
  assert.equal(panel._vadDraft, 'aggressive');
  panel.prepareDeviceDraft('two');
  assert.equal(panel._deviceDraft.logging_level, 'debug');
});

test('automatic redraws preserve page position, nested scrolling, and expanded details', () => {
  const panel = fixture();
  const documentScroller = { scrollTop: 720, scrollLeft: 0, isConnected: true };
  const ancestorScroller = { scrollTop: 410, scrollLeft: 6, isConnected: true, parentNode: null };
  const parentShadowRoot = { host: ancestorScroller, parentNode: null };
  const internalBefore = { scrollTop: 180, scrollLeft: 2 };
  panel.parentNode = parentShadowRoot;
  panel.ownerDocument = { scrollingElement: documentScroller };
  panel.shadowRoot = {
    querySelectorAll: selector => selector === 'details'
      ? [{ open: true }, { open: false }]
      : [internalBefore],
  };
  const state = panel.captureViewState();

  const internalAfter = { scrollTop: 0, scrollLeft: 0 };
  const detailsAfter = [{ open: false }, { open: false }];
  ancestorScroller.scrollTop = 0;
  ancestorScroller.scrollLeft = 0;
  documentScroller.scrollTop = 0;
  panel.shadowRoot = {
    querySelectorAll: selector => selector === 'details' ? detailsAfter : [internalAfter],
  };
  panel.restoreViewState(state);

  assert.deepEqual([internalAfter.scrollTop, internalAfter.scrollLeft], [180, 2]);
  assert.equal(detailsAfter[0].open, true);
  assert.deepEqual([ancestorScroller.scrollTop, ancestorScroller.scrollLeft], [410, 6]);
  assert.equal(documentScroller.scrollTop, 720);
});

test('saving one domain and read-only commands preserve other pending settings', async () => {
  const panel = fixture();
  panel._globalDraft.continued_chat = false; panel.markDirty('global', 'continued_chat');
  panel._globalDraft.wake_verifier_threshold = 0.92; panel.markDirty('global', 'wake_verifier_threshold');
  panel._globalDraft.capture_close_misses = true; panel.markDirty('global', 'capture_close_misses');
  panel._wakeDraft.wake_detector_mode = 'mww_nww'; panel.markDirty('wake');
  panel.prepareDeviceDraft('one'); panel._deviceDraft.aec_enabled = true; panel.markDirty('device');
  panel.hasActiveInput = () => false;
  panel.api = async () => copy(panel._data);
  await panel.run(async () => {}, 'Identified');
  assert.equal(panel._dirtyScopes.size, 5);
  await panel.run(async () => { panel._data.global_settings.continued_chat = false; }, 'Saved', ['global']);
  assert.equal(panel._dirtyScopes.size, 4);
  assert.equal(panel._globalDraft.wake_verifier_threshold, 0.92);
  assert.equal(panel._globalDraft.capture_close_misses, true);
  assert.equal(panel._wakeDraft.wake_detector_mode, 'mww_nww');
  assert.equal(panel._deviceDraft.aec_enabled, true);
  assert.equal(panel._dirty, true);
});

test('failed saves keep all pending changes', async () => {
  const panel = fixture();
  panel._wakeDraft.wake_detector_mode = 'nww'; panel.markDirty('wake');
  await panel.run(async () => { throw new Error('offline'); }, '', ['wake']);
  assert.equal(panel._wakeDraft.wake_detector_mode, 'nww');
  assert.equal(panel.isScopeDirty('wake'), true);
  assert.match(panel._error, /offline/);
});

test('a pending device save clears only the device that initiated it', async () => {
  const panel = fixture(); panel.prepareDeviceDraft('one'); panel.markDirty('device');
  panel.hasActiveInput = () => false; panel.api = async () => copy(panel._data);
  await panel.run(async () => {
    panel.prepareDeviceDraft('two'); panel._deviceDraft.aec_enabled = true; panel.markDirty('device');
  }, 'Saved', ['device']);
  assert.equal(panel._dirtyScopes.has('device:one'), false);
  assert.equal(panel._dirtyScopes.has('device:two'), true);
  assert.equal(panel._deviceDraft.aec_enabled, true);
});

test('device save still posts only changed firmware settings plus pipeline and VAD', async () => {
  const panel = fixture(); panel.prepareDeviceDraft('one');
  panel._deviceDraft.aec_enabled = true; panel._pipelineDraft = 'selected'; panel._vadDraft = 'relaxed';
  const save = {};
  controls(panel, { '[data-action="save-device"]': save });
  let request;
  panel.api = async (...args) => { request = args; };
  panel.run = async action => action();
  save.listeners.click();
  assert.deepEqual(request, ['POST', 'settings/device/one', { settings: { aec_enabled: true }, pipeline_id: 'selected', vad_sensitivity: 'relaxed' }]);
});

test('domain saves retain the existing API allowlists', async () => {
  const panel = fixture();
  panel._globalDraft = { continued_chat: true, capture_wake_audio: true, wake_verifier_threshold: 0.9, wake_word_url: 'must-not-cross-boundaries' };
  const cases = [
    ['save-global', 'settings/global', { continued_chat: true }],
    ['save-trainer', 'settings/trainer', { capture_wake_audio: true }],
    ['save-verifier', 'settings/verifier', { wake_verifier_threshold: 0.9 }],
  ];
  for (const [action, endpoint, expected] of cases) {
    const control = {}; controls(panel, { [`[data-action="${action}"]`]: control });
    let request; panel.api = async (...args) => { request = args; }; panel.run = async fn => fn();
    await control.listeners.click();
    assert.deepEqual(request, ['POST', endpoint, { settings: expected }]);
  }
});

test('catalog and sound selection retains every option and escapes labels', () => {
  const panel = fixture();
  const field = { key: 'wake_sound', label: 'Wake sound', type: 'select', options: [{ value: 'one', label: 'A <sound>' }, { value: 'two', label: 'B & C' }] };
  const normal = panel.renderField(field, { wake_sound: 'one' }, 'global');
  assert.match(normal, /data-pick-setting="wake_sound"/);
  assert.match(normal, /A &lt;sound&gt;/);
  const picker = panel.renderField(field, { wake_sound: 'one' }, 'global', true);
  assert.match(picker, /value="one" checked/);
  assert.match(picker, /value="two"/);
  assert.match(picker, /B &amp; C/);
});

test('an asset upload preserves device edits even when switching away and back', async () => {
  const panel = fixture(); panel.prepareDeviceDraft('one');
  panel._deviceDraft.aec_enabled = true; panel.markDirty('device');
  const picker = { files: [{ name: 'wake.wav', arrayBuffer: async () => new Uint8Array([1, 2]).buffer }], listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }, click() {} };
  const previousDocument = globalThis.document, previousPrompt = globalThis.prompt;
  globalThis.document = { createElement: () => picker }; globalThis.prompt = () => 'Wake sound';
  panel.hasActiveInput = () => false;
  panel.api = async (method, endpoint) => {
    if (endpoint === 'assets') {
      panel.navigate('audio'); panel.prepareDeviceDraft('two'); panel.prepareDeviceDraft('one');
      return { asset: { id: 'uploaded-asset' } };
    }
    return copy(panel._data);
  };
  try {
    await panel.uploadAsset({ dataset: { uploadKind: 'wake_sound', uploadKey: 'wake_sound_asset_id', uploadScope: 'device' } });
    await picker.listeners.change();
    assert.equal(panel._deviceDraft.aec_enabled, true);
    assert.equal(panel._deviceDraft.wake_sound_asset_id, 'uploaded-asset');
    assert.equal(panel._deviceDraft.wake_sound, 'custom');
  } finally { globalThis.document = previousDocument; globalThis.prompt = previousPrompt; }
});
