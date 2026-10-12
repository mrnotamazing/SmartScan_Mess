"""The only data the system ever handles.

A scan event is (pseudonymised student key, mess id, timestamp). No face
images, templates or other biometric data exist anywhere in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class ScanEvent:
    ts: float  # seconds (unix epoch for real scanners, simulation clock otherwise)
    mess_id: str
    student_key: str  # pseudonymised ID, see messq.privacy; never the raw roll number
    event_id: str | None = None  # device-side id, used to drop duplicates when polling


class FoodState(str, Enum):
    OK = "ok"
    LOW = "low"  # kitchen tapped "tray low"
    OUT = "out"  # kitchen tapped "out"; cleared by "refilled" (-> OK)


@dataclass(frozen=True, slots=True)
class FoodSignal:
    ts: float
    mess_id: str
    state: FoodState
    item: str | None = None  # a tray such as "Rice"; None = the main tray (or, for OK, all trays)
