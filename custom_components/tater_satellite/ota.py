"""OTA lifecycle tracking shared by Home Assistant entities and the panel."""

from __future__ import annotations

import time
from dataclasses import dataclass
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

    def begin(
        self,
        expected_version: Any,
        connection_generation: int,
        *,
        now: float | None = None,
    ) -> int:
        """Start a new OTA attempt and return its generation token."""
        started_at = time.time() if now is None else now
        self.attempt += 1
        self.in_progress = True
        self.progress = 0
        self.message = "OTA command sent"
        self.expected_version = _text(expected_version)
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
            self.progress = max(0, min(99, int(raw_progress)))
        message = _text(payload.get("message"))
        if status in _FAILED_STATUSES:
            self.fail(message or status)
            return
        if status in _REBOOT_STATUSES:
            self.reboot_requested = True
            self.message = (
                "Firmware downloaded. Waiting for the satellite to reconnect "
                "on the new version."
            )
            return
        if message or status:
            self.message = message or status

    def note_disconnect(self) -> None:
        """Remember the expected transport loss during the OTA reboot."""
        if not self.in_progress:
            return
        self.disconnect_seen = True
        self.message = (
            "Firmware downloaded. Waiting for the satellite to reconnect "
            "on the new version."
        )

    def note_reconnect(self, connection_generation: int, actual_version: Any) -> None:
        """Verify the first post-command connection against the release version."""
        if (
            not self.in_progress
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
