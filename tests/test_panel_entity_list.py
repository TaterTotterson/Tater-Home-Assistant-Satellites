from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "frontend"
    / "tater-satellite-panel.js"
)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PanelEntityListTests(unittest.TestCase):
    def test_entity_list_renders_limits_and_saves_checked_values(self) -> None:
        script = textwrap.dedent(
            r"""
            import assert from "node:assert";
            import { pathToFileURL } from "node:url";

            globalThis.HTMLElement = class {
              attachShadow() { this.shadowRoot = { querySelectorAll: () => [] }; }
            };
            let Panel = null;
            globalThis.customElements = {
              get: () => undefined,
              define: (_name, cls) => { Panel = cls; },
            };
            await import(pathToFileURL(process.argv[1]).href);
            assert.ok(Panel, "panel class was not defined");

            const panel = new Panel();
            const field = {
              key: "screen_room_temperature_entities",
              label: "Room temperatures",
              type: "entity_list",
              max_items: 2,
              options: [
                { value: "sensor.kitchen", label: "Kitchen · Temperature" },
                { value: "sensor.den", label: "Den <b>" },
                { value: "sensor.attic", label: "Attic" },
              ],
            };

            // Two of two chosen: the third box is disabled and labels are escaped.
            let html = panel.renderField(field, { [field.key]: "sensor.kitchen,sensor.den" }, "device");
            assert.match(html, /Room temperatures \(2\/2\)/);
            assert.match(html, /value="sensor\.kitchen"\s+checked/);
            assert.match(html, /value="sensor\.attic"\s+disabled/);
            assert.match(html, /Den &lt;b&gt;/);

            // With room left, nothing is disabled.
            html = panel.renderField(field, { [field.key]: "sensor.kitchen" }, "device");
            assert.doesNotMatch(html, /disabled/);

            // No sensors: the empty label is shown.
            html = panel.renderField({ ...field, options: [], empty_label: "None here" }, {}, "device");
            assert.match(html, /None here/);

            // Ticking boxes through the real change handler saves a comma list.
            const boxes = field.options.map((option) => ({
              dataset: { settingList: field.key, scope: "device" },
              value: option.value,
              checked: false,
              listeners: {},
              addEventListener(type, fn) { this.listeners[type] = fn; },
            }));
            panel.shadowRoot = {
              querySelectorAll: (selector) => (selector === "[data-setting-list]" ? boxes : []),
              querySelector: () => null,
            };
            panel._deviceDraft = {};
            let renders = 0;
            panel.render = () => { renders += 1; };
            panel.bindEvents();
            boxes[0].checked = true;
            boxes[2].checked = true;
            boxes[2].listeners.change();
            assert.strictEqual(panel._deviceDraft[field.key], "sensor.kitchen,sensor.attic");
            assert.strictEqual(panel._dirty, true);
            assert.strictEqual(renders, 1);
            """
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script, str(PANEL_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
