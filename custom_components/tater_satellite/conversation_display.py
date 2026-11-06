"""Live conversation display state for Tater Echo screens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ConversationDisplayState:
    """Build complete, ordered display snapshots from Assist pipeline events."""

    device_id: str
    turn_number: int = 0
    turn_id: str = ""
    phase: str = "listening"
    user_text: str = ""
    user_final: bool = False
    assistant_text: str = ""
    assistant_final: bool = False
    revision: int = 0

    def _start_turn(self) -> dict[str, Any]:
        self.turn_number += 1
        self.turn_id = f"{self.device_id}:{self.turn_number}"
        self.phase = "listening"
        self.user_text = ""
        self.user_final = False
        self.assistant_text = ""
        self.assistant_final = False
        self.revision = 0
        return self._update(force=True)

    def _snapshot(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "phase": self.phase,
            "user_text": self.user_text,
            "user_final": self.user_final,
            "assistant_text": self.assistant_text,
            "assistant_final": self.assistant_final,
            "revision": self.revision,
        }

    def _update(
        self,
        *,
        phase: str | None = None,
        user_text: str | None = None,
        user_final: bool | None = None,
        assistant_text: str | None = None,
        assistant_final: bool | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        before = (
            self.phase,
            self.user_text,
            self.user_final,
            self.assistant_text,
            self.assistant_final,
        )
        if phase is not None:
            self.phase = phase
        if user_text is not None:
            self.user_text = str(user_text or "").strip()
        if user_final is not None:
            self.user_final = bool(user_final)
        if assistant_text is not None:
            self.assistant_text = str(assistant_text or "").strip()
        if assistant_final is not None:
            self.assistant_final = bool(assistant_final)
        after = (
            self.phase,
            self.user_text,
            self.user_final,
            self.assistant_text,
            self.assistant_final,
        )
        if not force and before == after:
            return None
        self.revision += 1
        return self._snapshot()

    def pipeline_event(
        self, event_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Return a display snapshot for a relevant Assist pipeline event."""
        if event_name == "RUN_START":
            return self._start_turn()
        if event_name == "STT_START" and not self.turn_id:
            return self._start_turn()
        if not self.turn_id:
            return None
        if event_name == "STT_END":
            return self._update(
                phase="thinking",
                user_text=str(data.get("text") or ""),
                user_final=True,
            )
        if event_name in {"INTENT_START", "INTENT_PROGRESS"}:
            return self._update(phase="thinking")
        if event_name == "INTENT_END":
            speech = str(data.get("speech") or "").strip()
            if speech:
                return self._update(
                    phase="replying",
                    assistant_text=speech,
                    assistant_final=True,
                )
            return None
        if event_name == "TTS_START":
            speech = str(data.get("text") or "").strip()
            return self._update(
                phase="replying",
                assistant_text=speech if speech else None,
                assistant_final=True if speech else None,
            )
        return None
