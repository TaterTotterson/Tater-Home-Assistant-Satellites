from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_PATH = ROOT / "custom_components" / "tater_satellite" / "firmware.py"
HTTP_PATH = ROOT / "custom_components" / "tater_satellite" / "http.py"
PANEL_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "frontend"
    / "tater-satellite-panel.js"
)


def _load_usb_offset_helper():
    source = FIRMWARE_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    selected = []
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id in {"USB_APP_PARTITION_SIZE", "USB_APP_PARTITION_OFFSETS"}
            for target in node.targets
        ):
            selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "usb_app_partition_offsets":
            selected.append(node)
    namespace = {"Any": object}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(FIRMWARE_PATH), "exec"), namespace)
    return namespace["usb_app_partition_offsets"]


class FirmwareUsbModeTests(unittest.TestCase):
    def test_keep_settings_offsets_match_native_partition_layouts(self) -> None:
        offsets = _load_usb_offset_helper()

        self.assertEqual(offsets("8MB"), (0x20000, 0x320000))
        self.assertEqual(offsets("16MB"), (0x20000, 0x320000, 0x620000))
        with self.assertRaisesRegex(ValueError, "do not support flash size"):
            offsets("4MB")

    def test_web_manifest_switches_artifact_offsets_and_erase_prompt(self) -> None:
        source = FIRMWARE_PATH.read_text(encoding="utf-8")

        self.assertIn('signed = await self.async_prepare(board, kind)', source)
        self.assertIn('if kind == "factory"\n            else usb_app_partition_offsets', source)
        self.assertIn('"new_install_prompt_erase": kind == "factory"', source)
        self.assertIn('{"path": binary_url, "offset": offset}', source)

    def test_recovery_api_and_panel_send_the_selected_flash_kind(self) -> None:
        http_source = HTTP_PATH.read_text(encoding="utf-8")
        panel_source = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn('flash_kind = str(body.get("flash_kind") or "factory")', http_source)
        self.assertIn('"preserves_settings": flash_kind == "ota"', http_source)
        self.assertIn('data-recovery-kind="factory"', panel_source)
        self.assertIn('data-recovery-kind="ota"', panel_source)
        self.assertIn("OTA Update · Keep Settings", panel_source)
        self.assertIn("flash_kind: flashKind", panel_source)
        self.assertIn("browserUsbCapability()", panel_source)
        self.assertIn("window.isSecureContext", panel_source)
        self.assertIn("typeof serial.requestPort", panel_source)

    def test_browser_usb_capability_distinguishes_context_and_web_serial(self) -> None:
        script = textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const source = fs.readFileSync(process.argv[1], "utf8");
            const start = source.indexOf("const browserUsbCapability =");
            const end = source.indexOf("\n\nconst formatApiError", start);
            assert.notStrictEqual(start, -1, "Missing browserUsbCapability");
            assert.notStrictEqual(end, -1, "Missing capability function boundary");

            function capability(windowValue, navigatorValue) {
              const context = { window: windowValue, navigator: navigatorValue };
              vm.createContext(context);
              vm.runInContext(`${source.slice(start, end)}\nthis.checkBrowserUsb = browserUsbCapability;`, context);
              return context.checkBrowserUsb();
            }

            const insecure = capability({ isSecureContext: false }, { serial: { requestPort() {} } });
            assert.strictEqual(insecure.available, false);
            assert.match(insecure.message, /secure/i);

            const missingSerial = capability({ isSecureContext: true }, {});
            assert.strictEqual(missingSerial.available, false);
            assert.match(missingSerial.message, /does not expose Web Serial/i);

            const ready = capability({ isSecureContext: true }, { serial: { requestPort() {} } });
            assert.strictEqual(ready.available, true);
            """
        )
        result = subprocess.run(
            ["node", "-e", script, str(PANEL_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
