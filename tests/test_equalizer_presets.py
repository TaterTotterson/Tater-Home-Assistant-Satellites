"""Preset migration, live edits, capability gating, and device synchronization."""
from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('eq_settings', ROOT / 'custom_components/tater_satellite/settings.py')
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)
CAPS = {'output_chain': True, 'eq_presets': True}


def bands(values):
    return [values[key] for key, _ in settings.EQ_BANDS]


def manager_methods(*names):
    tree = ast.parse((ROOT / 'custom_components/tater_satellite/manager.py').read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'TaterSatelliteManager')
    scope = {'Any': Any, 'SatelliteRuntime': SimpleNamespace, 'text': lambda value: str(value or '').strip(),
             'EQUALIZER_SETTING_KEYS': settings.EQUALIZER_SETTING_KEYS, 'reported_equalizer': settings.reported_equalizer}
    nodes = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<actual EQ manager methods>', 'exec'), scope)
    return {name: scope[name] for name in names}


class EqualizerPresetTests(unittest.TestCase):
    def test_default_and_legacy_saved_curves(self):
        fresh = settings.merged_settings({}, {})
        self.assertEqual(fresh['eq_preset'], 'warm')
        self.assertEqual(bands(fresh), settings.EQ_PRESETS['warm'])
        for curve in (settings.EQ_PRESETS['flat'], settings.EQ_PRESETS['warm'], [2, 1, 0, -1, -2, -3, -4, -5]):
            saved = {key: curve[index] for index, (key, _) in enumerate(settings.EQ_BANDS)}
            for actual in (settings.normalize_settings(saved), settings.merged_settings({}, saved)):
                self.assertEqual(actual['eq_preset'], 'manual')
                self.assertEqual(bands(actual), curve)
        partial = settings.merged_settings({}, {'eq_band_125': 4})
        self.assertEqual(partial['eq_preset'], 'manual')
        self.assertEqual(bands(partial), [4, 0, 0, 0, 0, 0, 0, 0])
        old_global = settings.merged_settings({'eq_band_125': 0, 'eq_loudness': False}, {})
        self.assertEqual(old_global['eq_preset'], 'manual')
        self.assertEqual(bands(old_global), [0] * 8)

    def test_named_selection_and_manual_edits_are_complete_and_stable(self):
        current = settings.normalize_settings({'eq_preset': 'manual', 'eq_band_125': 6, 'eq_loudness': True, 'bass_guard_db': -10})
        for name, curve in settings.EQ_PRESETS.items():
            patch = settings.normalize_settings({'eq_preset': name}, base=current, partial=True)
            selected = settings.normalize_settings({**current, **patch})
            self.assertEqual(bands(selected), curve)
            self.assertEqual(selected['eq_preset'], name)
            self.assertIs(selected['eq_loudness'], False)
            self.assertEqual(selected['bass_guard_db'], -10)
            self.assertEqual(settings.merged_settings({}, selected)['eq_preset'], name)
        current = settings.normalize_settings({'eq_preset': 'voice'})
        manual = settings.normalize_settings({'eq_preset': 'manual'}, base=current, partial=True)
        self.assertEqual(bands(manual), settings.EQ_PRESETS['voice'])
        edit = settings.normalize_settings({'eq_band_125': 4.2}, base=current, partial=True)
        self.assertEqual(edit['eq_preset'], 'manual')
        self.assertEqual(bands(edit), [4.2, *settings.EQ_PRESETS['voice'][1:]])
        self.assertEqual(settings.normalize_settings({'eq_loudness': True}, base=current, partial=True)['eq_preset'], 'manual')
        self.assertEqual(settings.normalize_settings({'volume_percent': 20}, base=current, partial=True), {'volume_percent': 20})
        stale = settings.normalize_settings({'eq_preset': 'warm', 'eq_band_125': 5})
        self.assertEqual(stale['eq_preset'], 'manual')
        self.assertEqual(bands(stale), [5, *settings.EQ_PRESETS['warm'][1:]])

    def test_metadata_only_reaches_capable_firmware(self):
        for caps in ({}, {'output_chain': True}, CAPS):
            payload = settings.firmware_payload({'eq_preset': 'voice'}, board='rook', capabilities=caps)
            self.assertEqual('eq_preset' in payload, caps.get('eq_presets') is True)
            if caps.get('output_chain'):
                self.assertEqual(payload['eq_bands'], settings.EQ_PRESETS['voice'])
        field = next(field for section in settings.SETTINGS_SCHEMA for field in section['fields'] if field['key'] == 'eq_preset')
        self.assertEqual(field['presets'], settings.EQ_PRESETS)
        self.assertEqual(field['band_keys'], [key for key, _ in settings.EQ_BANDS])
        self.assertNotIn('eq_preset', settings.VOICE_DEFAULT_SETTING_KEYS)

    def test_local_reports_are_validated_scoped_and_persisted(self):
        adopt = manager_methods('_adopt_reported_device_equalizer')['_adopt_reported_device_equalizer']
        manager = SimpleNamespace(data={}, store=Mock(), _settings_cache={'one': {'eq_preset': 'warm'}})
        runtime = SimpleNamespace(device_id='one', capabilities=CAPS, record={'overrides': {'bass_guard_db': -10}})
        runtime.effective_settings = lambda: settings.merged_settings({}, runtime.record.get('overrides'))
        report = {'eq_preset': 'voice', 'eq_bands': settings.EQ_PRESETS['voice'], 'eq_loudness': False}
        self.assertTrue(adopt(manager, runtime, {'settings': report}))
        self.assertEqual(runtime.record['overrides']['eq_preset'], 'voice')
        self.assertEqual(runtime.record['overrides']['bass_guard_db'], -10)
        self.assertEqual(manager._settings_cache, {})
        self.assertFalse(adopt(manager, runtime, {'settings': report}))
        for invalid in (None, {}, {'eq_preset': 'bad'}, {**report, 'eq_bands': [0]}, {**report, 'eq_bands': [float('nan')] * 8}, {**report, 'eq_bands': [True] * 8}, {**report, 'eq_loudness': 'on'}):
            self.assertFalse(adopt(manager, runtime, {'settings': invalid}))
        for payload in ({'ok': False, 'settings': report}, {'error': 'rejected', 'settings': report}):
            self.assertFalse(adopt(manager, runtime, payload))
        runtime.capabilities = {'output_chain': True}
        self.assertFalse(adopt(manager, runtime, {'settings': report}))
        manager.store.async_delay_save.assert_called_once()

    def test_restored_device_eq_is_adopted_only_before_first_host_override(self):
        methods = manager_methods('_adopt_reported_device_equalizer', '_update_record_from_hello')
        manager = SimpleNamespace(data={}, store=Mock(), _settings_cache=None, async_save=AsyncMock(), _sync_firmware_room=Mock())
        manager._adopt_reported_device_equalizer = lambda *args, **kwargs: methods['_adopt_reported_device_equalizer'](manager, *args, **kwargs)
        runtime = SimpleNamespace(device_id='one', room='Kitchen', capabilities=CAPS, record={'capabilities': CAPS})
        runtime.effective_settings = lambda: settings.merged_settings({}, runtime.record.get('overrides'))
        report = {'eq_preset': 'voice', 'eq_bands': settings.EQ_PRESETS['voice'], 'eq_loudness': False}
        asyncio.run(methods['_update_record_from_hello'](manager, runtime, {'eq_settings': report}))
        self.assertEqual(runtime.record['overrides']['eq_preset'], 'voice')
        manager.async_save.assert_awaited_once()
        for existing in ({'eq_preset': 'flat'}, {'eq_band_125': 0}, {'eq_loudness': True}):
            runtime.record['overrides'] = dict(existing)
            asyncio.run(methods['_update_record_from_hello'](manager, runtime, {'eq_settings': report}))
            self.assertEqual(runtime.record['overrides'], existing)
        source = (ROOT / 'custom_components/tater_satellite/manager.py').read_text()
        handler = source[source.index('async def async_handle_websocket'):]
        self.assertLess(handler.index('await self._update_record_from_hello(runtime, payload)'), handler.index('await self.async_push_settings(runtime)'))

    def test_local_band_and_boost_deltas_preserve_the_other_eq_values(self):
        current = settings.normalize_settings({'eq_preset': 'voice'})
        boost = settings.reported_equalizer({'eq_preset': 'manual', 'eq_loudness': True}, current)
        self.assertEqual(bands(boost), settings.EQ_PRESETS['voice'])
        self.assertEqual(boost['eq_preset'], 'manual')
        self.assertIs(boost['eq_loudness'], True)
        curve = [4.2] * 8
        edited = settings.reported_equalizer({'eq_preset': 'manual', 'eq_bands': curve}, boost)
        self.assertEqual(bands(edited), curve)
        self.assertIs(edited['eq_loudness'], True)


if __name__ == '__main__':
    unittest.main()
