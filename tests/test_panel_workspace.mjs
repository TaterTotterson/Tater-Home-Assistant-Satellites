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
  panel._data = { global_settings: copy(settings.defaults), shared_wake_settings: copy(settings.defaults), settings_schema: copy(settings.schema), devices: [device('one', 'crown'), device('two', 'satellite1')], pipelines: [], tater_assistant: { settings: { assistant_mode: 'home_assistant', llm_base_url: 'https://api.openai.com/v1', llm_model: '', llm_api_key_set: false, stt_provider: 'openai', stt_base_url: 'https://api.openai.com/v1', stt_model: 'gpt-4o-transcribe', stt_wyoming_model: '', stt_api_key_set: false, tts_provider: 'openai', tts_base_url: 'https://api.openai.com/v1', tts_model: 'gpt-4o-tts', tts_voice: 'alloy', tts_wyoming_voice: '', tts_api_key_set: false, entity_scope: 'exposed', assistant_name: 'Tater', personality: 'Warm', max_display: 8, max_store: 20, max_llm: 8, hydra_max_ledger_items: 1500, hydra_astraeus_plan_review_enabled: true, hydra_auto_continue_incomplete_final_enabled: false }, ready: { ok: true, missing: [] }, home_control: { entity_count: 2, areas: 1, domains: ['light'], examples: [{ entity_id: 'light.kitchen', name: 'Kitchen', area: 'Kitchen', state: 'off', domain: 'light' }] }, metrics: {}, ledger: [], messages: [] } };
  Object.assign(panel._data.tater_assistant.settings, {
    hydra_beast_mode_enabled: false,
    hydra_llm_astraeus_provider: 'base',
    hydra_llm_thanatos_provider: 'base',
    hydra_llm_hermes_provider: 'base',
  });
  panel._data.wake_arbitration = { ...copy(settings.arbitration), pending: 0, busy: 0, history: [] };
  panel.syncDrafts(panel._data);
  panel.render = () => {};
  return panel;
}
function controls(panel, selectors, collections = {}) {
  panel.shadowRoot = { querySelectorAll: selector => collections[selector] || [], querySelector: selector => selectors[selector] || null };
  for (const control of [...Object.values(selectors), ...Object.values(collections).flat()]) {
    control.listeners = {};
    control.addEventListener = (type, fn) => { control.listeners[type] = fn; };
  }
  panel.bindEvents();
}

test('wake arbitration is available in both modes and saves its own draft without touching satellite settings', async () => {
  const panel = fixture();
  for (const mode of ['home_assistant', 'tater']) {
    panel._taterDraft.assistant_mode = mode;
    assert.match(panel.renderNavigation(), /data-tab="arbitration"/);
  }
  let html = panel.renderArbitration();
  for (const key of ['enabled', 'scope', 'selection', 'window_ms', 'release_ms', 'busy_timeout_s']) assert.match(html, new RegExp(`data-setting="${key}" data-scope="arbitration"`));
  assert.match(html, /Home Assistant also applies its own cooldown/);
  const shared = copy(panel._globalDraft);
  const duration = { type: 'range', dataset: { scope: 'arbitration', setting: 'window_ms' }, value: '1200' };
  const release = { type: 'range', dataset: { scope: 'arbitration', setting: 'release_ms' }, value: '0' };
  controls(panel, {}, { '[data-setting]': [duration, release] });
  duration.listeners.change();
  release.listeners.change();
  assert.equal(panel.pageHasDraft('arbitration'), true);
  panel.syncDrafts({ ...panel._data, wake_arbitration: { ...panel._data.wake_arbitration, settings: { ...settings.arbitration.settings, window_ms: 800 } } });
  assert.equal(panel._arbitrationDraft.window_ms, 1200);
  assert.equal(panel._arbitrationDraft.release_ms, 0);
  html = panel.renderArbitration();
  assert.match(html, /data-setting="release_ms"[^>]+value="0"/);
  assert.deepEqual(panel._globalDraft, shared);
  let request, scopes;
  panel.api = async (...args) => { request = args; };
  panel.run = async (action, message, savedScopes) => { scopes = savedScopes; await action(); };
  const save = {};
  controls(panel, { '[data-action="save-arbitration"]': save });
  await save.listeners.click();
  assert.equal(request[1], 'settings/arbitration');
  assert.equal(request[2].settings.window_ms, 1200);
  assert.deepEqual(Object.keys(request[2].settings).sort(), Object.keys(settings.arbitration.settings).sort());
  assert.deepEqual(scopes, ['arbitration']);
  const discard = {};
  panel._tab = 'arbitration';
  controls(panel, { '[data-action="reset-draft"]': discard });
  discard.listeners.click();
  assert.equal(panel._arbitrationDraft.window_ms, settings.arbitration.settings.window_ms);
  assert.equal(panel.pageHasDraft('arbitration'), false);
  panel._data.wake_arbitration.history = [{ timestamp: 100, winner: '<unsafe>', reason: 'strongest_audio', candidates: [] }];
  assert.match(panel.renderArbitration(), /&lt;unsafe&gt;/);
});

