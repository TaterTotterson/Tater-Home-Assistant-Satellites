from __future__ import annotations

from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from test_tater_assistant import tater

provider = importlib.import_module(tater.__package__ + ".dashboard_provider")
SETTINGS = {"base_url": "http://designer:8000/v1", "model": "studio-model", "api_key": "secret-key"}
DESIGN = {"message": "A calm layout", "config": None}
MESSAGES = [{"role": "user", "content": "Design my dashboard"}]


class Response:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = provider.DashboardProvider(SimpleNamespace())

    async def test_native_output_uses_only_studio_model_and_credentials(self):
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return Response(
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "dashboard_design",
                                            "arguments": json.dumps(DESIGN),
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            )

        self.client._session = lambda: SimpleNamespace(post=post)
        result = await self.client.design(MESSAGES, SETTINGS, {"type": "object"})
        self.assertEqual(result, DESIGN)
        url, request = calls[0]
        self.assertEqual(url, "http://designer:8000/v1/chat/completions")
        self.assertEqual(request["timeout"].total, 600)
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(request["json"]["model"], "studio-model")
        self.assertEqual(request["json"]["messages"], MESSAGES)
        self.assertNotIn("secret-key", json.dumps(request["json"]))
        self.assertEqual(len(request["json"]["tools"]), 1)
        self.assertEqual(request["json"]["tools"][0]["function"]["name"], "dashboard_design")

    async def test_base_url_variants_and_key_free_local_servers(self):
        urls = []

        def post(url, **kwargs):
            urls.append(url)
            self.assertNotIn("Authorization", kwargs["headers"])
            return Response({})

        self.client._session = lambda: SimpleNamespace(post=post)
        for base in (
            "http://host:8000",
            "http://host:8000/v1/",
            "http://host:8000/v1/chat/completions",
        ):
            await self.client._post({**SETTINGS, "base_url": base, "api_key": ""}, {})
        self.assertEqual(urls, ["http://host:8000/v1/chat/completions"] * 3)

    async def test_unsupported_tools_fall_back_to_plain_json_without_device_tools(self):
        calls = []

        async def post(settings, payload):
            calls.append(deepcopy(payload))
            if "tools" in payload:
                raise provider.ProviderError(400, "tools are unsupported")
            return {
                "choices": [{"message": {"content": "```json\n" + json.dumps(DESIGN) + "\n```"}}]
            }

        self.client._post = post
        self.assertEqual(await self.client.design(MESSAGES, SETTINGS, {}), DESIGN)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("tools", calls[1])
        self.assertNotIn("tool_choice", calls[1])
        self.assertEqual(calls[1]["model"], "studio-model")

    async def test_plain_json_fallback_gets_the_full_schema_including_focused_repairs(self):
        from test_dashboard_studio import studio

        schema = studio.section_repair_schema([1, 2])
        replies = [
            {
                "view_index": index,
                "sections": [{"type": "grid", "cards": [{"type": "heading", "heading": "Home"}]}],
            }
            for index in (1, 2)
        ]
        self.client._chat = AsyncMock(
            side_effect=[{}, {"content": json.dumps({"repairs": replies})}]
        )
        self.assertEqual((await self.client.design(MESSAGES, SETTINGS, schema))["repairs"], replies)
        fallback = self.client._chat.call_args.args[0][-1]["content"]
        self.assertIn(json.dumps(schema, ensure_ascii=False), fallback)
        self.assertIn('"required": ["repairs"]', fallback)

    async def test_unsupported_temperature_and_required_choice_are_retried(self):
        calls = []

        async def post(settings, payload):
            calls.append(deepcopy(payload))
            if len(calls) == 1:
                raise provider.ProviderError(400, "temperature is unsupported")
            if len(calls) == 2:
                raise provider.ProviderError(400, "tool_choice required is unsupported")
            return {"choices": [{"message": {"content": json.dumps(DESIGN)}}]}

        self.client._post = post
        self.assertEqual(await self.client.design(MESSAGES, SETTINGS, {}), DESIGN)
        self.assertNotIn("temperature", calls[-1])
        self.assertEqual(calls[-1]["tool_choice"], "auto")

    async def test_auth_errors_do_not_retry_and_redact_the_configured_key(self):
        calls = []

        def post(*args, **kwargs):
            calls.append(kwargs)
            return Response({"error": {"message": "Invalid API key secret-key"}}, 401)

        self.client._session = lambda: SimpleNamespace(post=post)
        with self.assertRaises(provider.ProviderError) as raised:
            await self.client.design(MESSAGES, SETTINGS, {})
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret-key", str(raised.exception))
        self.assertIn("[redacted]", str(raised.exception))

    async def test_invalid_output_is_reported_and_transport_errors_hide_credentials(self):
        self.client._chat = AsyncMock(return_value={"content": "not a design"})
        with self.assertRaisesRegex(RuntimeError, "valid design"):
            await self.client.design(MESSAGES, SETTINGS, {})
        self.assertEqual(self.client._chat.await_count, 2)

        def post(*args, **kwargs):
            raise provider.aiohttp.ClientConnectionError("secret-key in low-level error")

        self.client._session = lambda: SimpleNamespace(post=post)
        with self.assertRaisesRegex(RuntimeError, "Could not reach") as raised:
            await self.client._post(SETTINGS, {})
        self.assertNotIn("secret-key", str(raised.exception))

    async def test_slow_generation_is_distinguished_from_an_unreachable_server(self):
        def post(*args, **kwargs):
            raise TimeoutError("secret-key in low-level error")

        self.client._session = lambda: SimpleNamespace(post=post)
        with self.assertRaisesRegex(RuntimeError, "10-minute") as raised:
            await self.client._post(SETTINGS, {})
        self.assertNotIn("secret-key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
