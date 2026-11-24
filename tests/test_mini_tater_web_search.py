from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_tater_assistant import tater, _Manager

web = sys.modules[tater.WebSearchTool.__module__]


def source(index=1):
    return {"title": f"Source {index}", "url": f"https://example.org/{index}", "snippet": f"Verified search snippet {index}."}


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = _Manager()
        self.manager.hass.async_add_executor_job = AsyncMock(side_effect=asyncio.to_thread)
        self.runtime = tater.MiniTaterRuntime(self.manager)
        self.tool = self.runtime.ha_tools[web.WEB_SEARCH_TOOL_ID]

    async def call(self, query="What is new in Home Assistant?"):
        return await self.tool.async_call({"query": query}, None, device_id="private-satellite-id")

    async def test_search_runs_in_executor_and_sends_only_the_locked_question(self):
        event_loop_thread = threading.get_ident()

        def search(query):
            self.assertNotEqual(threading.get_ident(), event_loop_thread)
            self.assertEqual(query, "What is new in Home Assistant?")
            return {"provider": "duckduckgo", "sources": [source()]}

        with patch.object(web, "_search_web", side_effect=search):
            result = await self.call()
        self.assertTrue(result["ok"])
        self.assertEqual(result["sources"], [source()])
        self.assertEqual(result["content_kind"], "search_snippets")
        self.assertNotIn("private-satellite-id", json.dumps(result))
        self.assertIn("not instructions", result["say_hint"])
        self.manager.hass.async_add_executor_job.assert_awaited_once()

    async def test_cache_is_short_bounded_and_cannot_be_mutated_by_a_caller(self):
        with patch.object(web, "_search_web", return_value={"provider": "duckduckgo", "sources": [source()]}) as search:
            first = await self.call()
            first["sources"][0]["title"] = "Changed by caller"
            second = await self.call()
            self.assertEqual(second["sources"][0]["title"], "Source 1")
            self.assertEqual(search.call_count, 1)
            key = "What is new in Home Assistant?"
            self.tool._cache[key] = (time.monotonic() - web.CACHE_SECONDS - 1, "duckduckgo", [source(2)])
            await self.call()
            self.assertEqual(search.call_count, 2)
            for index in range(35):
                await self.call(f"public question {index}")
            self.assertLessEqual(len(self.tool._cache), 32)

    async def test_empty_rate_limited_and_failed_searches_are_not_cached(self):
        for outcome, code in [
            ({"provider": "duckduckgo", "sources": []}, "no_results"),
            (web.WebSearchError("rate_limited", "DuckDuckGo is limiting searches right now."), "rate_limited"),
            (TimeoutError(), "timeout"),
            (RuntimeError("raw provider internals"), "unavailable"),
        ]:
            with self.subTest(code=code):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch.object(web, "_search_web", **kwargs) as search:
                    for _ in range(2):
                        result = await self.call()
                        self.assertFalse(result["ok"])
                        self.assertEqual(result["code"], code)
                        self.assertNotIn("raw provider internals", json.dumps(result))
                        self.assertNotIn("sources", result)
                    self.assertEqual(search.call_count, 2)

    async def test_empty_request_does_not_start_a_search(self):
        result = await self.call(" ")
        self.assertFalse(result["ok"])
        self.manager.hass.async_add_executor_job.assert_not_awaited()

    async def test_slow_search_is_bounded_and_cancellation_is_propagated(self):
        async def wait_forever(*args):
            await asyncio.Future()

        self.manager.hass.async_add_executor_job.side_effect = wait_forever
        with patch.object(web, "SEARCH_TIMEOUT_SECONDS", 0.01):
            result = await self.call()
        self.assertEqual(result["code"], "timeout")
        task = asyncio.create_task(self.call())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_hydra_delivers_snippets_to_hermes_and_persists_verified_chat_sources(self):
        query = "Look up the latest Home Assistant release"
        self.runtime._plan_turn = AsyncMock(return_value={
            "mode": "execute", "goal": query, "response": "",
            "steps": [{"id": "step-1", "intent": "Search online", "nl": query, "tool_hint": "web_search"}],
        })
        self.runtime._review_plan = AsyncMock(return_value=(True, ""))

        async def chat(messages, *, role, **kwargs):
            if role == "thanatos":
                self.assertEqual(kwargs["native_tools"][0]["function"]["name"], "web_search")
                return {"tool_calls": [{"function": {"name": "web_search", "arguments": json.dumps({"query": query})}}]}
            self.assertEqual(role, "hermes")
            self.assertIn("Verified search snippet 1", messages[-1]["content"])
            return {"content": "Here is the latest release information."}

        self.runtime._chat = AsyncMock(side_effect=chat)
        with patch.object(web, "_search_web", return_value={"provider": "duckduckgo", "sources": [source()]}):
            result = await self.runtime.async_process_text(query, conversation_id="web-test")
        expected = [{"title": "Source 1", "url": "https://example.org/1"}]
        self.assertEqual(result["sources"], expected)
        self.assertEqual(self.runtime.recent_messages(2)[-1]["sources"], expected)
        self.assertNotIn("https://", result["response"])
        self.assertEqual(result["tools"][0]["name"], "web_search")
        self.assertTrue(result["tools"][0]["approved"])
        self.assertEqual(self.manager.saved, 1)


