from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "custom_components" / "tater_satellite" / "wake_bundle.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_wake_bundle", BUNDLE_PATH)
assert SPEC is not None and SPEC.loader is not None
wake_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wake_bundle)


class WakeBundleTests(unittest.TestCase):
    @staticmethod
    def schema_four_payload() -> dict:
        return {
            "schema_version": 4,
            "type": "tater_wake_word_bundle",
            "wake_word": "Hey Tater",
            "key": "hey_tater",
            "micro_wake_word": {
                "model": "hey_tater.tflite",
                "model_sha256": "a" * 64,
                "model_size_bytes": 1234,
                "micro": {
                    "probability_cutoff": 0.91,
                    "sliding_window_size": 4,
                },
            },
            "open_wake_word": {
                "artifacts": {
                    "onnx": {
                        "file": "hey_tater.oww.onnx",
                        "sha256": "b" * 64,
                        "size_bytes": 2345,
                    }
                },
                "recommended_threshold": 0.92,
                "recommended_patience": 3,
            },
            "nano_wake_word": {
                "default_architecture": "cnn",
                "variants": {
                    "cnn": {
                        "model": "hey_tater.nww.cnn.onnx",
                        "model_sha256": "c" * 64,
                        "model_size_bytes": 3456,
                        "recommended_threshold": 0.95,
                        "recommended_patience": 2,
                    }
                },
            },
            "wake_boundary": {
                "type": "wake_word_end",
                "model": "hey_tater.boundary.tflite",
                "model_sha256": "d" * 64,
                "model_size_bytes": 137984,
                "model_format": "tflite_stream_state_internal_quant",
                "quantization": "int8",
                "sample_rate": 16000,
                "threshold": 0.82,
                "tensor_arena_size": 65536,
                "search_before_ms": 700,
                "search_after_ms": 120,
            },
        }

    def test_schema_three_exposes_all_runtime_profiles(self) -> None:
        payload = {
            "schema_version": 3,
            "type": "tater_wake_word_bundle",
            "wake_word": "Hey Tater",
            "key": "hey_tater",
            "micro_wake_word": {
                "model": "hey_tater.tflite",
                "model_sha256": "a" * 64,
                "model_size_bytes": 1234,
                "micro": {
                    "probability_cutoff": 0.91,
                    "sliding_window_size": 4,
                },
                "tater_native": {"close_miss_threshold": 0.73},
            },
            "open_wake_word": {
                "artifacts": {
                    "onnx": {
                        "file": "hey_tater.oww.onnx",
                        "sha256": "d" * 64,
                        "size_bytes": 2345,
                    }
                },
                "recommended_threshold": 0.82,
                "recommended_patience": 2,
                "recommended_confirmation_threshold": 0.94,
                "recommended_confirmation_patience": 4,
            },
            "nano_wake_word": {
                "default_architecture": "cnn",
                "variants": {
                    "cnn": {
                        "model": "hey_tater.nww.cnn.onnx",
                        "model_sha256": "b" * 64,
                        "model_size_bytes": 3456,
                        "recommended_threshold": 0.95,
                        "recommended_patience": 2,
                    },
                    "gru": {
                        "model": "hey_tater.nww.gru.onnx",
                        "model_sha256": "c" * 64,
                        "model_size_bytes": 4567,
                        "recommended_threshold": 0.97,
                        "recommended_patience": 3,
                    },
                },
            },
        }

        result = wake_bundle.parse_wake_bundle(
            payload,
            "http://trainer.local:8789/api/trained_wake_words/hey_tater.wake-bundle.json",
            b"bundle",
            required_engine="nww",
            nww_architecture="gru",
        )

        self.assertEqual(
            result["manifest_url"],
            "http://trainer.local:8789/api/trained_wake_words/hey_tater.esphome.json",
        )
        self.assertEqual(result["wake_profile_threshold"], 0.91)
        self.assertEqual(result["wake_profile_sliding_window"], 4)
        self.assertEqual(result["wake_profile_close_miss_threshold"], 0.73)
        self.assertEqual(result["oww_profile_confirmation_threshold"], 0.94)
        self.assertEqual(result["nww_available_architectures"], "cnn,gru")
        self.assertEqual(result["nww_architecture"], "gru")
        self.assertEqual(result["nww_profile_threshold"], 0.97)
        self.assertEqual(result["nww_profile_patience"], 3)

    def test_schema_one_oww_bundle_remains_supported(self) -> None:
        result = wake_bundle.parse_wake_bundle(
            {
                "schema_version": 1,
                "type": "tater_wake_word_bundle",
                "wake_word": "Jarvis",
                "micro_wake_word": {
                    "manifest": "jarvis.json",
                    "model": "jarvis.tflite",
                },
                "open_wake_word": {
                    "artifacts": {"onnx": {"file": "jarvis.onnx"}}
                },
            },
            "https://example.test/models/jarvis.wake-bundle.json",
            b"legacy",
            required_engine="oww",
        )

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(
            result["manifest_url"], "https://example.test/models/jarvis.json"
        )
        self.assertTrue(result["bundle_has_mww"])
        self.assertTrue(result["bundle_has_oww"])
        self.assertEqual(result["nww_available_architectures"], "")

    def test_schema_two_embedded_micro_bundle_remains_supported(self) -> None:
        result = wake_bundle.parse_wake_bundle(
            {
                "schema_version": 2,
                "type": "tater_wake_word_bundle",
                "key": "computer",
                "micro_wake_word": {
                    "model": "computer.tflite",
                    "micro": {
                        "probability_cutoff": 0.96,
                        "sliding_window_size": 6,
                    },
                },
                "open_wake_word": {
                    "artifacts": {"onnx": {"file": "computer.onnx"}}
                },
            },
            "https://example.test/computer.wake-bundle.json",
            b"schema two",
            required_engine="oww",
        )

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["wake_profile_threshold"], 0.96)
        self.assertEqual(result["wake_profile_sliding_window"], 6)

    def test_nww_requires_a_bundle_with_nano_variant(self) -> None:
        with self.assertRaisesRegex(ValueError, "NanoWakeWord"):
            wake_bundle.parse_wake_bundle(
                {
                    "schema_version": 3,
                    "type": "tater_wake_word_bundle",
                    "key": "hey_tater",
                    "micro_wake_word": {
                        "model": "hey_tater.tflite",
                        "model_sha256": "a" * 64,
                        "model_size_bytes": 1234,
                    },
                },
                "https://example.test/hey_tater.wake-bundle.json",
                b"missing nano",
                required_engine="nww",
            )

    def test_schema_four_exposes_verified_boundary_and_bundle_revision(self) -> None:
        raw = b"schema-four-boundary-v1"
        result = wake_bundle.parse_wake_bundle(
            self.schema_four_payload(),
            "https://example.test/hey_tater.wake-bundle.json",
            raw,
            required_engine="nww",
        )
        revision = hashlib.sha256(raw).hexdigest()

        self.assertEqual(result["wake_bundle_schema_version"], 4)
        self.assertTrue(result["wake_boundary_available"])
        self.assertEqual(result["wake_boundary_threshold"], 0.82)
        self.assertEqual(result["wake_boundary_model_revision"], "d" * 64)
        self.assertEqual(result["wake_boundary_model_size_bytes"], 137984)
        self.assertEqual(result["wake_model_revision"], revision)
        self.assertEqual(result["oww_model_revision"], revision)
        self.assertEqual(result["nww_model_revision"], revision)

    def test_boundary_only_bundle_change_invalidates_all_engine_caches(self) -> None:
        payload = self.schema_four_payload()
        first = wake_bundle.parse_wake_bundle(
            payload,
            "https://example.test/hey_tater.wake-bundle.json",
            b"boundary-v1",
        )
        payload["wake_boundary"]["model_sha256"] = "e" * 64
        second = wake_bundle.parse_wake_bundle(
            payload,
            "https://example.test/hey_tater.wake-bundle.json",
            b"boundary-v2",
        )

        self.assertNotEqual(
            first["wake_model_revision"], second["wake_model_revision"]
        )
        self.assertNotEqual(
            first["oww_model_revision"], second["oww_model_revision"]
        )
        self.assertNotEqual(
            first["nww_model_revision"], second["nww_model_revision"]
        )
        self.assertEqual(
            second["wake_boundary_model_revision"],
            "e" * 64,
        )

    def test_schema_four_rejects_an_invalid_boundary_contract(self) -> None:
        payload = self.schema_four_payload()
        payload["wake_boundary"]["model"] = "../unsafe.boundary.tflite"

        with self.assertRaisesRegex(ValueError, "boundary model is invalid"):
            wake_bundle.parse_wake_bundle(
                payload,
                "https://example.test/hey_tater.wake-bundle.json",
                b"invalid boundary",
            )


if __name__ == "__main__":
    unittest.main()
