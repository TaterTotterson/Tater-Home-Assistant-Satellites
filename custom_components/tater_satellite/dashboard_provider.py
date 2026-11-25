"""Independent OpenAI-compatible connection for Dashboard Studio."""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp


class ProviderError(RuntimeError):
    def __init__(self, status, detail):
        super().__init__(f"Dashboard model returned HTTP {status}: {detail}")
        self.status = status


class DashboardProvider:
    def __init__(self, hass):
        self.hass = hass

    def _session(self):
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        return async_get_clientsession(self.hass)

    async def _post(self, settings, payload):
        base = settings["base_url"].rstrip("/")
        endpoint = (
            base
            if base.endswith("/chat/completions")
            else (base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"))
        )
        key = settings["api_key"]
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with self._session().post(
                endpoint, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status >= 400:
                    try:
                        data = await response.json()
                        detail = data.get("error", {}) if isinstance(data, dict) else ""
                        if isinstance(detail, dict):
                            detail = detail.get("message", "")
                    except (ValueError, aiohttp.ClientError):
                        detail = ""
                    detail = str(detail or "Request failed. Check the Studio connection settings.")
                    if key:
                        detail = detail.replace(key, "[redacted]")
                    raise ProviderError(response.status, detail[:500])
                data = await response.json()
        except TimeoutError:
            raise RuntimeError(
                "The dashboard model took too long to respond. Your saved draft is unchanged. Try a smaller request or check the model server."
            ) from None
        except aiohttp.ClientError:
            raise RuntimeError(
                "Could not reach the dashboard model. Check its address and try again."
            ) from None
        except ValueError:
            raise RuntimeError("The dashboard model returned invalid JSON.") from None
        if not isinstance(data, dict):
            raise RuntimeError("The dashboard model returned an invalid response.")
        return data

    async def _chat(self, messages, settings, tool=None):
        payload = {"model": settings["model"], "messages": messages, "temperature": 0.5}
        if tool:
            payload.update(tools=[tool], tool_choice="required")
        for _ in range(3):
            try:
                result = await self._post(settings, payload)
                break
            except ProviderError as err:
                detail = str(err).lower()
                if (
                    err.status in {400, 422}
                    and "temperature" in detail
                    and "temperature" in payload
                ):
                    payload.pop("temperature")
                elif (
                    err.status in {400, 422}
                    and "tool_choice" in detail
                    and payload.get("tool_choice") == "required"
                ):
                    payload["tool_choice"] = "auto"
                else:
                    raise
        else:
            raise RuntimeError("The dashboard model rejected the request.")
        choices = result.get("choices")
        message = (
            choices[0].get("message")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else None
        )
        if not isinstance(message, dict):
            raise RuntimeError("The dashboard model returned no response message.")
        return message

    @staticmethod
    def _object(content):
        if not isinstance(content, str):
            raise ValueError("Expected JSON text")
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
        try:
            value = json.loads(content)
        except ValueError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            value = json.loads(match.group(0)) if match else None
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    async def design(self, messages, settings, schema) -> dict[str, Any]:
        tool = {
            "type": "function",
            "function": {
                "name": "dashboard_design",
                "description": "Propose a dashboard draft or discuss its design without saving to HA.",
                "parameters": schema,
            },
        }
        try:
            message = await self._chat(messages, settings, tool)
        except ProviderError as err:
            if err.status not in {400, 404, 422} or not any(
                word in str(err).lower() for word in ("tools", "function", "tool_choice")
            ):
                raise
            message = {}
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                function = call.get("function") if isinstance(call, dict) else None
                if isinstance(function, dict) and function.get("name") == "dashboard_design":
                    try:
                        return self._object(function.get("arguments"))
                    except ValueError:
                        break
        try:
            return self._object(message.get("content"))
        except ValueError:
            pass
        # Local models without function calling can return the same object as text.
        fallback = await self._chat(
            messages
            + [
                {
                    "role": "user",
                    "content": "Return only a JSON object matching this output schema. Complete every required layout field with real content; do not return an outline. "
                    + json.dumps(schema, ensure_ascii=False),
                }
            ],
            settings,
        )
        try:
            return self._object(fallback.get("content"))
        except ValueError:
            raise RuntimeError(
                "The dashboard model did not return a valid design. Try again."
            ) from None
