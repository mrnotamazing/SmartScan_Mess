"""Configuration loading.

All tunable numbers live in a TOML file (default: config/default.toml, or the
path in the MESSQ_CONFIG environment variable). Secrets never live in the file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "default.toml"


@dataclass(frozen=True)
class MessConfig:
    id: str
    name: str
    seats: int
    counters: int
    service_rate_per_counter_per_min: float
    walk_time_s: float = 30.0
    food_batch: int = 350
    food_refill_trigger: int = 120
    food_refill_time_min: float = 30.0  # call-back when running low: kitchen makes it and sends it (total)
    food_ready_refill_min: tuple[float, float] = (10.0, 14.0)  # when the food is already made: just sent
    food_ready_prob: float = 0.7  # chance the kitchen already has the next batch made when called
    items: tuple[str, ...] = ("Gravy sabji", "Dry sabji", "Dal", "Rice", "Special rice", "Roti", "Sambar / rasam", "Curd / raita", "Dessert")  # trays on the food-status page; first = the one the simulator tracks
    scanners: int = 1  # face-scan terminals at the entrance
    scan_time_s: float = 2.0  # time for one student to scan in

    @property
    def scan_capacity_per_min(self) -> float:
        return self.scanners * 60.0 / self.scan_time_s

    @property
    def expected_refill_min(self) -> float:
        """Average minutes from the 'running low' call to the refill arriving."""
        ready = sum(self.food_ready_refill_min) / 2
        return self.food_ready_prob * ready + (1 - self.food_ready_prob) * self.food_refill_time_min

    def refill_remaining_min(self, elapsed_min: float) -> float:
        """Expected minutes still to wait for a refill, given `elapsed_min` since the
        kitchen was called and no refill seen yet. Mixture of the two cases: already
        made (uniform food_ready_refill_min) with probability food_ready_prob, else
        made from scratch (food_refill_time_min). At 0 this is expected_refill_min."""
        e = max(0.0, elapsed_min)
        lo, hi = self.food_ready_refill_min
        p_ready = self.food_ready_prob * (1.0 if e <= lo else max(0.0, (hi - e) / (hi - lo)) if hi > lo else 0.0)
        p_cook = (1 - self.food_ready_prob) * (1.0 if e < self.food_refill_time_min else 0.0)
        if p_ready + p_cook == 0:
            return 0.0
        rem_ready = (max(e, lo) + hi) / 2 - e if e < hi else 0.0
        rem_cook = self.food_refill_time_min - e
        return (p_ready * rem_ready + p_cook * rem_cook) / (p_ready + p_cook)

    @property
    def capacity_per_min(self) -> float:
        """Maximum serving rate of the hall (students/min) while food is available."""
        return self.counters * self.service_rate_per_counter_per_min


@dataclass(frozen=True)
class TrayConfig:
    """How much one tray matters, from the ABC/XYZ priority matrix (MDS_dataset.xlsx).

    weight 1.0 = a star dish: if it runs OUT, students are sent to the other mess.
    Smaller weights only add a delay to that mess's predicted wait (see engine.food_penalty_min)."""
    name: str
    type: str = "Base food"  # Star dish / Made fresh in batches / Fresh side / One per plate / Base food / Table item
    cls: str = "CZ"  # ABC/XYZ class: AZ Tight Control, AX Calculated Issue, CZ Buffered Issue, CX Free Issue
    weight: float = 0.1

    @property
    def star(self) -> bool:
        return self.type == "Star dish"


@dataclass(frozen=True)
class EngineConfig:
    rate_window_min: float = 5.0
    horizon_min: float = 5.0
    stay_mean_min: float = 16.0  # inside after getting food: food line + eating + disposal
    eat_mean_min: float = 13.5  # seat held while eating (seat turnover)
    entry_min: float = 0.45  # scan + collect a plate, with no queue
    normal_visit_min: float = 18.0
    routing_update_s: float = 30.0
    routing_smoothing: float = 0.5
    min_share: float = 0.05
    amber_wait_min: float = 5.0
    red_wait_min: float = 10.0
    low_food_left_min: float = 20.0  # "running low" is tapped with about this many minutes of that food left
    food_out_grace_min: float = 5.0
    food_low_expiry_min: float = 20.0
    assumed_compliance: float = 1.0
    natural_share: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LayoutConfig:
    # "doors": a screen outside each mess entrance; students see it at the mess
    #          they were already walking to and either go in or walk to another.
    # "hallway": one shared screen before the paths to the messes split.
    mode: str = "doors"
    switch_walk_s: float = 30.0  # walk from one mess door to another
    min_saving_min: float = 2.0  # only suggest switching if it saves at least this much

    def __post_init__(self):
        if self.mode not in ("doors", "hallway"):
            raise ValueError("layout.mode must be 'doors' or 'hallway'")


