from __future__ import annotations

import copy
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_tater_assistant import tater, _Manager


class ScheduledActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = _Manager()
        self.manager.hass.config = SimpleNamespace(time_zone="America/Chicago")
        self.runtime = tater.MiniTaterRuntime(self.manager)
        self.runtime.setup()
        self.tool = self.runtime.scheduler
        self.rows = [
            tater.HomeEntity("light.desk", "Desk", "light", "on", "Office", (), {}),
            tater.HomeEntity("light.ceiling", "Ceiling", "light", "on", "Office", (), {}),
        ]
        self.runtime.home.entities = lambda **kwargs: self.rows
        self.runtime.home._allowed = lambda entity_id: any(row.entity_id == entity_id for row in self.rows)
        self.runtime.home._vacuum_area_arguments = lambda query: None
        self.runtime._device_llm_json = AsyncMock(return_value={"action": "schedule", "request": "turn off the office lights", "delay_seconds": 300})
        self.track = Mock(side_effect=lambda hass, callback, when: self._track(callback, when))
        self.callbacks = {}
        self.event_patch = patch.dict(sys.modules, {"homeassistant.helpers.event": SimpleNamespace(async_track_point_in_utc_time=self.track)})
        self.event_patch.start()
        self.addCleanup(self.event_patch.stop)
        self.addCleanup(self.tool.shutdown)

    def _track(self, callback, when):
        cancel = Mock()
        self.callbacks[len(self.callbacks)] = (callback, when, cancel)
        return cancel

    async def call(self, query="turn off the office lights in five minutes"):
        return await self.tool.async_call({"query": query}, None)

    async def test_future_action_is_frozen_and_not_executed_early(self):
        execute = self.runtime.home.async_call = AsyncMock(return_value={"ok": True, "summary_for_user": "Turned off office lights."})
        result = await self.call()
        self.assertTrue(result["ok"], result)
        execute.assert_not_awaited()
        job = self.tool.jobs()[0]
        self.assertEqual(job["arguments"]["entity_ids"], ["light.desk", "light.ceiling"])
        self.rows.append(tater.HomeEntity("light.new", "New", "light", "on", "Office", (), {}))
        callback, _, _ = self.callbacks[0]
        await callback(None)
        self.assertEqual(execute.await_args.args[0]["entity_ids"], ["light.desk", "light.ceiling"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(self.manager.data["tater_hydra_ledger"][-1]["outcome"], "done")

    async def test_scope_change_fails_without_executing_any_target(self):
        await self.call()
        self.rows.pop()
        execute = self.runtime.home.async_call = AsyncMock()
        await self.callbacks[0][0](None)
        execute.assert_not_awaited()
        self.assertEqual(self.tool.jobs()[0]["status"], "failed")

    async def test_restores_pending_jobs_but_never_repeats_running_or_completed_actions(self):
        await self.call()
        pending = copy.deepcopy(self.tool.jobs()[0])
        running = {**copy.deepcopy(pending), "id": "running", "status": "running"}
        self.tool.shutdown()
        self.manager.data["tater_scheduled_actions"] = [pending, running]
        before = self.track.call_count
        self.tool.setup()
        self.assertEqual(self.track.call_count, before + 1)
        self.assertIn(pending["id"], self.tool.handles)
        self.assertNotIn("running", self.tool.handles)

    async def test_overdue_job_is_missed_instead_of_replayed(self):
        await self.call()
        self.tool.jobs()[0]["due"] = time.time() - 120
        execute = self.runtime.home.async_call = AsyncMock()
        await self.callbacks[0][0](None)
        execute.assert_not_awaited()
        self.assertEqual(self.tool.jobs()[0]["status"], "missed")

    async def test_cancellation_is_durable_and_save_failure_leaves_job_pending(self):
        await self.call()
        job = self.tool.jobs()[0]
        self.runtime._device_llm_json.return_value = {"action": "cancel", "id": job["id"]}
        self.manager.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
        result = await self.call("cancel the scheduled lights")
        self.assertFalse(result["ok"])
        self.assertEqual(job["status"], "pending")
        self.callbacks[0][2].assert_not_called()
        self.manager.async_save = AsyncMock()
        result = await self.call("cancel the scheduled lights")
        self.assertTrue(result["ok"], result)
        self.callbacks[0][2].assert_called_once()
        await self.callbacks[0][0](None)
        self.assertEqual(job["status"], "cancelled")

    async def test_failed_persistence_does_not_leave_an_armed_action(self):
        self.manager.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
        result = await self.call()
        self.assertFalse(result["ok"])
        self.assertEqual(self.tool.jobs(), [])
        self.assertEqual(self.tool.handles, {})
        self.callbacks[0][2].assert_called_once()

    async def test_invalid_or_ambiguous_action_is_never_scheduled(self):
        for parsed in [
            {"request": "turn off the office lights", "delay_seconds": -2},
            {"request": "turn off the office lights", "at": "2027-01-01T15:00:00"},
            {"request": "turn off the lights", "delay_seconds": 60},
        ]:
            self.runtime._device_llm_json.return_value = {"action": "schedule", **parsed}
            self.assertFalse((await self.call())["ok"])
        self.assertEqual(self.tool.jobs(), [])
        self.track.assert_not_called()


if __name__ == "__main__":
    unittest.main()
