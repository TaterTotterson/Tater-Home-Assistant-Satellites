"""Natural-language Timer Verba backed by satellite-owned timers.

The description and duration/name parsing follow Tater Shop's
verba/voicepe_remote_timer.py. Only live native commands cross the bridge;
satellites own countdowns, alarms, and timer state.
"""

from __future__ import annotations

import asyncio
import math
import re
import secrets
from typing import Any


TIMER_TOOL_ID = "voicepe_remote_timer"
TIMER_VERBA_DESCRIPTION = (
    "Use this for normal timer requests. Set, start, create, cancel, stop, silence, snooze, or check multiple named timers from one natural-language request. "
    "Pause, resume, and add or remove time from existing timers. "
    "Examples: set a pasta timer for 5 minutes; start a 90 second timer; how much time is left on the pasta timer; cancel the 10 minute timer."
)
MAX_TIMER_SECONDS = 7200
DEFAULT_SNOOZE_SECONDS = 300


class TimerTool:
    """Interpret one natural-language request and verify the satellite reply."""

    def __init__(self, manager, llm_json=None) -> None:
        self.manager = manager
        self._llm_json = llm_json

    @staticmethod
    def definition() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": TIMER_TOOL_ID,
                "description": TIMER_VERBA_DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "One complete natural-language timer request. Pass the locked step unchanged. "
                                "Include the duration naturally when starting a timer. Status and cancel need no duration. "
                                "Snooze defaults to five minutes."
                            ),
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }

    def summary(self) -> dict[str, Any]:
        satellites = [
            runtime
            for runtime in getattr(self.manager, "runtimes", {}).values()
            if runtime.connected and runtime.capabilities.get("timers")
        ]
        return {
            "satellite_count": len(satellites),
            "examples": [
                {"name": runtime.name, "room": runtime.room}
                for runtime in satellites[:8]
            ],
        }

    @staticmethod
    def _failure(message: str, *, code: str = "timer_failed", needs=None) -> dict[str, Any]:
        return {
            "ok": False,
            "code": code,
            "error": message,
            "needs": needs or [],
            "say_hint": message,
        }

    def _target(self, query: str, device_id: str):
        """Resolve explicit room/device wording, otherwise use trusted origin."""
        runtimes = getattr(self.manager, "runtimes", {})
        candidates = []
        for runtime in runtimes.values():
            for label in {runtime.name, runtime.room, runtime.device_id}:
                if not label:
                    continue
                match = re.search(
                    r"\b(?:on|in|at|from)\s+(?:the\s+)?"
                    + re.escape(label)
                    + r"(?:\s+(?:satellite|speaker|device))?(?=\s+(?:for|please)\b|[?.!,]*$)",
                    query,
                    flags=re.I,
                )
                if match:
                    candidates.append((len(label), runtime, match))
        if candidates:
            longest = max(row[0] for row in candidates)
            best = {row[1].device_id: row for row in candidates if row[0] == longest}
            if len(best) > 1 and device_id in best:
                best = {device_id: best[device_id]}
            if len(best) != 1:
                return None, query, self._failure(
                    "More than one satellite matches that room. Which satellite should I use?",
                    code="ambiguous_satellite",
                    needs=["Name the satellite for this timer."],
                )
            _, runtime, match = next(iter(best.values()))
            query = query[:match.start()] + " " + query[match.end():]
        else:
            location = re.search(
                r"\b(?:on|in|at|from)\s+(?:the\s+)?(.+?)(?=\s+for\b|[?.!,]*$)",
                query,
                flags=re.I,
            )
            if (
                location
                and location.group(1).strip().casefold()
                not in {"now", "here", "this room", "this satellite", "my room"}
                and not re.search(r"\btimers?\b", location.group(1), re.I)
            ):
                return None, query, self._failure(
                    "I couldn't match that location to a satellite. Which satellite or room should I use?",
                    code="unknown_satellite",
                    needs=["Name a known satellite or its assigned room."],
                )
            runtime = runtimes.get(device_id)
        if runtime is None:
            return None, query, self._failure(
                "Which satellite or room should I use for the timer?",
                code="missing_satellite",
                needs=["Name a satellite or room, or ask from a Tater satellite."],
            )
        if not runtime.connected:
            return None, query, self._failure(
                f"{runtime.name} is offline. I couldn't reach its timers.",
                code="satellite_unavailable",
            )
        if not runtime.capabilities.get("timers"):
            return None, query, self._failure(
                f"{runtime.name} does not support native timers with its current firmware.",
                code="timers_unsupported",
            )
        return runtime, query.strip(), None

    @staticmethod
    def _public_timer(row: dict[str, Any]) -> dict[str, Any]:
        def seconds(key):
            try:
                return max(0, math.ceil(float(row.get(key) or 0) / 1000))
            except (TypeError, ValueError, OverflowError):
                return 0

        return {
            "id": str(row.get("id") or row.get("timer_id") or ""),
            "name": str(row.get("name") or row.get("label") or ""),
            "state": str(row.get("state") or ("ringing" if row.get("ringing") else "armed")),
            "remaining_s": seconds("remaining_ms"),
            "original_duration_s": seconds("original_duration_ms") or seconds("duration_ms"),
        }

    async def _duration_fallback(self, query: str) -> int:
        if self._llm_json is None:
            return 0
        try:
            result = await self._llm_json(
                "Extract only the timer duration explicitly present in this natural-language request. "
                "Return JSON {\"seconds\": integer or null}. Parse spoken numbers and fractions; a bare "
                "number in a timer request means minutes. Use null if no duration is present. Do not "
                "invent a default duration or interpret a timer name as a duration.",
                {"request": query},
            )
            value = result.get("seconds")
            if value is None or isinstance(value, bool):
                return 0
            seconds = round(float(value))
            return max(0, min(seconds, MAX_TIMER_SECONDS))
        except (RuntimeError, ValueError, TypeError, OverflowError):
            return 0

    async def async_call(
        self,
        arguments: dict[str, Any],
        context,
        *,
        request: str = "",
        device_id: str = "",
    ) -> dict[str, Any]:
        del context
        query = str(arguments.get("query") or request or "").strip()
        if not query:
            return self._failure("What would you like to do with the timer?", code="missing_query")
        runtime, query, failure = self._target(query, device_id)
        if failure:
            return failure
        action, duration = self._resolve_action_duration({"query": query})
        paused = self.manager.data.get("tater_paused_timers", {}).get(runtime.device_id, {})
        if action in {"pause", "resume", "increase", "decrease"} or (paused and action in {"status", "cancel"}):
            return await self._extended(runtime, query, action)
        if action not in {"start", "status", "cancel", "snooze"}:
            return self._failure(
                "Would you like to start, check, cancel, or snooze a timer?",
                code="missing_action",
            )
        if re.search(r"(?<!\w)-\s*\d|\b(?:negative|minus)\s+", duration):
            return self._failure("The timer duration must be greater than zero.", code="invalid_duration")
        name = self._extract_timer_name({"query": query}, action)
        original_seconds = 0
        if action == "snooze":
            # The original duration selects a timer; "for ..." is the snooze
            # duration. Never add the two durations together.
            split = re.split(r"\s+for\s+", query, maxsplit=1, flags=re.I)
            if len(split) == 2:
                reference, snooze_for = split
                original_seconds = self._parse_duration_to_seconds(reference, MAX_TIMER_SECONDS)
                duration = self._extract_duration_from_text(snooze_for)
                if not duration:
                    return self._failure("How long should I snooze the timer?", code="invalid_duration")
            elif re.search(r"\b(?:hours?|minutes?|seconds?)\s+timer\b", query, re.I):
                original_seconds = self._parse_duration_to_seconds(duration, MAX_TIMER_SECONDS)
                duration = ""
        seconds = self._parse_duration_to_seconds(duration, MAX_TIMER_SECONDS) if duration else 0
        if action == "start" and not seconds:
            seconds = await self._duration_fallback(query)
            if not seconds:
                return self._failure(
                    "How long should I set the timer for?",
                    code="missing_duration",
                    needs=["Include a duration, such as five minutes or ninety seconds."],
                )
        if action == "snooze" and not seconds:
            if duration:
                return self._failure("How long should I snooze the timer?", code="invalid_duration")
            seconds = DEFAULT_SNOOZE_SECONDS

        payload: dict[str, Any] = {}
        if action == "start":
            payload = {
                "id": secrets.token_hex(6),
                "name": name,
                "label": name,
                "duration_ms": seconds * 1000,
                "original_duration_ms": seconds * 1000,
                "source": "mini_tater",
            }
            command = "timer.start"
        elif action == "status":
            command = "timer.list"
        else:
            command = "timer.cancel" if action == "cancel" else "timer.snooze"
            payload = {"name": name, "source": "mini_tater"}
            if action == "cancel":
                payload["all"] = bool(
                    re.search(r"\b(?:all|every)\s+(?:(?:of\s+)?(?:my|the)\s+)?timers?\b", query, re.I)
                )
                payload["original_duration_ms"] = seconds * 1000
            else:
                payload["duration_ms"] = seconds * 1000
                payload["original_duration_ms"] = original_seconds * 1000
        try:
            response = await runtime.async_request(command, payload, timeout=3.0)
        except asyncio.TimeoutError:
            return self._failure(
                f"{runtime.name} did not confirm the timer request. Its outcome is unknown; check its timers before retrying.",
                code="timer_timeout",
            )
        except Exception as err:
            return self._failure(
                f"I couldn't reach {runtime.name}'s timers: {err}",
                code="satellite_unavailable",
            )
        if not isinstance(response, dict) or response.get("ok") is not True:
            return self._failure(
                str(response.get("message") or response.get("error") or "The satellite did not confirm the timer request.")
                if isinstance(response, dict)
                else "The satellite returned an invalid timer response.",
            )
        if response.get("code") == "ambiguous":
            return self._failure(
                str(response.get("message") or "More than one timer matches. Tell me its name or original duration."),
                code="ambiguous_timer",
                needs=["Name the timer or its original duration."],
            )
        rows = response.get("timers")
        if action == "status" and not isinstance(rows, list):
            return self._failure("The satellite did not return a valid list of its current timers.")
        timers = [self._public_timer(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        timer = response.get("timer")
        if isinstance(timer, dict):
            timers.insert(0, self._public_timer(timer))
        if action == "status":
            if name:
                timers = [row for row in timers if row["name"].casefold() == name.casefold()]
            if seconds:
                timers = [row for row in timers if row["original_duration_s"] == seconds]
            timers.sort(key=lambda row: (row["state"] != "ringing", row["remaining_s"], row["name"]))
            summary = (
                "; ".join(self._timer_status(row) for row in timers) + "."
                if timers
                else "No matching timer is currently running."
            )
        elif action == "start":
            if not any(row["id"] == payload["id"] for row in timers):
                return self._failure("The satellite acknowledged the start but returned no timer to verify.")
            summary = f"{name.title() + ' timer' if name else 'Timer'} started for {self._format_remaining(seconds)} on {runtime.name}."
        else:
            try:
                affected = int(response.get("affected") or response.get("cancelled") or response.get("snoozed") or 0)
            except (TypeError, ValueError, OverflowError):
                affected = 0
            if affected <= 0:
                return self._failure(
                    "No matching timer is currently running.", code="timer_not_found"
                )
            label = f"{affected} timers" if affected > 1 else f"{name.title()} timer" if name else "Timer"
            summary = (
                f"{label} cancelled on {runtime.name}."
                if action == "cancel"
                else f"{label} snoozed for {self._format_remaining(seconds)} on {runtime.name}."
            )
        return {
            "ok": True,
            "facts": {
                "action": action,
                "satellite": runtime.name,
                "device_id": runtime.device_id,
                "room": runtime.room,
                "name": name,
                "duration_s": seconds,
                "affected": 1 if action == "start" else len(timers) if action == "status" else affected,
            },
            "data": {"timers": timers},
            "summary_for_user": summary,
            "say_hint": "Report the verified timer result naturally, with the name, duration or time left, and satellite when helpful.",
        }

    async def _extended(self, runtime, query: str, action: str) -> dict[str, Any]:
        """Use existing confirmed clear/arm commands; paused snapshots live in HA."""
        if re.search(r"(?<!\w)-\s*\d|\b(?:negative|minus)\s+", query, re.I):
            return self._failure("Use a positive amount of time to add or remove.", code="invalid_duration")
        try:
            response = await runtime.async_request("timer.list", {}, timeout=3.0)
            if not isinstance(response, dict) or response.get("ok") is not True or not isinstance(response.get("timers"), list):
                return self._failure("The satellite did not return its live timers.")
            stored = self.manager.data.get("tater_paused_timers", {}).get(runtime.device_id, {})
            live = {row["id"]: row for raw in response["timers"] if isinstance(raw, dict) and (row := self._public_timer(raw))["id"]}
            combined = {**stored, **live}
            if action in {"increase", "decrease"}:
                by = re.split(r"\bby\s+", query, maxsplit=1, flags=re.I)
                parts = re.split(r"\b(?:to|from)\s+(?:(?:the|my)\s+)?", query, maxsplit=1, flags=re.I)
                amount = self._parse_duration_to_seconds(by[1] if len(by) == 2 else parts[0], MAX_TIMER_SECONDS)
                if amount <= 0:
                    return self._failure("How much time should I add or remove?")
                reference = by[0] if len(by) == 2 else parts[1] if len(parts) == 2 else query
                reference = re.sub(r"\b(?:add|increase|extend|remove|decrease|subtract|shorten)\b", "", reference, flags=re.I)
                name = self._clean_timer_name(reference)
                original = self._parse_duration_to_seconds(reference, MAX_TIMER_SECONDS) if len(by) == 2 or len(parts) == 2 else 0
            else:
                amount = 0
                reference = re.sub(r"^\s*(?:pause|resume|unpause)\s+", "", query, flags=re.I)
                name = self._clean_timer_name(reference) if action in {"pause", "resume"} else self._extract_timer_name({"query": query}, action)
                original = self._parse_duration_to_seconds(reference, MAX_TIMER_SECONDS)
            if name in {"all", "every", "running", "active"}:
                name = ""
            rows = [row for row in combined.values() if (not name or row["name"].casefold() == name.casefold()) and (not original or row["original_duration_s"] == original)]
            if action == "status":
                return {"ok": True, "data": {"timers": rows}, "summary_for_user": "; ".join(self._timer_status(row) for row in rows) + "." if rows else "No matching timer is currently running."}
            all_requested = bool(re.search(r"\b(?:all|every)\b.*\btimers?\b", query, re.I))
            if not rows:
                return self._failure("No matching timer is currently running.", code="timer_not_found")
            if len(rows) != 1 and not (action == "cancel" and all_requested):
                return self._failure("More than one timer matches. Name the timer or its original duration.", code="ambiguous_timer")
            changed = []
            paused = self.manager.data.setdefault("tater_paused_timers", {}).setdefault(runtime.device_id, {})
            for row in rows:
                timer_id = row["id"]
                if action == "cancel" and timer_id not in live:
                    paused.pop(timer_id, None)
                    changed.append(row)
                    await self.manager.async_save()
                    continue
                if action == "pause":
                    if row["state"] == "paused":
                        return self._failure("That timer is already paused.")
                    if row["state"] == "ringing":
                        return self._failure("That timer is already ringing. Cancel or snooze it instead.")
                    reply = await runtime.async_request("timer.cancel", {"id": timer_id}, timeout=3.0)
                    if not isinstance(reply, dict) or reply.get("ok") is not True or int(reply.get("affected") or reply.get("cancelled") or 0) < 1:
                        return self._failure("The satellite did not confirm the pause.")
                    row = {**row, "state": "paused"}
                    paused[timer_id] = row
                elif action == "cancel":
                    reply = await runtime.async_request("timer.cancel", {"id": timer_id}, timeout=3.0)
                    if not isinstance(reply, dict) or reply.get("ok") is not True or int(reply.get("affected") or reply.get("cancelled") or 0) < 1:
                        return self._failure("The satellite did not confirm the cancellation.")
                    paused.pop(timer_id, None)
                else:
                    if action == "resume" and row["state"] != "paused":
                        return self._failure("That timer is already running.")
                    remaining = row["remaining_s"] + (amount if action == "increase" else -amount if action == "decrease" else 0)
                    if not 0 < remaining <= MAX_TIMER_SECONDS:
                        return self._failure("The resulting timer duration must be greater than zero and at most two hours.")
                    row = {**row, "remaining_s": remaining}
                    if row["state"] == "paused" and action != "resume":
                        paused[timer_id] = row
                    else:
                        payload = {"id": timer_id, "name": row["name"], "duration_ms": remaining * 1000, "remaining_ms": remaining * 1000, "original_duration_ms": row["original_duration_s"] * 1000, "source": "mini_tater"}
                        reply = await runtime.async_request("timer.arm", payload, timeout=3.0)
                        confirmed = reply.get("timer") if isinstance(reply, dict) else None
                        if not isinstance(reply, dict) or reply.get("ok") is not True or not isinstance(confirmed, dict) or str(confirmed.get("id") or confirmed.get("timer_id")) != timer_id:
                            return self._failure("The satellite did not confirm the timer update. Its outcome is unknown; check the timer before retrying.")
                        row = self._public_timer(confirmed)
                        paused.pop(timer_id, None)
                changed.append(row)
                # Persist each confirmed change, including progress through a
                # cancel-all request if a later satellite acknowledgement fails.
                await self.manager.async_save()
            verb = {"pause": "Paused", "resume": "Resumed", "increase": "Added time to", "decrease": "Removed time from", "cancel": "Cancelled"}[action]
            return {"ok": True, "data": {"timers": changed}, "summary_for_user": f"{verb} {len(changed)} timer(s) on {runtime.name}."}
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            return self._failure("The satellite did not confirm the timer change. Check its timers before retrying.", code="timer_timeout")
        except Exception as err:
            return self._failure(f"The timer change could not be confirmed: {err}")

    def _timer_status(self, timer: dict[str, Any]) -> str:
        label = timer["name"] + " timer" if timer["name"] else self._format_remaining(timer["original_duration_s"]) + " timer"
        return (
            f"The {label} is paused with {self._format_remaining(timer['remaining_s'])} left"
            if timer["state"] == "paused"
            else f"The {label} is ringing"
            if timer["state"] == "ringing"
            else f"The {label} has {self._format_remaining(timer['remaining_s'])} left"
        )

    # Natural-language parsing ported from the Timer Verba.

    def _parse_integer_word_tokens(self, tokens: list[str]) -> int | None:
        """
        Parse integer-like number words (supports up to thousands).
        Examples:
          - ["two"] -> 2
          - ["twenty", "five"] -> 25
          - ["one", "hundred", "ten"] -> 110
        """
        if not tokens:
            return None

        units = {
            "zero": 0,
            "one": 1, "a": 1, "an": 1,
            "two": 2, "couple": 2,
            "three": 3, "few": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12, "dozen": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
        }
        tens = {
            "twenty": 20,
            "thirty": 30,
            "forty": 40,
            "fifty": 50,
            "sixty": 60,
            "seventy": 70,
            "eighty": 80,
            "ninety": 90,
        }

        total = 0
        current = 0
        seen = False
        for tok in tokens:
            t = str(tok or "").strip().lower()
            if not t:
                continue
            if t in {"and", "of"}:
                continue
            if re.fullmatch(r"\d+", t):
                current += int(t)
                seen = True
                continue
            if t in units:
                current += units[t]
                seen = True
                continue
            if t in tens:
                current += tens[t]
                seen = True
                continue
            if t == "hundred":
                current = (current or 1) * 100
                seen = True
                continue
            if t == "thousand":
                total += (current or 1) * 1000
                current = 0
                seen = True
                continue
            return None

        if not seen:
            return None
        return total + current

    def _parse_amount_phrase(self, phrase: str) -> float | None:
        """
        Parse quantity phrases used before duration units.
        Handles numerals and common spoken forms:
          - "2", "2.5", "two", "twenty five"
          - "half", "quarter", "three quarters"
          - "one and a half", "two and a quarter"
        """
        text = str(phrase or "").strip().lower()
        if not text:
            return None

        text = text.replace("-", " ")
        text = re.sub(r"[^a-z0-9.\s]", " ", text)
        # In "a five minute timer", the article belongs to timer, not to
        # the number. Counting it as one would turn five minutes into six.
        text = re.sub(
            r"\b(?:a|an)\s+(?=(?:\d|zero\b|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b|eleven\b|twelve\b|thirteen\b|fourteen\b|fifteen\b|sixteen\b|seventeen\b|eighteen\b|nineteen\b|twenty\b|thirty\b|forty\b|fifty\b|sixty\b|seventy\b|eighty\b|ninety\b))",
            "",
            text,
        )
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None

        def parse_fractional(raw: str) -> float | None:
            s = str(raw or "").strip()
            if not s:
                return None
            if re.fullmatch(r"\d+(?:\.\d+)?", s):
                try:
                    return float(s)
                except Exception:
                    return None

            direct = {
                "half": 0.5,
                "a half": 0.5,
                "one half": 0.5,
                "quarter": 0.25,
                "a quarter": 0.25,
                "one quarter": 0.25,
                "three quarters": 0.75,
                "three quarter": 0.75,
            }
            if s in direct:
                return direct[s]

            patterns = [
                (r"^(.+?)\s+and\s+a\s+half$", 0.5),
                (r"^(.+?)\s+and\s+half$", 0.5),
                (r"^(.+?)\s+and\s+a\s+quarter$", 0.25),
                (r"^(.+?)\s+and\s+quarter$", 0.25),
                (r"^(.+?)\s+and\s+three\s+quarters?$", 0.75),
            ]
            for pat, frac in patterns:
                m = re.match(pat, s)
                if not m:
                    continue
                base = m.group(1).strip()
                base_int = self._parse_integer_word_tokens(base.split())
                if base_int is not None:
                    return float(base_int) + frac
                try:
                    return float(base) + frac
                except Exception:
                    continue

            int_val = self._parse_integer_word_tokens(s.split())
            if int_val is not None:
                return float(int_val)
            return None

        tokens = text.split()
        for i in range(len(tokens)):
            suffix = " ".join(tokens[i:]).strip()
            val = parse_fractional(suffix)
            if val is not None:
                return val

        return parse_fractional(text)

    def _duration_components_from_text(self, text: str) -> list[tuple[float, int]]:
        """
        Extract duration components from free text as (amount, unit_seconds).
        """
        src = str(text or "").strip().lower()
        if not src:
            return []

        src = src.replace("-", " ")
        src = re.sub(r"\b(half|quarter)\s+(?:an?|one)\s+(hours?|minutes?|seconds?)\b", r"\1 \2", src)
        src = re.sub(
            r"\b(an?|one)\s+(hours?|minutes?|seconds?)\s+and\s+(?:a\s+)?(half|quarter)\b",
            r"one and a \3 \2",
            src,
        )
        src = re.sub(r"\s+", " ", src).strip()

        unit_seconds = {
            "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
            "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
            "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        }
        pattern = re.compile(r"(?<![a-z])(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)(?![a-z])")

        parts: list[tuple[float, int]] = []
        previous_end = 0
        for m in pattern.finditer(src):
            amount_raw = src[previous_end:m.start()].strip()
            unit_raw = m.group(1).lower()
            previous_end = m.end()
            amt = self._parse_amount_phrase(amount_raw)
            if amt is None or amt <= 0:
                continue
            mult = unit_seconds.get(unit_raw)
            if not mult:
                continue
            parts.append((amt, mult))

        return parts

    @staticmethod
    def _merged_request_text(args: dict[str, Any]) -> str:
        a = args if isinstance(args, dict) else {}
        text_fields = (
            a.get("request"),
            a.get("query"),
            a.get("message"),
            a.get("prompt"),
            a.get("text"),
            a.get("content"),
            a.get("duration"),
        )
        merged = " ".join(str(v or "").strip() for v in text_fields if str(v or "").strip()).strip().lower()
        return re.sub(r"\s+", " ", merged).strip()

    def _parse_duration_to_seconds(self, text: str, max_seconds: int) -> int:
        t = (text or "").strip().lower()
        if not t:
            return 0
        if re.search(r"(?<!\w)-\s*\d|\b(?:negative|minus)\s+", t):
            return 0

        t = re.sub(r"[,;]+", " ", t)
        t = re.sub(r"[()]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()

        if re.fullmatch(r"\d+", t):
            return max(0, min(int(t), max_seconds))

        if re.fullmatch(r"\d{1,2}:\d{2}", t):
            mm, ss = t.split(":")
            total = int(mm) * 60 + int(ss)
            return max(0, min(total, max_seconds))

        t_spaced = re.sub(r"(\d)([a-z])", r"\1 \2", t)
        t_spaced = re.sub(r"([a-z])(\d)", r"\1 \2", t_spaced)
        t_spaced = re.sub(r"\s+", " ", t_spaced).strip()

        total = 0.0
        for amount, mult in self._duration_components_from_text(t_spaced):
            total += float(amount) * int(mult)

        if total > 0:
            return max(0, min(int(round(total)), max_seconds))

        # If we got only a plain number token, interpret as seconds.
        if re.fullmatch(r"\d+(?:\.\d+)?", t_spaced):
            try:
                return max(0, min(int(round(float(t_spaced))), max_seconds))
            except Exception:
                return 0

        return 0

    def _format_remaining(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds} seconds"
        m = seconds // 60
        s = seconds % 60
        if s == 0:
            return f"{m} minute" + ("s" if m != 1 else "")
        return f"{m}m {s}s"

    def _extract_duration_from_text(self, text: str) -> str:
        src = str(text or "").strip().lower()
        if not src:
            return ""

        hhmm = re.search(r"\b(\d{1,2}:\d{2})\b", src)
        if hhmm:
            return hhmm.group(1)

        if self._duration_components_from_text(src):
            return src

        if "timer" in src:
            n_for = re.search(r"\bfor\s+(\d{1,4})\b", src)
            if n_for:
                return f"{n_for.group(1)} minutes"
            n_plain = re.search(r"\b(\d{1,4})\b", src)
            if n_plain:
                return f"{n_plain.group(1)} minutes"
        return ""

    @staticmethod
    def _clean_timer_name(value: str) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
        text = re.sub(
            r"\b\d+(?:\.\d+)?\s*(?:hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b",
            " ",
            text,
        )
        text = re.sub(r"[^a-z0-9'\- ]+", " ", text)
        number_words = (
            "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
            "thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|half|quarter|a|an"
        )
        text = re.sub(
            rf"\b(?:{number_words})(?:[\s-]+(?:and\s+)?(?:{number_words}))*\s+"
            r"(?:hours?|hrs?|minutes?|mins?|seconds?|secs?)\b",
            " ",
            text,
        )
        text = re.sub(r"\b(?:a|an|the|my|me|called|named|for|please)\b", " ", text)
        text = re.sub(r"\b(?:timer|timers)\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" -")
        return text[:63]

    def _extract_timer_name(self, args: dict[str, Any], action: str = "") -> str:
        body = args if isinstance(args, dict) else {}
        explicit = str(body.get("name") or body.get("label") or body.get("timer_name") or "").strip()
        if explicit:
            return self._clean_timer_name(explicit)

        text = self._merged_request_text(body)
        if not text:
            return ""
        patterns = [
            r"\b(?:called|named)\s+(.+?)(?:\s+for\b|$)",
            r"\b(?:set|start|create)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?(.+?)\s+timer\b",
            r"\b(?:cancel|stop|clear|end|silence|dismiss|snooze|check|show)\s+(?:the\s+|my\s+|a\s+)?(.+?)\s+timers?\b",
            r"\b(?:on|for)\s+(?:the\s+|my\s+)?(.+?)\s+timer\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            candidate = self._clean_timer_name(match.group(1))
            if candidate and candidate not in {"all", "every", "running", "active"}:
                return candidate
        return ""

    def _resolve_action_duration(self, args: dict[str, Any]) -> tuple[str, str]:
        a = args if isinstance(args, dict) else {}
        action = str(a.get("action") or "").strip().lower()
        duration = str(a.get("duration") or "").strip()
        if duration:
            return action, duration

        merged = self._merged_request_text(a)
        if not merged:
            return action, ""

        if not action:
            if re.search(r"\b(unpause|resume)\b", merged):
                action = "resume"
            elif re.search(r"\bpause\b", merged):
                action = "pause"
            elif re.search(r"\b(add|increase|extend)\b", merged):
                action = "increase"
            elif re.search(r"\b(remove|decrease|subtract|shorten)\b", merged):
                action = "decrease"
            elif re.search(r"\bsnooze\b", merged):
                action = "snooze"
            elif re.search(r"\b(cancel|stop|clear|end|silence|dismiss)\b", merged):
                action = "cancel"
            elif re.search(r"\b(status|remaining|left|how much time|how long|time left|check|list|show)\b", merged):
                action = "status"
            elif re.search(r"\b(start|set|create)\b", merged) and "timer" in merged:
                action = "start"
            elif re.search(r"\b(?:what|which|any)\b.*\btimers?\b", merged):
                action = "status"

        inferred_duration = self._extract_duration_from_text(merged)
        if inferred_duration:
            duration = inferred_duration
        return action, duration
