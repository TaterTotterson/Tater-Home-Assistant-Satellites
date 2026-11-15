"""OTA lifecycle tracking shared by Home Assistant entities and the panel."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


OTA_VERIFY_TIMEOUT_SECONDS = 5 * 60.0
_FAILED_STATUSES = {"error", "failed"}
_REBOOT_STATUSES = {"rebooting", "done", "complete", "completed", "success"}


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class OtaState:
    """Track one satellite OTA attempt through its reboot and reconnect."""

    in_progress: bool = False
    progress: int | None = None
    message: str = ""
    expected_version: str = ""
    initial_connection_generation: int = 0
    disconnect_seen: bool = False
    reboot_requested: bool = False
    deadline: float = 0.0
    attempt: int = 0
    stage: str = "final"
    stage_count: int = 1
    required_capability: str = ""
    minimum_capability_version: int = 0
    final_command: dict[str, Any] = field(default_factory=dict)
    expected_system_version: str = ""

    def begin(
        self,
        expected_version: Any,
        connection_generation: int,
        *,
        stage: str = "final",
        required_capability: Any = "",
        minimum_capability_version: int = 0,
        final_command: dict[str, Any] | None = None,
        expected_system_version: str = "",
        now: float | None = None,
    ) -> int:
        """Start a new OTA attempt and return its generation token."""
        started_at = time.time() if now is None else now
        self.attempt += 1
        self.in_progress = True
        self.stage = stage if stage in {'bridge', 'system'} else 'final'
        self.stage_count = 2 if self.stage in {'bridge', 'system'} else 1
        self.progress = 0
        self.message = (
            "OTA compatibility bridge command sent (stage 1 of 2)"
            if self.stage == "bridge"
            else "System OTA command sent (stage 1 of 2)" if self.stage == 'system'
            else "OTA command sent"
        )
        self.expected_version = _text(expected_version)
        self.initial_connection_generation = max(0, int(connection_generation))
        self.disconnect_seen = False
        self.reboot_requested = False
        self.deadline = started_at + OTA_VERIFY_TIMEOUT_SECONDS
        self.required_capability = _text(required_capability)
        self.minimum_capability_version = max(
            0, int(minimum_capability_version or 0)
        )
        self.final_command = dict(final_command or {})
        self.expected_system_version = _text(expected_system_version)
        return self.attempt

    def system_reconnect_ready(self, connection_generation: int, capabilities: dict[str, Any]) -> bool:
        if (not self.in_progress or self.stage != 'system'
                or connection_generation <= self.initial_connection_generation):
            return False
        if (not self.expected_system_version or
                _text(capabilities.get('system_version')) != self.expected_system_version):
            self.fail('System OTA did not boot the expected Linux version; the final app update was not sent.')
            return False
        return True

    @staticmethod
    def _capability_version(capabilities: dict[str, Any], name: str) -> int:
        value = capabilities.get(name)
        if isinstance(value, bool):
            return 1 if value else 0
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def bridge_reconnect_ready(
        self,
        connection_generation: int,
        capabilities: dict[str, Any],
    ) -> bool:
        """Validate the bridge reboot before the final OTA is sent."""
        if (
            not self.in_progress
            or self.stage != "bridge"
            or int(connection_generation) <= self.initial_connection_generation
        ):
            return False
        current = self._capability_version(
            capabilities, self.required_capability
        )
        if current < self.minimum_capability_version:
            self.fail(
                "The OTA bridge restarted without "
                f"{self.required_capability} version "
                f"{self.minimum_capability_version}; the final OTA was not sent."
            )
            return False
        return True

    def begin_final(
        self,
        connection_generation: int,
        *,
        now: float | None = None,
    ) -> int:
        """Advance a verified two-stage migration to its final OTA."""
        started_at = time.time() if now is None else now
        self.attempt += 1
        self.stage = "final"
        self.progress = 50
        self.message = "OTA platform verified; final firmware command sent (stage 2 of 2)"
        self.initial_connection_generation = max(0, int(connection_generation))
        self.disconnect_seen = False
        self.reboot_requested = False
        self.deadline = started_at + OTA_VERIFY_TIMEOUT_SECONDS
        return self.attempt

    def fail(self, message: Any) -> None:
        """Finish the attempt with an actionable error."""
        self.in_progress = False
        self.message = _text(message) or "Native OTA failed."

    def complete(self, actual_version: Any) -> None:
        """Finish the attempt after the new firmware reports its version."""
        version = _text(actual_version) or self.expected_version
        self.in_progress = False
        self.progress = 100
        self.message = (
            f"OTA verified after reboot. The satellite is running {version}."
            if version
            else "OTA verified after reboot."
        )

    def apply_status(self, payload: dict[str, Any]) -> None:
        """Apply a progress report without trusting pre-reboot 100%."""
        if not self.in_progress:
            return
        status = _text(payload.get("status")).lower()
        raw_progress = payload.get("progress")
        if isinstance(raw_progress, (int, float)):
            progress = max(0, min(100, int(raw_progress)))
            if self.stage_count == 2:
                self.progress = (
                    min(49, int(progress * 0.49))
                    if self.stage in {'bridge', 'system'}
                    else min(99, 50 + int(progress * 0.49))
                )
            else:
                self.progress = min(99, progress)
        message = _text(payload.get("message"))
        if status in _FAILED_STATUSES:
            self.fail(message or status)
            return
        if status in _REBOOT_STATUSES:
            self.reboot_requested = True
            self.message = self._reconnect_message()
            return
        if message or status:
            self.message = message or status

    def note_disconnect(self) -> None:
        """Remember the expected transport loss during the OTA reboot."""
        if not self.in_progress:
            return
        self.disconnect_seen = True
        self.message = self._reconnect_message()

    def _reconnect_message(self) -> str:
        if self.stage == 'system':
            return 'System OTA staged. Waiting for the expected Linux version before the final app update.'
        if self.stage == "bridge":
            return (
                "OTA bridge installed. Waiting for the satellite to reconnect "
                "before stage 2 of 2."
            )
        return (
            "Firmware downloaded. Waiting for the satellite to reconnect "
            "on the new version."
        )

    def note_reconnect(self, connection_generation: int, actual_version: Any) -> None:
        """Verify the first post-command connection against the release version."""
        if (
            not self.in_progress
            or self.stage in {'bridge', 'system'}
            or int(connection_generation) <= self.initial_connection_generation
        ):
            return
        actual = _text(actual_version)
        if self.expected_version and actual == self.expected_version:
            self.complete(actual)
            return
        if actual:
            self.fail(
                f"The satellite reconnected on {actual}, but Home Assistant "
                f"expected {self.expected_version or 'the new firmware'}. The "
                "update may have rolled back or been interrupted."
            )

    def expire(self, attempt: int, *, now: float | None = None) -> bool:
        """Fail an unchanged OTA attempt once reconnect verification times out."""
        current_time = time.time() if now is None else now
        if (
            not self.in_progress
            or attempt != self.attempt
            or current_time < self.deadline
        ):
            return False
        self.fail(
            "Timed out waiting for the satellite to reboot and report the "
            "expected firmware version."
        )
        return True
