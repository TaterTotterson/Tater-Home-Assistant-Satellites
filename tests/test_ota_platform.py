from __future__ import annotations

import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'custom_components/tater_satellite/firmware.py'


def policy_helper():
    module = ast.parse(SOURCE.read_text())
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('capability_version', 'ota_upgrade_requirement')]
    namespace = {'Any': Any}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['ota_upgrade_requirement']


class OTAPlatformTests(unittest.TestCase):
    def test_system_update_plan_is_only_available_after_usb_platform_upgrade(self):
        module = ast.parse(SOURCE.read_text())
        selected = [node for node in module.body if isinstance(node, ast.FunctionDef)
                    and node.name in ('capability_version', 'version_tuple', 'required_ota_migration', 'ota_upgrade_requirement')]
        selected.insert(0, next(node for node in module.body if isinstance(node, ast.Assign)
                                and any(isinstance(target, ast.Name) and target.id == '_VERSION' for target in node.targets)))
        selected.append(next(node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == 'ota_plan_for_board'))
        namespace = {'Any': Any, 're': re}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        device = {'ota_policy': {'package_schema': 2, 'platform': 'echo-hardware-v1/rook'},
                  'firmware_version': 'v5.0.1', 'minimum_system_version': 'v5.0.1',
                  'artifacts': {'system': {'path': 'system.tar.gz'}}, 'ota_migrations': []}
        catalog = SimpleNamespace(_device_row=lambda _board: device)
        plan = namespace['ota_plan_for_board']
        with self.assertRaisesRegex(RuntimeError, 'USB upgrade'):
            plan(catalog, 'rook', {})
        caps = {'ota_package_schema': 2, 'ota_platform': 'echo-hardware-v1/rook',
                'system_ota_version': 1, 'system_version': 'v5.0.0'}
        self.assertEqual(plan(catalog, 'rook', caps)['initial_kind'], 'system')
        self.assertEqual(plan(catalog, 'rook', caps)['final_kind'], 'ota')
        caps['system_version'] = 'v5.0.1'
        self.assertEqual(plan(catalog, 'rook', caps)['initial_kind'], 'ota')

    def test_legacy_missing_and_wrong_platform_are_blocked(self):
        check = policy_helper()
        for target in ('biscuit', 'radar', 'checkers', 'cronos', 'crown', 'athena', 'rook'):
            profile = f'echo-hardware-v1/{target}'
            device = {'ota_policy': {'package_schema': 2, 'platform': profile}}
            for capabilities in ({}, {'ota_package_schema': 1, 'ota_platform': profile},
                                 {'ota_package_schema': 2},
                                 {'ota_package_schema': 2, 'ota_platform': 'other'}):
                self.assertIn('USB upgrade', check(device, capabilities))
            self.assertEqual('', check(device, {'ota_package_schema': 2, 'ota_platform': profile}))

    def test_other_firmware_families_and_older_catalogs_are_unchanged(self):
        self.assertEqual('', policy_helper()({}, {}))
        for invalid in ('bad', {}, {'package_schema': True, 'platform': 'x'}):
            self.assertIn('blocked', policy_helper()({'ota_policy': invalid}, {}))

    def test_host_blocks_before_a_bridge_and_explains_usb_in_ui(self):
        source = SOURCE.read_text()
        plan = source.split('    def ota_plan_for_board(', 1)[1].split('    def _artifact_row(', 1)[0]
        self.assertLess(plan.index('ota_upgrade_requirement'), plan.index('required_ota_migration'))
        panel = (ROOT / 'custom_components/tater_satellite/frontend/tater-satellite-panel.js').read_text()
        self.assertIn('escapeHtml(firmware.ota_blocked_reason)', panel)


if __name__ == '__main__':
    unittest.main()
