from __future__ import annotations

from ..events import ScanEvent
from .base import ScannerAdapter


class SimulatedScanner(ScannerAdapter):
    """Receives fake scans from the simulator and hands them out on poll()."""

    def __init__(self) -> None:
        self._buffer: list[ScanEvent] = []

    def emit(self, event: ScanEvent) -> None:
        self._buffer.append(event)

    def poll(self) -> list[ScanEvent]:
        out, self._buffer = self._buffer, []
        return out
