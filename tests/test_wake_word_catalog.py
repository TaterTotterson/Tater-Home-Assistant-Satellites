from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "wake_word_catalog.py"
)
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"

CATALOG_SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_wake_word_catalog", CATALOG_PATH
)
assert CATALOG_SPEC is not None and CATALOG_SPEC.loader is not None
catalog = importlib.util.module_from_spec(CATALOG_SPEC)
CATALOG_SPEC.loader.exec_module(catalog)

SETTINGS_SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_catalog_settings", SETTINGS_PATH
)
assert SETTINGS_SPEC is not None and SETTINGS_SPEC.loader is not None
settings = importlib.util.module_from_spec(SETTINGS_SPEC)
SETTINGS_SPEC.loader.exec_module(settings)

V1_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/microWakeWordsV1/hey_tater.json"
)
V6_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/microWakeWordsV6/hey_tater.json"
)
V7_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/microWakeWordsV7/hey_tater.esphome.json"
)
V7_BUNDLE_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/microWakeWordsV7/hey_tater.wake-bundle.json"
)
V8_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/microWakeWordsV8/hey_tater.esphome.json"
)
V8_BUNDLE_URL = (
    "https://raw.githubusercontent.com/TaterTotterson/"
    "Tater-Wake-Words/main/microWakeWordsV8/hey_tater.wake-bundle.json"
)


class _FakeContent:
    def __init__(self, payload: bytes, chunk_size: int | None = None) -> None:
        self.payload = payload
        self.chunk_size = chunk_size
        self.offset = 0

    async def read(self, limit: int) -> bytes:
        if self.offset >= len(self.payload):
            return b""
        size = min(limit, self.chunk_size or limit)
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class _FakeResponse:
    def __init__(self, payload: bytes, chunk_size: int | None = None) -> None:
        self.content = _FakeContent(payload, chunk_size)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, payload: dict, chunk_size: int | None = None) -> None:
        self.payload = payload
        self.chunk_size = chunk_size
        self.calls = 0
        self.fail = False

    def get(self, _url: str, **_kwargs):
        self.calls += 1
        if self.fail:
            raise OSError("catalog offline")
        return _FakeResponse(
            json.dumps(self.payload).encode("utf-8"), self.chunk_size
        )


