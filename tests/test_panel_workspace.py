from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PanelWorkspaceTests(unittest.TestCase):
    def test_changed_panel_gets_a_new_cache_identity(self):
        source = (ROOT / "custom_components/tater_satellite/__init__.py").read_text()
        nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "_panel_asset_revision"]
        scope = {"Path": Path, "hashlib": hashlib}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "<panel revision>", "exec"), scope)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panel.js"
            path.write_text("first panel")
            first = scope["_panel_asset_revision"](path)
            self.assertEqual(first, scope["_panel_asset_revision"](path))
            path.write_text("updated panel")
            self.assertNotEqual(first, scope["_panel_asset_revision"](path))

    def test_workspace_preserves_settings_drafts_and_save_contracts(self):
        spec = importlib.util.spec_from_file_location("workspace_settings", ROOT / "custom_components/tater_satellite/settings.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "settings.json"
            fixture.write_text(json.dumps({"schema": module.SETTINGS_SCHEMA, "defaults": module.DEFAULT_SETTINGS}))
            result = subprocess.run(
                ["node", str(ROOT / "tests/test_panel_workspace.mjs"), str(ROOT / "custom_components/tater_satellite/frontend/tater-satellite-panel.js"), str(fixture)],
                capture_output=True, text=True, cwd=ROOT, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
