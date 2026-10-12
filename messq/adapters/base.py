"""Scanner adapter interface.

Everything that produces scan events (the simulator now; a COSEC API poller
or a CSV-export poller later) implements this, so the engine never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..events import ScanEvent


class ScannerAdapter(ABC):
    @abstractmethod
    def poll(self) -> list[ScanEvent]:
        """Return events seen since the previous poll (duplicates are allowed;
        the engine drops repeated event_ids)."""

    def close(self) -> None:  # noqa: B027 - optional hook
        pass