@dataclass(frozen=True)
class PrivacyConfig:
    salt_env: str = "MESSQ_ID_SALT"
    retention_days: int = 30
    show_names: bool = False


@dataclass(frozen=True)
class MealSlot:
    name: str
    start: str
    duration_min: float
    expected_students: int
    peak_offset_min: float
    spread_min: float


@dataclass(frozen=True)
class SimConfig:
    habit_share: dict[str, float]
    slots: tuple[MealSlot, ...]
    step_s: float = 5.0
    compliance: float = 0.6
    staff_signal_prob: float = 0.9
    # The four stages of a visit (uniform ranges): scan + collect a plate; walk the
    # food line after the serving station; eat at a table; dispose of plate and leftovers.
    plate_pickup_s: tuple[float, float] = (15.0, 35.0)
    food_line_s: tuple[float, float] = (40.0, 80.0)
    eat_min: tuple[float, float] = (12.0, 15.0)
    dispose_min: tuple[float, float] = (1.0, 2.0)
    service_cv: float = 0.6

    def slot(self, name: str) -> MealSlot:
        for s in self.slots:
            if s.name == name:
                return s
        raise KeyError(f"no meal slot named {name!r}; have {[s.name for s in self.slots]}")


@dataclass(frozen=True)
class AppConfig:
    messes: tuple[MessConfig, ...]
    engine: EngineConfig
    privacy: PrivacyConfig
    simulation: SimConfig
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    trays: dict[str, TrayConfig] = field(default_factory=dict)

    def tray(self, name: str) -> TrayConfig:
        """Tray settings; a tray missing from the config counts as base food."""
        return self.trays.get(name) or TrayConfig(name)

    def mess(self, mess_id: str) -> MessConfig:
        for m in self.messes:
            if m.id == mess_id:
                return m
        raise KeyError(mess_id)


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    path = Path(path or os.environ.get("MESSQ_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return config_from_dict(raw)


def config_from_dict(raw: dict) -> AppConfig:
    messes = tuple(MessConfig(**{**m, "items": tuple(m.get("items", MessConfig.items)),
                                       "food_ready_refill_min": tuple(m.get("food_ready_refill_min", MessConfig.food_ready_refill_min))}) for m in raw["mess"])
    if len({m.id for m in messes}) != len(messes):
        raise ValueError("mess ids must be unique")
    sim_raw = dict(raw.get("simulation", {}))
    slots = tuple(MealSlot(**s) for s in sim_raw.pop("slot", []))
    habit = sim_raw.pop("habit_share", {m.id: 1 / len(messes) for m in messes})
    sim = SimConfig(habit_share=_normalise(habit, messes), slots=slots, **sim_raw)
    eng_raw = dict(raw.get("engine", {}))
    if "natural_share" in eng_raw:
        eng_raw["natural_share"] = _normalise(eng_raw["natural_share"], messes)
    engine = EngineConfig(**eng_raw)
    privacy = PrivacyConfig(**raw.get("privacy", {}))
    layout = LayoutConfig(**raw.get("layout", {}))
    trays = {t["name"]: TrayConfig(name=t["name"], type=t.get("type", "Base food"), cls=t.get("class", "CZ"),
                                   weight=float(t.get("weight", 0.1))) for t in raw.get("tray", [])}
    return AppConfig(messes=messes, engine=engine, privacy=privacy, simulation=sim, layout=layout, trays=trays)


def _normalise(shares: dict[str, float], messes: tuple[MessConfig, ...]) -> dict[str, float]:
    ids = {m.id for m in messes}
    if set(shares) != ids:
        raise ValueError(f"share keys {sorted(shares)} must match mess ids {sorted(ids)}")
    total = sum(shares.values())
    return {k: v / total for k, v in shares.items()}