test('all bridge and Tater workspaces plus fallback settings remain reachable', () => {
  const panel = fixture();
  panel._taterDraft.assistant_mode = 'tater';
  const nav = panel.renderNavigation();
  for (const id of ['assistant', 'models', 'home-control', 'hydra', 'satellites', 'awareness', 'vision', 'audio', 'bluetooth', 'defaults', 'verifier', 'trainer', 'firmware']) assert.match(nav, new RegExp(`data-tab="${id}"`));
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

test('doorbell stays available in HA and keeps independent speaker, camera, and screen drafts', async () => {
  const panel = fixture();
  panel._data.doorbell = {default_prompt:'Be welcoming.',doorbells:[],history:[],catalog:{
    triggers:[{id:'event.press',name:'Doorbell',options:[{value:'event:press',label:'Pressed'}],suggested_for:['camera.front']}],
    cameras:[{id:'camera.front',name:'Front camera',device_id:'front'}],
    speakers:[{id:'media_player.separate',name:'Another brand speaker',device_id:'front'}],
    screens:[{id:'rook',name:'Rook',supported:true,available:true},{id:'old',name:'Old Show',supported:false,available:true}],
  }};
  assert.match(panel.renderNavigation(), /data-tab="doorbell"/);
  panel.openDoorbell();
  let html = panel.renderDoorbellEditor();
  assert.match(html, /Greeting speaker[\s\S]*Another brand speaker/);
  assert.match(html, /Home Assistant’s default Assist pipeline/);
  assert.match(html, /data-doorbell-screen="old"[^>]*disabled/);
  const trigger = {dataset:{doorbellSetting:'trigger_entity'},value:'event.press',tagName:'SELECT'};
  controls(panel, {}, {'[data-doorbell-setting]':[trigger]});
  trigger.listeners.change();
  assert.equal(panel._doorbellDraft.camera_entity,'camera.front');
  assert.equal(panel._doorbellDraft.speaker_entity,'media_player.separate');
  assert.equal(panel._doorbellDraft.trigger_value,'event:press');
  panel._doorbellDraft.speaker_entity='media_player.user_choice';
  panel.syncDrafts(panel._data);
  assert.equal(panel._doorbellDraft.speaker_entity,'media_player.user_choice');
  assert.equal(panel.pageHasDraft('doorbell'),true);
  assert.match(panel.renderDoorbellEditor(), /media_player.user_choice · Unavailable/);
  let request;
  panel.api=async(...args)=>{request=args;return {doorbell:{...panel._doorbellDraft,id:'saved'}};};
  panel.run=async action=>action();
  const save={};
  controls(panel, {'[data-action="save-doorbell"]':save});
  await save.listeners.click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(request[1],'doorbell/doorbells');
  assert.equal(request[2].doorbell.speaker_entity,'media_player.user_choice');
  panel._doorbellDraft.greeting_enabled=false;
  assert.doesNotMatch(panel.renderDoorbellEditor(), /data-doorbell-setting="speaker_entity"/);
  assert.match(panel.renderDoorbellEditor(), /Camera viewing will work without generating speech/);
  panel._doorbellSection='activity';
  panel._data.doorbell.history=[{name:'<Door>',created_at:1,status:'partial',greeting:'<Hello>',deliveries:[{kind:'speaker',destination:'media_player.separate',status:'failed',error:'<Offline>'}]}];
  html=panel.renderDoorbell();
  assert.match(html,/&lt;Hello&gt;/);
  assert.match(html,/&lt;Offline&gt;/);
});

test('identity drafts survive refresh and device navigation and stay separate from overrides', async () => {
  const panel = fixture();
  panel._data.devices[0].capabilities.identity_update = true;
  panel.prepareDeviceDraft('one');
  const input = { dataset: { identity: 'device_name' }, value: 'Kitchen <Echo>' };
  const save = {};
  controls(panel, { '[data-save-identity]': save }, { '[data-identity]': [input] });
  input.listeners.input();
  assert.equal(panel.isScopeDirty('identity'), true);
  assert.equal(panel.pageHasDraft('satellites'), true);
  assert.equal(panel.isScopeDirty('device'), false);
  panel.syncDrafts(panel._data);
  assert.equal(panel._identityDrafts.get('one').device_name, 'Kitchen <Echo>');
  panel.prepareDeviceDraft('two');
  panel.prepareDeviceDraft('one');
  assert.match(panel.renderDeviceIdentity(panel._data.devices[0]), /Kitchen &lt;Echo&gt;/);
  let request;
  panel.api = async (...args) => { request = args; return { ok: true }; };
  panel.run = async action => action();
  save.listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(request[1], 'settings/device/one/identity');
  assert.deepEqual(request[2], { device_name: 'Kitchen <Echo>', room: '' });
  assert.match(panel.renderDeviceIdentity(panel._data.devices[1]), /Update this satellite’s firmware/);
  panel._data.devices[0].connected = false;
  assert.match(panel.renderDeviceIdentity(panel._data.devices[0]), /Connect this satellite before saving/);
});

test('Home Assistant is default and hides Tater-only navigation until selected', () => {
  const panel = fixture();
  let nav = panel.renderNavigation();
  assert.match(nav, /data-tab="assistant"/);
  assert.match(nav, /data-tab="awareness"/);
  assert.match(nav, /data-tab="vision"/);
  assert.match(nav, /data-tab="bluetooth"[\s\S]*data-tab="dashboard-studio"[\s\S]*Voice & wake/);
  for (const id of ['models', 'home-control', 'hydra']) assert.doesNotMatch(nav, new RegExp(`data-tab="${id}"`));
  panel.navigate('models');
  assert.equal(panel._tab, 'satellites');

  panel._taterDraft.assistant_mode = 'tater';
  nav = panel.renderNavigation();
  for (const id of ['models', 'home-control', 'hydra']) assert.match(nav, new RegExp(`data-tab="${id}"`));

  panel._tab = 'hydra';
  panel._taterDraft.assistant_mode = 'home_assistant';
  panel.syncDrafts(panel._data);
  assert.equal(panel._tab, 'assistant');
});

test('mini Tater pages retain the complete pipeline, built-in tools, and Hydra controls', () => {
  const panel = fixture();
  let assistant = panel.renderAssistantChoice();
  assert.match(assistant, /Home Assistant[\s\S]*Mini version of Tater[\s\S]*Mini-Tater/i);
  assert.doesNotMatch(assistant, /data-tater-test-message/);
  panel._taterDraft.assistant_mode = 'tater';
  assistant = panel.renderAssistantChoice();
  assert.match(assistant, /Talk to Mini-Tater/);
  assert.doesNotMatch(assistant, /data-tater-test-message[^>]*disabled/);
  const models = panel.renderModelsAndSpeech();
  assert.match(models, /Language model[\s\S]*Image understanding[\s\S]*Open Vision[\s\S]*Beast Mode[\s\S]*Astraeus[\s\S]*Thanatos[\s\S]*Hermes[\s\S]*Speech-to-text[\s\S]*Text-to-speech/);
  assert.doesNotMatch(models, /data-tater-vad|WebRTC/);
  panel.prepareDeviceDraft('one');
  panel._deviceSection = 'voice';
  assert.doesNotMatch(panel.renderDeviceEditor(panel._data.devices[0]), /End-of-speech sensitivity|data-special="vad"/);
  assert.match(panel.renderHomeControl(), /Tater Vision is Tater's visual-question tool[\s\S]*tater_vision[\s\S]*Use this for normal timer requests[\s\S]*voicepe_remote_timer[\s\S]*Built-in Home Assistant capabilities[\s\S]*Use for any request to control or check smart-home devices[\s\S]*device_control[\s\S]*Exposed to Assist[\s\S]*All HA entities[\s\S]*Available now[\s\S]*2 entities across 1 areas[\s\S]*Save home tools/);
  panel._data.tater_assistant.built_in_tools = [
    {id:'todo_list',description:'Manage HA lists'}, {id:'weather_forecast',description:'Read HA weather'},
    {id:'broadcast',description:'Spoken announcements'}, {id:'music_assistant',description:'Music playback'},
    {id:'schedule_home',description:'Delayed device actions'},
  ];
  const tools = panel.renderHomeControl();
  for (const id of ['todo_list','weather_forecast','broadcast','music_assistant','schedule_home']) assert.match(tools, new RegExp(id));
  assert.match(tools, /Home Assistant clock[\s\S]*configured timezone/);
  assert.match(tools, /<h2>Scheduled actions<\/h2>/);
  assert.match(tools, /<h2>Web search<\/h2>[\s\S]*no API key or setup needed/);
  assert.equal((tools.match(/<h2>Scheduled actions<\/h2>/g) || []).length, 1);
  panel._hydraSection = 'behavior';
  assert.match(panel.renderHydra(), /Maximum ledger items[\s\S]*Astraeus second plan check/);
});

test('web search sources are safe clickable links and survive a refreshed chat snapshot', () => {
  const panel = fixture();
  panel._taterDraft.assistant_mode = 'tater';
  panel._data.tater_assistant.messages = [{
    role: 'assistant', content: 'Here is the current information.',
    sources: [
      { title: '<img src=x onerror=alert(1)>', url: 'https://example.org/?a=1&b=2' },
      { title: 'Unsafe', url: 'javascript:alert(1)' },
      { title: 'Unsafe', url: 'data:text/html,hello' },
      { title: 'Unsafe', url: 'https://user:password@example.org/' },
      { title: 'Unsafe', url: 'https://example.org/\npath' },
    ],
  }];
  const html = panel.renderAssistantChoice();
  assert.match(html, /aria-label="Web sources"/);
  assert.match(html, /href="https:\/\/example.org\/\?a=1&amp;b=2" target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img src=x|href="javascript:|href="data:|user:password|>Unsafe<\/a>/);
  assert.equal((html.match(/rel="noopener noreferrer"/g) || []).length, 1);
  assert.doesNotMatch(panel.renderAssistantTestMessage({ role: 'user', content: 'hello', sources: [{ url: 'https://example.org' }] }, {}), /Web sources/);
});

test('vision can follow Base or reveal a dedicated compatible endpoint', () => {
  const panel = fixture();
  panel._taterDraft.assistant_mode = 'tater';
  panel._visionDraft.vision_provider = 'base';
  let models = panel.renderVision();
  assert.match(models, /Reuse the Base model/);
  assert.doesNotMatch(models, /data-vision-setting="vision_base_url"/);

  panel._visionDraft.vision_provider = 'openai_compatible';
  panel._data.tater_assistant.ready.vision = { ok: false, missing: ['Vision model'] };
  models = panel.renderVision();
  assert.match(models, /data-vision-setting="vision_base_url"[\s\S]*data-vision-setting="vision_model"[\s\S]*data-vision-setting="vision_api_key"/);
  assert.match(models, /Finish Vision setup[\s\S]*Vision model/);
});

test('shared Vision drafts survive polling and cannot overwrite other assistant edits', async () => {
  const panel = fixture();
  panel._taterDraft.llm_model = 'unsaved-conversation-model';
  panel.markDirty('tater');
  Object.assign(panel._visionDraft, { vision_provider: 'openai_compatible', vision_model: 'image-model', vision_base_url: 'http://vision.local/v1', vision_api_key: 'vision-secret' });
  panel.markDirty('vision');
  panel.syncDrafts(panel._data);
  assert.equal(panel._visionDraft.vision_model, 'image-model');
  const save = {};
  controls(panel, { '[data-action="save-vision"]': save });
  let request;
  panel.api = async (...args) => {
    request = args;
    return { settings: { ...panel._data.tater_assistant.settings, vision_provider: 'openai_compatible', vision_model: 'image-model', vision_base_url: 'http://vision.local/v1', vision_api_key_set: true } };
  };
  panel.run = async action => action();
  await save.listeners.click();
  assert.equal(request[1], 'vision/settings');
  assert.deepEqual(Object.keys(request[2].settings).sort(), ['vision_api_key', 'vision_base_url', 'vision_model', 'vision_provider']);
  assert.equal(panel._taterDraft.llm_model, 'unsaved-conversation-model');
  assert.equal(panel._taterDraft.vision_model, 'image-model');
  assert.equal(panel.isScopeDirty('tater'), true);
});

test('Awareness keeps simple camera trigger destination fields and monitor drafts in HA mode', () => {
  const panel = fixture();
  panel.openAwarenessMonitor();
  panel._awarenessDraft.name = 'Unsaved front door';
  panel.markDirty('awareness');
  panel.syncDrafts(panel._data);
  assert.equal(panel._awarenessDraft.name, 'Unsaved front door');
  const html = panel.renderAwareness();
  for (const text of ['Choose a camera', 'When should we look?', 'Where should it go?', 'Optional settings', 'Save monitor', 'Recent activity']) assert.ok(html.includes(text));
  assert.match(html, /data-awareness-setting="camera_entity"/);
  assert.match(html, /data-awareness-setting="trigger_entity"/);
  assert.match(html, /data-tab="vision"/);
  panel._tab = 'vision';
  assert.match(panel.renderBody(), /configure Vision without setting up Mini-Tater/);
});

test('Awareness save and test use the saved monitor identity', async () => {
  const panel = fixture();
  panel.openAwarenessMonitor();
  Object.assign(panel._awarenessDraft, { name: 'Door', camera_entity: 'camera.door', trigger_entity: 'event.door', trigger_value: 'event:ring', destinations: ['satellite:one'] });
  const save = {};
  controls(panel, { '[data-action="save-awareness"]': save });
  let request;
  panel.api = async (...args) => { request = args; return { monitor: { ...args[2]?.monitor, id: 'saved-id' } }; };
  panel.run = async action => action();
  await save.listeners.click();
  assert.equal(request[1], 'awareness/monitors');
  assert.equal(request[2].monitor.camera_entity, 'camera.door');
  assert.equal(panel._awarenessDraft.id, 'saved-id');
  const button = { dataset: { awarenessTest: 'saved-id' } };
  controls(panel, {}, { '[data-awareness-test]': [button] });
  await button.listeners.click();
  assert.equal(request[1], 'awareness/monitors/saved-id/test');
  assert.equal(panel._awarenessSection, 'activity');
  panel.markDirty('awareness');
  request = null;
  await button.listeners.click();
  assert.equal(request, null);
  assert.match(panel._error, /Save this monitor/);
});

test('Awareness shows per-destination failures and escapes descriptions', () => {
  const panel = fixture();
  panel._awarenessSection = 'activity';
  panel._data.awareness = { history: [{ id: 'event', name: 'Door', camera_name: 'Camera', created_at: 1, description: '<script>bad()</script>', status: 'partial', deliveries: [{ destination: 'satellite:offline', status: 'failed', error: 'Screen offline' }, { destination: 'mobile_app:mobile_app_phone', status: 'sent' }] }] };
  const html = panel.renderAwareness();
  assert.match(html, /Partly delivered/);
  assert.match(html, /Screen offline/);
  assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test('Wyoming model and voice names are blank provider-specific fields', () => {
  const panel = fixture();
  Object.assign(panel._taterDraft, { stt_provider: 'wyoming', tts_provider: 'wyoming' });
  const models = panel.renderModelsAndSpeech();
  assert.match(models, /data-tater-setting="stt_wyoming_model"[^>]*value=""/);
  assert.match(models, /data-tater-setting="tts_wyoming_voice"[^>]*value=""/);
  assert.doesNotMatch(models, /Wyoming model name[^]*gpt-4o-transcribe/);
  assert.doesNotMatch(models, /Wyoming voice name[^]*value="alloy"/);
});

test('Tater setup guidance appears before changing the active HA pipeline', () => {
  const panel = fixture();
  panel._data.tater_assistant.ready = { ok: false, missing: ['LLM model', 'LLM API key'] };
  panel._taterDraft.assistant_mode = 'tater';
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
  assert.equal(Object.keys(request[2].settings).some(key => key.startsWith('vision_')), false);
});

test('pressing Enter sends the mini Tater chat message', async () => {
  const panel = fixture();
  const input = { value: 'What about now?' };
  const send = {};
  controls(panel, {
    '[data-tater-test-message]': input,
    '[data-action="test-tater"]': send,
  });
  let request;
  panel.api = async (...args) => {
    request = args;
    return { conversation_id: 'tater-panel-test' };
  };
  panel.run = async action => action();
  let prevented = false;

  await input.listeners.keydown({
    key: 'Enter',
    isComposing: false,
    preventDefault: () => { prevented = true; },
  });

  assert.equal(prevented, true);
  assert.deepEqual(request, [
    'POST',
    'tater/test',
    { text: 'What about now?', conversation_id: 'tater-panel-test' },
  ]);
  assert.equal(panel._testMessage, '');
});

test('mini Tater chat sends attached images through vision and clears the draft', async () => {
  const panel = fixture();
  panel._testImages = [{ name: 'office.png', type: 'image/png', size: 12, data_url: 'data:image/png;base64,cGljdHVyZQ==' }];
  const input = { value: 'What is on the desk?' };
  const send = {};
  controls(panel, {
    '[data-tater-test-message]': input,
    '[data-action="test-tater"]': send,
  });
  let request;
  panel.api = async (...args) => {
    request = args;
    return { conversation_id: 'vision-chat' };
  };
  panel.run = async action => action();

  await send.listeners.click();

  assert.deepEqual(request, [
    'POST',
    'tater/test',
    {
      text: 'What is on the desk?',
      conversation_id: 'tater-panel-test',
      images: [{ name: 'office.png', data_url: 'data:image/png;base64,cGljdHVyZQ==' }],
    },
  ]);
  assert.equal(panel._testConversationId, 'vision-chat');
  assert.deepEqual(panel._testImages, []);
});

test('device drafts and pipeline choices survive navigation and polling', () => {
  const panel = fixture();
  panel.prepareDeviceDraft('one');
  panel._deviceDraft.aec_enabled = true;
  panel._pipelineDraft = 'custom-pipeline';
  panel.markDirty('device');
  panel.navigate('defaults');
  panel.prepareDeviceDraft('two');
  panel._deviceDraft.logging_level = 'debug';
  panel.markDirty('device');
  panel.prepareDeviceDraft('one');
  panel.syncDrafts(panel._data);
  assert.equal(panel._deviceDraft.aec_enabled, true);
  assert.equal(panel._pipelineDraft, 'custom-pipeline');
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

test('conversation style is visible only on capable device displays and saves only that device', async () => {
  const panel = fixture();
  const device = panel._data.devices[0];
  device.capabilities.screen_power_management_version = 1;
  const keys = (scope, target = device) => panel.settingsSectionsFor(device.settings, scope, target).flatMap(section => section.fields.map(field => field.key));
  assert.ok(!keys('device').includes('screen_text_style'));
  device.capabilities.screen_text_style = true;
  assert.ok(keys('device').includes('screen_text_style'));
  assert.ok(!keys('global').includes('screen_text_style'));
  for (const board of ['checkers', 'cronos', 'crown', 'athena', 'rook']) {
    Object.assign(device, { board, board_key: board });
    assert.ok(keys('device').includes('screen_text_style'), board);
  }
  Object.assign(device, { board: 's3_box', board_key: 's3_box' });
  assert.ok(!keys('device').includes('screen_text_style'));
  Object.assign(device, { board: 'athena', board_key: 'athena' });
  panel.prepareDeviceDraft('one');
  panel._deviceDraft.screen_text_style = 'matrix';
  const save = {};
  controls(panel, { '[data-action="save-device"]': save });
  let request;
  panel.api = async (...args) => { request = args; };
  panel.run = async action => action();
  await save.listeners.click();
  assert.deepEqual(request, ['POST', 'settings/device/one', { settings: { screen_text_style: 'matrix' }, pipeline_id: '' }]);
  assert.equal(panel._data.devices[1].settings.screen_text_style, 'smooth');
});

test('device save still posts only changed firmware settings plus pipeline', async () => {
  const panel = fixture(); panel.prepareDeviceDraft('one');
  panel._deviceDraft.aec_enabled = true; panel._pipelineDraft = 'selected';
  const save = {};
  controls(panel, { '[data-action="save-device"]': save });
  let request;
  panel.api = async (...args) => { request = args; };
  panel.run = async action => action();
  save.listeners.click();
  assert.deepEqual(request, ['POST', 'settings/device/one', { settings: { aec_enabled: true }, pipeline_id: 'selected' }]);
});

test('physical volume updates refresh the control without leaking stale volume into an editor save', async () => {
  const panel = fixture();
  panel.prepareDeviceDraft('one');
  panel._deviceDraft.aec_enabled = true;
  panel.markDirty('device');
  panel._data.devices[0].settings.volume_percent = 35;
  panel.syncDrafts(panel._data);
  assert.match(panel.renderDeviceVolume(panel._data.devices[0]), /35%/);
  const save = {};
  controls(panel, { '[data-action="save-device"]': save });
  let request;
  panel.api = async (...args) => { request = args; };
  panel.run = async action => action();
  await save.listeners.click();
  assert.equal(request[2].settings.aec_enabled, true);
  assert.ok(!('volume_percent' in request[2].settings));
});

test('domain saves retain the existing API allowlists', async () => {
  const panel = fixture();
  panel._globalDraft = { continued_chat: true, capture_wake_audio: true, wake_verifier_threshold: 0.9, wake_verifier_window_ms: 2000, wake_verifier_timeout_ms: 1200, wake_word_url: 'must-not-cross-boundaries' };
  const cases = [
    ['save-global', 'settings/global', { continued_chat: true }],
    ['save-trainer', 'settings/trainer', { capture_wake_audio: true }],
    ['save-verifier', 'settings/verifier', { wake_verifier_threshold: 0.9, wake_verifier_window_ms: 2000, wake_verifier_timeout_ms: 1200 }],
  ];
  for (const [action, endpoint, expected] of cases) {
    const control = {}; controls(panel, { [`[data-action="${action}"]`]: control });
    let request; panel.api = async (...args) => { request = args; }; panel.run = async fn => fn();
    await control.listeners.click();
    assert.deepEqual(request, ['POST', endpoint, { settings: expected }]);
  }
});

test('wake-check wait slider shows milliseconds and saves a numeric live timeout', async () => {
  const panel = fixture();
  panel._globalDraft.wake_verifier_timeout_ms = 1200;
  const html = panel.renderVerifier();
  assert.match(html, /Wait for wake check[\s\S]*<output>1200 ms<\/output>/);
  assert.match(html, /500 ms · shorter wait/);
  assert.match(html, /2000 ms · more time to verify/);
  assert.match(html, /Reset to 500 ms/);
  assert.match(html, /type="range"[^>]*data-setting="wake_verifier_timeout_ms"[^>]*min="500"[^>]*max="2000"[^>]*step="100"/);
  const output = {};
  const slider = {
    type: 'range', value: '1500', dataset: { setting: 'wake_verifier_timeout_ms', scope: 'global', rangeFormat: 'milliseconds' },
    closest: () => ({ querySelector: () => output }),
    setAttribute: (name, value) => { slider[name] = value; },
  };
  const save = {};
  controls(panel, { '[data-action="save-verifier"]': save }, { '[data-setting]': [slider] });
  slider.listeners.input();
  assert.equal(output.textContent, '1500 ms');
  assert.equal(slider['aria-valuetext'], '1500 ms');
  slider.listeners.change();
  assert.equal(panel._globalDraft.wake_verifier_timeout_ms, 1500);
  panel.syncDrafts(panel._data);
  assert.equal(panel._globalDraft.wake_verifier_timeout_ms, 1500, 'polling must preserve the unsaved timeout');
  let request;
  panel.api = async (...args) => { request = args; };
  panel.run = async action => action();
  await save.listeners.click();
  assert.equal(request[1], 'settings/verifier');
  assert.equal(request[2].settings.wake_verifier_timeout_ms, 1500);
});

test('verification audio window keeps its own labels, draft, reset, and numeric save', async () => {
  const panel = fixture();
  let html = panel.renderVerifier();
  assert.match(html, /Verification audio window[\s\S]*<output>1000 ms<\/output>/);
  assert.match(html, /500 ms · shorter clip/);
  assert.match(html, /2000 ms · more audio context/);
  assert.match(html, /type="range"[^>]*data-setting="wake_verifier_window_ms"[^>]*min="500"[^>]*max="2000"[^>]*step="100"/);
  const output = {};
  const slider = {
    type: 'range', value: '2000', dataset: { setting: 'wake_verifier_window_ms', scope: 'global', rangeFormat: 'milliseconds' },
    closest: () => ({ querySelector: () => output }),
    setAttribute: (name, value) => { slider[name] = value; },
  };
  const save = {};
  controls(panel, { '[data-action="save-verifier"]': save }, { '[data-setting]': [slider] });
  slider.listeners.input();
  assert.equal(output.textContent, '2000 ms');
  assert.equal(slider['aria-valuetext'], '2000 ms');
  slider.listeners.change();
  panel.syncDrafts(panel._data);
  assert.equal(panel._globalDraft.wake_verifier_window_ms, 2000, 'polling preserves the unsaved window');
  assert.equal(panel._globalDraft.wake_verifier_timeout_ms, 500, 'clip length does not change the result wait');
  assert.equal(panel.isScopeDirty('verifier'), true);
  html = panel.renderVerifier();
  assert.match(html, /Verification audio window[\s\S]*<output>2000 ms<\/output>/);
  assert.match(html, /data-reset-setting="wake_verifier_window_ms"[^>]*data-reset-value="1000"/);
  let request;
  panel.api = async (...args) => { request = args; };
  panel.run = async action => action();
  await save.listeners.click();
  assert.equal(request[1], 'settings/verifier');
  assert.equal(request[2].settings.wake_verifier_window_ms, 2000);
  assert.equal(request[2].settings.wake_verifier_timeout_ms, 500);
  const reset = { dataset: { resetSetting: 'wake_verifier_window_ms', resetScope: 'global', resetValue: '1000' } };
  controls(panel, {}, { '[data-reset-setting]': [reset] });
  reset.listeners.click();
  assert.equal(panel._globalDraft.wake_verifier_window_ms, 1000);
  assert.equal(panel._globalDraft.wake_verifier_timeout_ms, 500);
});

test('STT mismatch and the satellite timeout outcome remain separate', () => {
  const panel = fixture();
  const device = panel._data.devices[0];
  device.wake_verifier = {
    mode: 'enforce', applied_mode: 'enforce', supported: true,
    count: 99, accepted: 50, rejections: 49, fail_open: 10,
    server: { count: 3, accepted: 0, rejections: 2, fail_open: 1 },
    last: { reason: 'transcript_mismatch', accepted: false, available: true, score: 0.6, stt_ms: 400 },
    device: { completed: 3, rejections: 2, fail_open: 1, last_reason: 'satellite_timeout_fail_open' },
  };
  let html = panel.renderVerifierDevice(device);
  assert.match(html, /STT mismatch/);
  assert.match(html, /3 STT checks/);
  assert.match(html, /Last satellite report[\s\S]*Timed out — listening allowed/);
  assert.doesNotMatch(html, /Wake blocked/);
  device.wake_verifier.device.last_reason = 'transcript_mismatch';
  html = panel.renderVerifierDevice(device);
  assert.match(html, /Last satellite report[\s\S]*Wake blocked/);
  device.wake_verifier.mode = 'observe';
  html = panel.renderVerifierDevice(device);
  assert.match(html, /Mismatch recorded — Observe mode/);
  assert.doesNotMatch(html, /Wake blocked/);
  device.wake_verifier.device = {};
  assert.match(panel.renderVerifierDevice(device), /Not reported yet/);
  device.wake_verifier.device = { pending: true };
  assert.match(panel.renderVerifierDevice(device), /Waiting for result/);
});

test('network diagnostics follow Ethernet, Wi-Fi fallback and disconnects without hiding Wi-Fi signal', () => {
  const panel = fixture();
  const device = panel._data.devices[1];
  device.wifi_rssi = -48;
  for (const board of ['satellite1', 'voice-pe', 'respeaker-xvf3800', 's3-box', 'biscuit']) {
    device.board = board;
    device.network = { connection: 'USB Ethernet', connection_ip: '192.0.2.9', ethernet_ip: '192.0.2.9', wifi_ip: '192.0.2.10', ethernet_link: true, usb_ethernet_state: 'connected' };
    assert.match(panel.renderDeviceOverview(device), /<label>Network<\/label><span>USB Ethernet<\/span>/);
    const diagnostics = panel.renderDeviceDiagnostics(device);
    assert.match(diagnostics, /<label>Ethernet IP<\/label><span>192.0.2.9<\/span>/);
    assert.match(diagnostics, /<label>Ethernet link<\/label><span>Up<\/span>/);
    assert.match(diagnostics, /<label>Wi-Fi signal<\/label><span>-48 dBm<\/span>/);
  }
  device.network.connection = 'Wi-Fi';
  device.network.connection_ip = '192.0.2.10';
  device.network.ethernet_link = false;
  device.network.usb_ethernet_state = 'waiting_for_link';
  assert.match(panel.renderDeviceDiagnostics(device), /<label>Network<\/label><span>Wi-Fi<\/span>/);
  assert.match(panel.renderDeviceDiagnostics(device), /<label>Ethernet link<\/label><span>Down<\/span>/);
  assert.match(panel.renderDeviceDiagnostics(device), /waiting for link/);
  device.connected = false;
  const offline = panel.renderDeviceDiagnostics(device);
  assert.match(offline, /<label>Network<\/label><span>Offline<\/span>/);
  assert.doesNotMatch(offline, /192\.0\.2\./);
  assert.doesNotMatch(offline, /waiting for link/);
});

test('network diagnostics handle older firmware and escape reported text', () => {
  const panel = fixture();
  const device = panel._data.devices[0];
  assert.match(panel.renderDeviceDiagnostics(device), /<label>Network<\/label><span>Not reported<\/span>/);
  device.network = { connection: '<route>', connection_ip: '<ip>', usb_ethernet_state: '<adapter>' };
  const html = panel.renderDeviceDiagnostics(device);
  for (const value of ['route', 'ip', 'adapter']) {
    assert.match(html, new RegExp(`&lt;${value}&gt;`));
    assert.doesNotMatch(html, new RegExp(`<${value}>`));
  }
});

test('trainer reports direct delivery separately from model pairing', () => {
  const panel = fixture();
  assert.match(panel.renderTrainer(), /Satellites send captures directly/);
  assert.match(panel.renderTrainer(), /Waiting for satellite report/);
  const device = panel._data.devices[0];
  device.settings.capture_wake_audio = true;
  device.trainer_capture = { reported: true, uploads: 2, upload_failures: 1, upload_pending: true, last_error: 'upload deferred during voice activity', free_internal_heap: 3100 };
  assert.match(panel.renderTrainerCapture(device), /Queued for idle/);
  device.trainer_capture.upload_running = true;
  assert.match(panel.renderTrainerCapture(device), /Uploading/);
  device.trainer_capture.upload_running = false;
  device.trainer_capture.upload_pending = false;
  device.trainer_capture.last_error = 'pending capture expired';
  assert.match(panel.renderTrainerCapture(device), /Capture expired/);
  device.trainer_capture.last_error = '<upload error>';
  assert.match(panel.renderTrainerCapture(device), /&lt;upload error&gt;/);
  device.trainer_capture.last_error = '';
  assert.match(panel.renderTrainerCapture(device), /Uploaded<\/span>/);
  device.connected = false;
  assert.match(panel.renderTrainerCapture(device), /Offline — last report/);
  assert.doesNotMatch(panel.renderTrainerCapture(device), /badge online/);
  device.connected = true;
  device.settings.capture_wake_audio = false;
  device.settings.capture_close_misses = false;
  assert.match(panel.renderTrainerCapture(device), /Capture disabled/);
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

test('sound presets update the full curve, manual edits and refresh preserve unsaved tuning', () => {
  const panel = fixture();
  panel.prepareDeviceDraft('one');
  panel._deviceDraft.eq_loudness = true;
  const selector = { type: 'select-one', value: 'voice', dataset: { setting: 'eq_preset', scope: 'device' } };
  controls(panel, {}, { '[data-setting]': [selector] });
  selector.listeners.change();
  const field = settings.schema.flatMap(section => section.fields).find(field => field.key === 'eq_preset');
  assert.equal(panel._deviceDraft.eq_preset, 'voice');
  assert.deepEqual(field.band_keys.map(key => panel._deviceDraft[key]), field.presets.voice);
  assert.equal(panel._deviceDraft.eq_loudness, false);
  panel.syncDrafts(panel._data);
  assert.equal(panel._deviceDraft.eq_preset, 'voice');
  assert.deepEqual(field.band_keys.map(key => panel._deviceDraft[key]), field.presets.voice);
  const slider = { type: 'number', value: '4', dataset: { setting: field.band_keys[0], scope: 'device' } };
  controls(panel, {}, { '[data-setting]': [slider] });
  slider.listeners.change();
  assert.equal(panel._deviceDraft.eq_preset, 'manual');
  assert.deepEqual(field.band_keys.map(key => panel._deviceDraft[key]), [4, ...field.presets.voice.slice(1)]);
  selector.value = 'manual';
  controls(panel, {}, { '[data-setting]': [selector] });
  selector.listeners.change();
  assert.equal(panel._deviceDraft[field.band_keys[0]], 4);
  selector.value = 'flat';
  selector.listeners.change();
  assert.deepEqual(field.band_keys.map(key => panel._deviceDraft[key]), Array(8).fill(0));
  const boost = { type: 'checkbox', checked: true, dataset: { setting: 'eq_loudness', scope: 'device' } };
  controls(panel, {}, { '[data-setting]': [boost] });
  boost.listeners.change();
  assert.equal(panel._deviceDraft.eq_preset, 'manual');
  assert.equal(panel._deviceDraft.eq_loudness, true);
  assert.match(panel.renderField(field, panel._deviceDraft, 'device'), /<select[\s\S]*Warm[\s\S]*Voice[\s\S]*Manual/);
});

test('Dashboard Studio keeps a separate workspace and escapes model text', () => {
  const panel = fixture();
  panel._studio.catalog = {enabled:true, model_ready:true, home:{areas:4, entities:50}, dashboards:[], workspaces:[]};
  let html = panel._studio.render();
  assert.match(html, /Choose for me/);
  assert.match(html, /Wall tablet/);
  panel._studio.workspace = {id:'private-design', title:'<img src=x>', url_path:null, revision:2,
    config:{views:[]}, messages:[{role:'assistant',content:'<script>alert(1)</script>'}], suggestions:[], has_changes:true};
  html = panel._studio.render();
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
  panel._taterDraft.assistant_mode = 'home_assistant';
  assert.match(panel.renderNavigation(), /data-tab="dashboard-studio"/);
  panel.syncDrafts(panel._data);
  assert.equal(panel._studio.workspace.id, 'private-design');
});

test('Studio design loop creates a draft and only calls its dedicated API', async () => {
  const panel = fixture();
  const calls = [];
  panel.api = async (method, path, body) => {
    calls.push({method,path,body});
    assert.equal(path, 'dashboard-studio');
    if (method === 'GET') return {enabled:true, model_ready:true, workspaces:[]};
    if (body.action === 'open') return {workspace:{id:'one',revision:0}};
    if (body.action === 'chat') return {workspace:{id:'one',revision:1,config:{views:[]},messages:[]}};
    throw new Error('Unexpected write');
  };
  await panel._studio.send('Make a dashboard for my home');
  assert.equal(panel._studio.workspace.revision, 1);
  assert.equal(calls.filter(call => call.body?.action === 'chat').length, 1);
  assert.equal(calls.find(call => call.body?.action === 'chat').body.revision, 0);
  assert.equal(calls.some(call => call.body?.action === 'apply'), false);
});

test('Studio preserves a failed request and Enter respects Shift and composition', async () => {
  const panel = fixture();
  panel._tab = 'dashboard-studio';
  const input = {value:'Keep this request'};
  controls(panel, {'[data-studio-message]':input});
  panel._studio.message = input.value;
  panel.api = async () => {throw new Error('Provider unavailable')};
  await panel._studio.send();
  assert.equal(panel._studio.message, 'Keep this request');
  assert.match(panel._studio.error, /Provider unavailable/);
  let sent = 0, prevented = 0;
  panel._studio.send = () => {sent++};
  for (const flags of [{shiftKey:true}, {isComposing:true}, {}]) input.listeners.keydown({key:'Enter', preventDefault:()=>{prevented++}, ...flags});
  assert.equal(sent, 1);
  assert.equal(prevented, 1);
});

test('Studio preview creates inert native cards, rebuilds lazy cards and updates state', async () => {
  const panel = fixture();
  class Element {
    constructor() {this.children=[];this.events={};this.style={values:{},setProperty(name,value){this.values[name]=value;}};this.isConnected=true;}
    setAttribute() {}
    addEventListener(name, callback) {this.events[name]=callback;}
    append(...children) {this.children.push(...children);}
    replaceChildren(...children) {this.children=children;}
    get firstElementChild() {return this.children[0];}
  }
  const target = new Element();
  panel.shadowRoot.querySelector = selector => selector === '[data-studio-native-preview]' ? target : null;
  const oldDocument = globalThis.document, oldHelpers = window.loadCardHelpers;
  globalThis.document = {createElement:()=>new Element()};
  const created = [];
  window.loadCardHelpers = async () => ({createCardElement:config => {
    const card = new Element();card.config=config;created.push(card);return card;
  }});
  try {
    panel._hass = {states:{'light.office':{state:'off'}}};
    panel._studio.workspace = {config:{views:[{type:'sections',theme:'Midnight',background:'linear-gradient(135deg,#111827,#30204a)',sections:[{theme:'Warm',background:{color:'#334455',opacity:30},cards:[{type:'tile',entity:'light.office'}]}]}]}};
    await panel._studio.mountPreview();
    const surface = target.children[0];
    assert.equal(surface.theme,'Midnight');
    assert.equal(surface.children[0].background,'linear-gradient(135deg,#111827,#30204a)');
    const section = surface.children[1].children[0];
    assert.equal(section.theme,'Warm');
    assert.equal(section.style.values.background,'color-mix(in srgb,#334455 30%,transparent)');
    const holder = surface.children[1].children[0].children[0];
    assert.equal(holder.inert, true);
    assert.equal(created[0].config.entity, 'light.office');
    created[0].events['ll-rebuild']({stopPropagation(){}});
    assert.equal(created.length, 2);
    assert.equal(panel._studio._cards.length, 1);
    assert.equal(holder.children[0], created[1]);
    const hass = {states:{'light.office':{state:'on'}}};
    panel._studio.updateHass(hass);
    assert.equal(created[1].hass, hass);
    assert.equal(surface.hass,hass);
    assert.equal(section.hass,hass);
    section.children.at(-1).events.click();
    assert.deepEqual(panel._studio.focus,{view_index:0,section_index:0});
  } finally {
    globalThis.document = oldDocument;window.loadCardHelpers = oldHelpers;
  }
});


test('Studio connection has its own workspace and preserves the design and pending edits', async () => {
  const panel = fixture();
  panel._tab = 'dashboard-studio';
  const saved = {base_url:'http://designer:8000/v1', model:'designer', api_key_set:true};
  panel._studio.catalog = {model_ready:false, settings:saved, dashboards:[]};
  let html = panel._studio.render();
  assert.match(html, /AI connection/);
  assert.doesNotMatch(html, /data-studio-setting=/);
  const workspace = {id:'my-layout', title:'My layout', url_path:null, config:{views:[]}, messages:[]};
  panel._studio.workspace = workspace;
  panel._studio.message = 'Keep my unfinished request';
  const position = {designScroll:250};
  panel.captureViewState = () => position;
  let restored;
  panel.restoreViewState = state => {restored = state;};
  const open = {dataset:{studioAction:'settings'}};
  controls(panel, {}, {'[data-studio-action]':[open]});
  await open.listeners.click();
  assert.equal(panel._studio.screen,'connection');
  html = panel._studio.render();
  assert.match(html, /Back to Studio/);
  assert.doesNotMatch(html, /data-studio-message|data-studio-starter|data-studio-native-preview|data-studio-dashboard/);
  assert.match(html, /data-studio-setting="base_url"/);
  assert.match(html, /Key saved/);
  assert.doesNotMatch(html, /data-tab="models"/);
  const input = {dataset:{studioSetting:'model'}, value:'new-designer'};
  const save = {dataset:{studioAction:'save-settings'}};
  controls(panel, {}, {'[data-studio-setting]':[input], '[data-studio-action]':[save]});
  input.listeners.input({target:input});
  html = panel._studio.render();
  assert.match(html, /value="new-designer"/);
  const back = {dataset:{studioAction:'back-to-design'}};
  controls(panel, {}, {'[data-studio-action]':[back]});
  await back.listeners.click();
  assert.equal(panel._studio.screen,'design');
  assert.equal(restored,position);
  assert.equal(panel._studio.workspace,workspace);
  assert.equal(panel._studio.message,'Keep my unfinished request');
  assert.doesNotMatch(panel._studio.render(),/data-studio-setting=/);
  controls(panel, {}, {'[data-studio-action]':[open]});
  await open.listeners.click();
  assert.match(panel._studio.render(), /value="new-designer"/);
  controls(panel, {}, {'[data-studio-action]':[save]});
  panel._studio.connectionDraft.api_key = 'new-secret';
  const calls = [];
  panel.api = async (method, path, body) => {
    assert.equal(path,'dashboard-studio');
    calls.push({method,body});
    if(method === 'POST') return {settings:{...saved, model:'new-designer'}};
    return {model_ready:true, settings:{...saved, model:'new-designer'}, dashboards:[]};
  };
  await save.listeners.click();
  assert.equal(calls[0].body.action,'settings');
  assert.equal(calls[0].body.settings.model,'new-designer');
  assert.equal(calls[0].body.settings.api_key,'new-secret');
  assert.equal(panel._studio.connectionDraft.api_key,'');
  assert.equal(panel._taterDraft.assistant_mode,'home_assistant');
  assert.match(panel._studio.notice,/ready to design/);
  assert.equal(panel._studio.screen,'connection');
  assert.equal(panel._studio.workspace,workspace);
  assert.doesNotMatch(panel._studio.render(),/new-secret/);
});

test('Studio opening times out, releases controls and ignores a late catalog response', async context => {
  context.mock.timers.enable({apis:['setTimeout']});
  const panel = fixture();
  let finish;
  panel._hass = {callApi:() => new Promise(resolve => {finish=resolve;})};
  const loading = panel._studio.load();
  assert.match(panel._studio.render(),/Opening Studio/);
  context.mock.timers.tick(15000);
  await loading;
  assert.equal(panel._studio.busy,false);
  assert.equal(panel._studio.operation,'');
  assert.match(panel._studio.error,/could not finish loading/);
  assert.match(panel._studio.render(),/Reload Studio/);
  finish({model_ready:true,dashboards:[]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(panel._studio.catalog,null);
});

test('Studio switches from opening to the design chat while the first model request runs', async () => {
  const panel = fixture();
  panel._studio.catalog = {model_ready:true,dashboards:[],home:{}};
  let opened, designed;
  panel.api = async (method,path,body) => {
    if(method==='GET') return panel._studio.catalog;
    if(body.action==='open') return new Promise(resolve => {opened=resolve;});
    if(body.action==='chat') return new Promise(resolve => {designed=resolve;});
    throw new Error('Unexpected write');
  };
  const running = panel._studio.send('Design my home');
  assert.match(panel._studio.render(),/Opening your design/);
  const workspace = {id:'first',title:'My home',revision:0,url_path:null,config:{views:[]},messages:[]};
  opened({workspace});
  await new Promise(resolve => setImmediate(resolve));
  const html = panel._studio.render();
  assert.match(html,/Designing your dashboard/);
  assert.match(html,/class="studio-workspace"/);
  assert.doesNotMatch(html,/Opening Studio/);
  designed({workspace:{...workspace,revision:1}});
  await running;
  assert.equal(panel._studio.busy,false);
  assert.equal(panel._studio.workspace.revision,1);
});

test('Bridge waits for HA readiness and reloads Studio after the frontend connects', async () => {
  const panel = fixture();
  panel._tab='dashboard-studio';
  let mainLoads=0, studioLoads=0;
  panel.load=async()=>{mainLoads++;};
  panel.hass=undefined;
  assert.equal(mainLoads,0);
  assert.equal(panel._error,'');
  const hass={callApi:async(method,path)=>{
    assert.equal(path,'tater/satellite/v1/dashboard-studio');
    studioLoads++;
    return {model_ready:true,dashboards:[],home:{}};
  }};
  panel.hass=hass;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(mainLoads,1);
  assert.equal(studioLoads,1);
  assert.equal(panel._studio.busy,false);
  assert.equal(panel._studio.catalog.model_ready,true);
  panel.hass=hass;
  assert.equal(mainLoads,1);
  assert.equal(studioLoads,1);
});

test('Studio clears its busy state if the initial render fails', async () => {
  const panel=fixture();
  let renders=0;
  panel.render=()=>{if(++renders===1) throw new Error('Render failed');};
  await panel._studio.load();
  assert.equal(panel._studio.busy,false);
  assert.equal(panel._studio.error,'Render failed');
  assert.equal(renders,2);
});

test('Studio visual direction is pending until the next chat and resumes with the saved design', async () => {
  const panel=fixture();
  panel._tab='dashboard-studio';
  panel._studio.catalog={model_ready:true,dashboards:[],themes:['default','Midnight'],styles:[{id:'auto',label:'Let the designer choose'},{id:'neon',label:'Neon control room',description:'Bold and colorful.'}]};
  panel._studio.workspace={id:'one',revision:1,config:{views:[]},messages:[]};
  let calls=[];
  panel.api=async(method,path,body)=>{
    calls.push({method,body});
    if(method==='GET') return panel._studio.catalog;
    if(body.action==='chat') return {workspace:{...panel._studio.workspace,visual_style:body.visual_style,theme:body.theme,revision:2}};
    if(body.action==='open') return {workspace:{...panel._studio.workspace,visual_style:'neon',theme:'Midnight'}};
    throw new Error('Unexpected HA write');
  };
  const choice={dataset:{studioStyle:'neon'}}, theme={value:'Midnight'}, details={};
  controls(panel,{'.studio-direction':details,'[data-studio-theme]':theme},{'[data-studio-style]':[choice]});
  choice.listeners.click();
  theme.listeners.change({target:theme});
  assert.equal(details.open,true);
  assert.equal(calls.length,0);
  assert.equal(panel._studio.visualStyle,'neon');
  assert.match(panel._studio.render(),/Neon control room/);
  assert.match(panel._studio.render(),/Your next message uses these choices/);
  await panel._studio.send('Make it dramatic');
  assert.equal(calls[0].body.visual_style,'neon');
  assert.equal(calls[0].body.theme,'Midnight');
  panel._studio.visualStyle='auto';panel._studio.theme='';
  await panel._studio.act('open',{workspace_id:'one'});
  assert.equal(panel._studio.visualStyle,'neon');
  assert.equal(panel._studio.theme,'Midnight');
});

test('Invalid designs keep the message and draft and offer retry without reloading', async () => {
  const panel=fixture();
  panel._studio.catalog={model_ready:true,dashboards:[]};
  const workspace={id:'one',revision:1,config:{views:[]},messages:[]};
  panel._studio.workspace=workspace;
  panel.api=async()=>{throw new Error('The model did not finish a valid dashboard. Your saved draft is unchanged.');};
  await panel._studio.send('Try an editorial look');
  assert.equal(panel._studio.workspace,workspace);
  assert.equal(panel._studio.message,'Try an editorial look');
  assert.equal(panel._studio.failedDesign,true);
  assert.match(panel._studio.render(),/Try design again/);
  assert.doesNotMatch(panel._studio.render(),/Reload Studio/);
  panel.api=async()=>{throw new Error('Studio lost track of this request. Reload Studio to check the latest saved design.');};
  await panel._studio.send();
  assert.equal(panel._studio.failedDesign,false);
  assert.match(panel._studio.render(),/Reload Studio/);
});

test('Studio generates three ideas sequentially without replacing the draft or applying to HA', async () => {
  const panel=fixture();
  const original={views:[]};
  let current={id:'ideas',revision:0,config:original,messages:[],concepts:[]};
  panel._studio.workspace=current;
  panel._studio.catalog={model_ready:true,dashboards:[]};
  const calls=[];
  panel.api=async(method,path,body)=>{
    if(method==='GET') return panel._studio.catalog;
    calls.push(structuredClone(body));
    assert.equal(body.revision,current.revision);
    if(body.action==='concept') {
      const idea={id:'idea-'+body.index,title:'Idea '+body.index,description:'A distinct composition',layout:['bento','editorial','original'][body.index],config:{views:[{title:'Home',type:'sections',sections:[{cards:[{type:'markdown',content:'Idea '+body.index}]}]}]}};
      current={...current,revision:current.revision+1,concepts:[...current.concepts,idea]};
    } else if(body.action==='choose_concept') {
      const idea=current.concepts.find(item=>item.id===body.concept_id);
      current={...current,revision:current.revision+1,config:idea.config,layout:idea.layout,has_changes:true};
    } else throw new Error('Unexpected HA write');
    return {workspace:current};
  };
  await panel._studio.showIdeas();
  assert.deepEqual(calls.map(call=>call.index),[0,1,2]);
  assert.deepEqual(panel._studio.workspace.config,original);
  assert.equal(panel._studio.previewConcept,'idea-0');
  assert.match(panel._studio.render(),/Compare ideas/);
  assert.match(panel._studio.render(),/Use this idea/);
  assert.equal(panel._studio.currentPreview().id,'idea-0');
  const before=calls.length;
  await panel._studio.send('Change this');
  assert.equal(calls.length,before);
  await panel._studio.act('choose_concept',{concept_id:'idea-1'});
  assert.equal(panel._studio.previewConcept,'');
  assert.equal(panel._studio.layout,'editorial');
  assert.equal(panel._studio.workspace.config.views[0].sections[0].cards[0].content,'Idea 1');
  assert.equal(calls.some(call=>call.action==='apply'),false);
});

test('A failed second idea preserves the first and can resume from the remaining idea', async () => {
  const panel=fixture();
  panel._studio.catalog={model_ready:true,dashboards:[]};
  let current={id:'ideas',revision:0,config:{views:[]},concepts:[]}, fail=true;
  panel._studio.workspace=current;
  const indices=[];
  panel.api=async(method,path,body)=>{
    if(method==='GET') return panel._studio.catalog;
    assert.equal(body.action,'concept');indices.push(body.index);
    if(body.index===1 && fail) {fail=false;throw new Error('The model did not finish this idea.');}
    current={...current,revision:current.revision+1,concepts:[...current.concepts,{id:'idea-'+body.index,title:'Idea',description:'Draft',config:{views:[]}}]};
    return {workspace:current};
  };
  await panel._studio.showIdeas();
  assert.equal(panel._studio.workspace.concepts.length,1);
  assert.equal(panel._studio.busy,false);
  assert.match(panel._studio.render(),/Finish the three ideas/);
  await panel._studio.showIdeas(true);
  assert.deepEqual(indices,[0,1,1,2]);
  assert.equal(panel._studio.workspace.concepts.length,3);
});

test('Surprise me requests an original layout and scoped edits send explicit indices', async () => {
  const panel=fixture();panel._tab='dashboard-studio';
  const workspace={id:'one',revision:0,config:{views:[{type:'sections',sections:[{cards:[]}]}]},messages:[]};
  panel._studio.workspace=workspace;panel._studio.catalog={model_ready:true,dashboards:[]};
  const calls=[];
  panel.api=async(method,path,body)=>{
    if(method==='GET')return panel._studio.catalog;
    calls.push(body);return {workspace:{...workspace,revision:1}};
  };
  const starter={dataset:{studioStarter:'5'}};
  controls(panel,{}, {'[data-studio-starter]':[starter]});
  await starter.listeners.click();
  assert.equal(calls[0].layout,'original');
  assert.match(calls[0].text,/Invent an original/);
  const scope={value:'section:0'};
  controls(panel,{'[data-studio-scope]':scope});
  scope.listeners.change({target:scope});
  await panel._studio.send('Make this section more useful');
  assert.deepEqual(calls[1].focus,{view_index:0,section_index:0});
  assert.match(panel._studio.render(),/Everything outside it stays unchanged/);
});