class WebSourceTests(unittest.TestCase):
    def test_search_prefers_duckduckgo_and_uses_bing_only_after_failure_or_empty_results(self):
        with patch.object(web, "_search_provider", return_value=[source()]) as search:
            result = web._search_web("question")
            self.assertEqual(result["provider"], "duckduckgo")
            search.assert_called_once_with("question", "duckduckgo")
        for first in ([], web.WebSearchError("unavailable", "Blocked")):
            with patch.object(web, "_search_provider", side_effect=[first, [source(2)]]) as search:
                result = web._search_web("question")
                self.assertEqual(result["provider"], "bing")
                self.assertEqual(result["sources"], [source(2)])
                self.assertEqual([call.args for call in search.call_args_list], [("question", "duckduckgo"), ("question", "bing")])
        with patch.object(web, "_search_provider", side_effect=web.WebSearchError("rate_limited", "Try later")):
            with self.assertRaises(web.WebSearchError):
                web._search_web("question")

    def test_results_are_bounded_deduplicated_and_safe_for_links(self):
        unsafe = [
            "javascript:alert(1)", "data:text/html,hello", "//example.org/path",
            "https://user:password@example.org/", "https://example.org/\npath",
            "https://[broken/", "https://example.org:99999/", "https://example.org:0/",
            "https://example.org/\\evil", "https://example.org/" + "x" * 2050,
        ]
        rows = [{"title": "Unsafe", "url": url} for url in unsafe]
        rows.extend([{"title": "A &amp; B", "href": "https://example.org/valid", "body": "x" * 2000}] * 2)
        rows.extend(source(index) for index in range(20))
        result = web.normalize_sources(rows)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["title"], "A & B")
        self.assertEqual(len(result[0]["snippet"]), 1200)
        self.assertEqual(len({row["url"] for row in result}), 5)

    def test_only_successful_search_steps_can_publish_sources(self):
        result = web.sources_from_executions([
            {"tool_hint": "device_control", "result": {"ok": True, "sources": [source(1)]}},
            {"tool_hint": "web_search", "result": {"ok": False, "sources": [source(2)]}},
            {"tool_hint": "web_search", "result": {"ok": True, "sources": [source(3), source(3)]}},
        ])
        self.assertEqual(result, [{"title": "Source 3", "url": "https://example.org/3"}])

    def test_ddgs_uses_duckduckgo_with_tls_and_handles_provider_failures(self):
        class ProviderError(Exception):
            pass

        class RateLimited(ProviderError):
            pass

        class ProviderTimeout(ProviderError):
            pass

        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=None)
        factory = Mock(return_value=client)
        modules = {
            "ddgs": SimpleNamespace(DDGS=factory),
            "ddgs.exceptions": SimpleNamespace(DDGSException=ProviderError, RatelimitException=RateLimited, TimeoutException=ProviderTimeout),
        }
        with patch.dict(sys.modules, modules):
            client.text.return_value = [{"title": "Example", "href": "https://example.org", "body": "A fact."}]
            self.assertEqual(len(web._search_provider("the complete question", "duckduckgo")), 1)
            factory.assert_called_once_with(timeout=5)
            client.text.assert_called_once_with("the complete question", backend="duckduckgo", max_results=5, safesearch="moderate")
            for error, code in [(RateLimited(), "rate_limited"), (ProviderTimeout(), "timeout"), (ProviderError(), "unavailable")]:
                client.text.side_effect = error
                with self.assertRaises(web.WebSearchError) as raised:
                    web._search_provider("question", "duckduckgo")
                self.assertEqual(raised.exception.code, code)


if __name__ == "__main__":
    unittest.main()
