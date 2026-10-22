"""Today's dishes for each food tray, from config/menu.toml.

The trays are fixed categories (gravy sabji, rice, roti, ...) so the system's
logic does not change with the menu; the menu only names what is in each tray.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "menu.toml"


@dataclass(frozen=True)
class DayMenu:
    day: str = ""
    theme: str = ""
    dishes: dict[str, str] = field(default_factory=dict)  # tray -> dish

    def dish(self, tray: str) -> str | None:
        return self.dishes.get(tray)

    def served(self, tray: str) -> bool:
        """A tray missing from the day's menu isn't served; with no menu, show every tray."""
        return not self.dishes or tray in self.dishes


def load_menu(day: str | None = None, meal: str = "lunch", path: str | Path | None = None) -> DayMenu:
    day = (day or DAYS[dt.date.today().weekday()]).lower()
    if day not in DAYS:
        raise ValueError(f"unknown day {day!r}; use one of {', '.join(DAYS)}")
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return DayMenu(day)
    entry = dict(tomllib.loads(p.read_text(encoding="utf-8")).get(meal, {}).get(day, {}))
    theme = str(entry.pop("theme", ""))
    return DayMenu(day, theme, {str(k): str(v) for k, v in entry.items()})