class WakeWordCatalogTests(unittest.TestCase):
    def test_manifest_keeps_only_versioned_official_models(self) -> None:
        entries = catalog.entries_from_manifest(
            {
                "entries": [
                    {
                        "source": "microWakeWordsV6",
                        "slug": "hey_tater",
                        "label": "Hey Tater",
                        "url": V6_URL,
                    },
                    {
                        "source": "microWakeWordsV1",
                        "slug": "hey_tater",
                        "path": "microWakeWordsV1/hey_tater.json",
                    },
                    {
                        "source": "microWakeWordsV7",
                        "slug": "unsafe",
                        "url": "https://example.test/unsafe.json",
                    },
                ]
            }
        )

        self.assertEqual([row["url"] for row in entries], [V1_URL, V6_URL])
        self.assertEqual(
            [row["version_label"] for row in entries], ["V1", "V6"]
        )

    def test_catalog_source_resolves_to_firmware_custom_url(self) -> None:
        resolved = catalog.resolve_wake_word_source_values(
            {
                "wake_word": "catalog",
                "wake_word_catalog_url": V6_URL,
                "wake_model_asset_id": "old-upload",
            }
        )

        self.assertEqual(resolved["wake_word"], "custom_url")
        self.assertEqual(resolved["wake_word_url"], V6_URL)
        self.assertEqual(resolved["wake_model_asset_id"], "")
        self.assertNotIn("wake_word_catalog_url", resolved)

    def test_catalog_rejects_non_official_urls(self) -> None:
        with self.assertRaisesRegex(ValueError, "official Tater catalog"):
            catalog.resolve_wake_word_source_values(
                {
                    "wake_word": "catalog",
                    "wake_word_catalog_url": "https://example.test/wake.json",
                }
            )

    def test_legacy_catalog_only_patch_remains_supported(self) -> None:
        resolved = catalog.resolve_wake_word_source_values(
            {"wake_word_catalog_url": V1_URL},
            allow_catalog_only=True,
        )

        self.assertEqual(resolved["wake_word"], "custom_url")
        self.assertEqual(resolved["wake_word_url"], V1_URL)

    def test_current_api_ignores_catalog_url_without_catalog_source(self) -> None:
        resolved = catalog.resolve_wake_word_source_values(
            {"wake_word_catalog_url": V1_URL}
        )

        self.assertEqual(resolved, {})

    def test_empty_orphaned_catalog_fields_do_not_block_global_saves(self) -> None:
        resolved = catalog.resolve_wake_word_source_values(
            {
                "oww_wake_word_catalog_url": "",
                "wake_verifier_mode": "observe",
            }
        )

        self.assertEqual(resolved, {"wake_verifier_mode": "observe"})

    def test_explicit_catalog_selection_still_requires_a_catalog_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "official Tater catalog"):
            catalog.resolve_wake_word_source_values(
                {
                    "oww_wake_word": "catalog",
                    "oww_wake_word_catalog_url": "",
                }
            )

    def test_companion_catalog_enforces_oww_v7_and_nww_v8(self) -> None:
        oww = catalog.resolve_wake_word_source_values(
            {
                "wake_detector_mode": "mww_oww",
                "oww_wake_word": "catalog",
                "oww_wake_word_catalog_url": V7_BUNDLE_URL,
            }
        )
        nww = catalog.resolve_wake_word_source_values(
            {
                "wake_detector_mode": "mww_nww",
                "oww_wake_word": "catalog",
                "oww_wake_word_catalog_url": V8_BUNDLE_URL,
            }
        )

        self.assertEqual(oww["oww_wake_word"], "custom_url")
        self.assertEqual(oww["oww_wake_word_url"], V7_BUNDLE_URL)
        self.assertEqual(nww["oww_wake_word_url"], V8_BUNDLE_URL)
        with self.assertRaisesRegex(ValueError, "V8-or-newer"):
            catalog.resolve_wake_word_source_values(
                {
                    "wake_detector_mode": "nww",
                    "oww_wake_word": "catalog",
                    "oww_wake_word_catalog_url": V7_BUNDLE_URL,
                }
            )

    def test_catalog_snapshot_splits_oww_and_nww_bundle_generations(self) -> None:
        entries = catalog.entries_from_manifest(
            {
                "entries": [
                    {
                        "source": "microWakeWordsV7",
                        "slug": "hey_tater",
                        "label": "Hey Tater",
                        "url": V7_URL,
                        "bundle_url": V7_BUNDLE_URL,
                        "dual_model": True,
                    },
                    {
                        "source": "microWakeWordsV8",
                        "slug": "hey_tater",
                        "label": "Hey Tater",
                        "url": V8_URL,
                        "bundle_url": V8_BUNDLE_URL,
                        "available_engines": [
                            "micro_wake_word",
                            "open_wake_word",
                            "nano_wake_word",
                        ],
                        "nanowakeword_architectures": ["cnn", "gru"],
                    },
                ]
            }
        )
        coordinator = catalog.WakeWordCatalog.__new__(catalog.WakeWordCatalog)
        coordinator._entries = entries
        coordinator.last_error = ""
        snapshot = coordinator.snapshot()

        self.assertEqual(
            [row["value"] for row in snapshot["oww_options"]],
            [V7_BUNDLE_URL, V8_BUNDLE_URL],
        )
        self.assertEqual(
            snapshot["nww_options"],
            [
                {
                    "value": V8_BUNDLE_URL,
                    "label": "Hey Tater [V8]",
                    "architectures": ["cnn", "gru"],
                }
            ],
        )

    def test_settings_schema_exposes_catalog_as_a_separate_source(self) -> None:
        wake_section = next(
            section
            for section in settings.SETTINGS_SCHEMA
            if section.get("section") == "wake"
        )
        by_key = {field["key"]: field for field in wake_section["fields"]}

        self.assertIn(
            {"value": "catalog", "label": "Tater Wake Word Catalog"},
            by_key["wake_word"]["options"],
        )
        self.assertEqual(
            by_key["wake_word_catalog_url"]["show_when"],
            {"key": "wake_word", "equals": "catalog"},
        )
        self.assertNotIn("catalog", settings._ALLOWED["wake_word"])

    def test_bridge_wires_catalog_endpoint_and_both_setting_scopes(self) -> None:
        integration = (
            ROOT / "custom_components" / "tater_satellite" / "__init__.py"
        ).read_text(encoding="utf-8")
        manager = (
            ROOT / "custom_components" / "tater_satellite" / "manager.py"
        ).read_text(encoding="utf-8")
        http = (
            ROOT / "custom_components" / "tater_satellite" / "http.py"
        ).read_text(encoding="utf-8")
        panel = (
            ROOT
            / "custom_components"
            / "tater_satellite"
            / "frontend"
            / "tater-satellite-panel.js"
        ).read_text(encoding="utf-8")
        assist = (
            ROOT / "custom_components" / "tater_satellite" / "assist_satellite.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(manager.count("resolve_wake_word_source_values("), 1)
        self.assertIn("allow_catalog_only=allow_catalog_only", manager)
        self.assertIn("self.wake_word_catalog.async_refresh()", manager)
        self.assertIn("class WakeWordCatalogView", http)
        self.assertIn("class WakeVerifierSettingsView", http)
        self.assertIn("class TrainerSettingsView", http)
        self.assertIn('settings/verifier"', http)
        self.assertIn('settings/trainer"', http)
        self.assertIn('this.api("GET", "wake-word/catalog")', panel)
        self.assertIn('this.api("POST", "settings/verifier"', panel)
        self.assertIn('this.api("POST", "settings/trainer"', panel)
        self.assertIn("pickSettings(this._globalDraft, VOICE_DEFAULT_SETTING_KEYS)", panel)
        self.assertIn("prepareSettingsDraft", panel)
        self.assertIn('input.dataset.setting === "oww_wake_word_catalog_url"', panel)
        self.assertIn('_CATALOG_WAKE_PREFIX = "catalog:"', assist)
        self.assertIn("wake_word_catalog.snapshot()", assist)
        self.assertIn("async_get_integration(hass, DOMAIN)", integration)
        self.assertIn("?v={quote(panel_version, safe='')}", integration)
        self.assertIn(
            "webcomponent_name=_panel_element_name(panel_version)", integration
        )
        self.assertIn("new URL(import.meta.url).searchParams.get(\"v\")", panel)
        self.assertIn("customElements.define(PANEL_ELEMENT_NAME", panel)
        self.assertIn("catalogUnavailable && catalogRetryDue", panel)


class WakeWordCatalogRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_fetch_reads_every_network_chunk(self) -> None:
        session = _FakeSession(
            {
                "entries": [
                    {
                        "source": "microWakeWordsV6",
                        "slug": "hey_tater",
                        "label": "Hey Tater",
                        "url": V6_URL,
                    }
                ]
            },
            chunk_size=17,
        )

        result = await catalog.WakeWordCatalog(session).async_refresh()

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["warning"], "")

    async def test_catalog_fetch_is_cached_and_compact(self) -> None:
        session = _FakeSession(
            {
                "entries": [
                    {
                        "source": "microWakeWordsV6",
                        "slug": "hey_tater",
                        "label": "Hey Tater",
                        "url": V6_URL,
                    }
                ]
            }
        )
        coordinator = catalog.WakeWordCatalog(session)

        first = await coordinator.async_refresh()
        second = await coordinator.async_refresh()

        self.assertEqual(session.calls, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["count"], 1)
        self.assertEqual(
            first["options"],
            [{"value": V6_URL, "label": "Hey Tater [V6]"}],
        )

        session.fail = True
        with self.assertLogs(catalog._LOGGER, level="WARNING"):
            stale = await coordinator.async_refresh(force=True)
        self.assertEqual(stale["options"], first["options"])
        self.assertIn("Could not refresh", stale["warning"])


if __name__ == "__main__":
    unittest.main()
