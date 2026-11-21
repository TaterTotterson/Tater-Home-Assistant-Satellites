"""Persist delayed Mini-Tater actions with their original, resolved targets."""

from __future__ import annotations

from datetime import datetime, timezone
import secrets
import time

from .ha_tools import failure, tool_definition

SCHEDULE_TOOL_ID = "schedule_home"
SCHEDULE_DESCRIPTION = (
    "Schedule a Home Assistant device action for a later time, or list/cancel pending actions. "
    "Use for requests such as turn off the kitchen lights in five minutes. "
    "A countdown timer does not schedule a device action. Never execute a delayed action immediately."
)


class ScheduledActionsTool:
    name = SCHEDULE_TOOL_ID

    def __init__(self, runtime):
        self.runtime = runtime
        self.handles = {}

    def definition(self):
        return tool_definition(self.name, SCHEDULE_DESCRIPTION)

    def jobs(self):
        return self.runtime.manager.data.setdefault("tater_scheduled_actions", [])

    def setup(self):
        for job in self.jobs():
            if job.get("status") == "pending":
                self._arm(job)

    def _trim_history(self):
        jobs = self.jobs()
        finished = [job for job in jobs if job.get("status") not in {"pending", "running"}]
        keep = {id(job) for job in finished[-100:]}
        jobs[:] = [job for job in jobs if job.get("status") in {"pending", "running"} or id(job) in keep]

    def shutdown(self):
        for cancel in self.handles.values():
            cancel()
        self.handles.clear()

    def _arm(self, job):
        from homeassistant.helpers.event import async_track_point_in_utc_time

        async def due(_now):
            self.handles.pop(job["id"], None)
            if job.get("status") != "pending":
                return
            # Don't replay an old action after HA was offline for a long time.
            if time.time() - job["due"] > 60:
                job.update(status="missed", error="Home Assistant was offline at the scheduled time.")
            else:
                job["status"] = "running"
                # Persist before dispatch: a restart must never repeat a toggle
                # or another action whose first outcome was not recorded.
                await self.runtime.manager.async_save()
                allowed = {row.entity_id for row in self.runtime.home.entities()}
                if not set(job["arguments"]["entity_ids"]).issubset(allowed):
                    result = failure("A scheduled target is unavailable or no longer in the selected Assist scope.")
                else:
                    try:
                        result = await self.runtime.home.async_call(job["arguments"], None)
                    except Exception as err:
                        result = failure(str(err) or "The scheduled device action failed.")
                job.update(status="completed" if result.get("ok") else "failed", result=result)
            ledger = self.runtime.manager.data.setdefault("tater_hydra_ledger", [])
            ledger.append({
                "id": secrets.token_hex(8), "time": time.time(), "request": job["request"],
                "outcome": "done" if job["status"] == "completed" else "failed",
                "response": job.get("result", {}).get("summary_for_user") or job.get("result", {}).get("error") or job.get("error", ""),
                "tools": [{"name": self.name, "result": job.get("result", {}), "approved": job["status"] == "completed"}],
            })
            limit = self.runtime.settings().get("hydra_max_ledger_items", 1500)
            del ledger[:-limit]
            self._trim_history()
            await self.runtime.manager.async_save()

        self.handles[job["id"]] = async_track_point_in_utc_time(
            self.runtime.hass, due, datetime.fromtimestamp(job["due"], timezone.utc)
        )

    async def async_call(self, arguments, context, *, request="", device_id=""):
        del context
        query = str(arguments.get("query") or request or "").strip()[:2000]
        try:
            pending = [row for row in self.jobs() if row.get("status") == "pending"]
            parsed = await self.runtime._device_llm_json(
                "Interpret a delayed HA device action. Return JSON with action (schedule/list/cancel), "
                "request (the complete device command WITHOUT its delay), delay_seconds (positive number or null), "
                "at (ISO datetime with timezone for an absolute time, otherwise empty), and id (a pending job ID for cancel). "
                "Use the supplied live HA clock for relative dates. Never omit the device command, invent a target, "
                "choose a new action, or convert a request for later into an immediate action. "
                "For cancellation choose only a job matching the user's request; use an empty id if ambiguous.",
                {"query": query, "current_local_datetime": self.runtime._current_datetime_context_message(),
                 "voice_context": self.runtime._voice_context(device_id), "pending": pending},
            )
            action = parsed.get("action")
            if action == "list":
                return {"ok": True, "pending": [{"id": row["id"], "request": row["request"], "at": row["at"]} for row in pending]}
            if action == "cancel":
                matches = [row for row in pending if row["id"] == parsed.get("id")]
                if len(matches) != 1:
                    return failure("Which scheduled action should I cancel?")
                job = matches[0]
                job["status"] = "cancelled"
                # Make cancellation durable before removing the callback. If
                # saving fails, leave the original pending action intact.
                try:
                    await self.runtime.manager.async_save()
                except Exception:
                    job["status"] = "pending"
                    raise
                cancel = self.handles.pop(job["id"], None)
                if cancel:
                    cancel()
                self._trim_history()
                return {"ok": True, "summary_for_user": f"Cancelled the scheduled action: {job['request']}."}
            if action != "schedule":
                return failure("What device action should I schedule, and when?")
            if len(pending) >= 50:
                return failure("There are already 50 pending actions. Cancel one before scheduling another.")
            now = time.time()
            delay = parsed.get("delay_seconds")
            if parsed.get("at"):
                when = datetime.fromisoformat(str(parsed["at"]))
                if when.tzinfo is None:
                    return failure("The scheduled time needs a timezone.")
                due = when.timestamp()
            elif isinstance(delay, (int, float)) and not isinstance(delay, bool):
                due = now + delay
            else:
                return failure("When should I run that action?")
            if not 1 <= due - now <= 7 * 86400:
                return failure("Choose a future time within the next seven days.")
            command = str(parsed.get("request") or "").strip()[:2000]
            home = self.runtime.home
            prepared = home._vacuum_area_arguments(command) or home._natural_arguments(command)
            prepared = await home._complete_natural_arguments(command, prepared)
            if prepared.get("operation") != "control" or not prepared.get("command"):
                return failure("That request is not a supported device action.")
            if not prepared.get("query") and not prepared.get("entity_ids"):
                return failure("Which room, floor, or device should I schedule that action for?")
            rows = home.resolve(prepared, request="" if prepared.get("command") == "clean_vacuum_area" else command)
            rows = [row for row in rows if home._supports_command(row, prepared["command"])]
            if not rows:
                return failure("No allowed device matched the scheduled action.")
            from .tater_assistant import _COMMANDS, _GENERIC_COMMAND_DOMAINS, _clean_control_target

            spec = _COMMANDS.get(prepared["command"])
            if spec is None:
                return failure("That device action cannot be scheduled.")
            domain = spec[0]
            if domain:
                rows = [row for row in rows if row.domain == domain]
            elif prepared["command"] in _GENERIC_COMMAND_DOMAINS:
                rows = [row for row in rows if row.domain in _GENERIC_COMMAND_DOMAINS[prepared["command"]]]
            else:
                return failure("That device action cannot be scheduled.")
            if not rows:
                return failure("The matched devices do not support that action.")
            target = _clean_control_target(prepared.get("query"))
            if len(rows) > 1 and target and not all(
                target in {_clean_control_target(row.area), _clean_control_target(row.floor)}
                for row in rows
            ):
                return failure("More than one device matched. Name a room, floor, or exact device.")
            frozen = {
                "operation": "control", "command": prepared["command"], "query": "all",
                "entity_ids": [row.entity_id for row in rows],
                "parameters": prepared.get("parameters") or {},
            }
            job = {
                "id": secrets.token_hex(8), "request": command, "due": due,
                "at": datetime.fromtimestamp(due, timezone.utc).isoformat(),
                "arguments": frozen, "status": "pending",
            }
            self.jobs().append(job)
            try:
                self._arm(job)
                await self.runtime.manager.async_save()
            except Exception:
                cancel = self.handles.pop(job["id"], None)
                if cancel:
                    cancel()
                self.jobs().remove(job)
                raise
            return {
                "ok": True, "id": job["id"], "at": job["at"],
                "summary_for_user": f"Scheduled {command} for {job['at']}. The device action has not run yet.",
                "say_hint": "Confirm the scheduled time in the user's HA timezone. Do not say the device has already changed.",
            }
        except Exception as err:
            return failure(str(err) or "The action could not be scheduled.")
