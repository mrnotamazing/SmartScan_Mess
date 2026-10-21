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
    food_refill_time_min: float = 10.0
    items: tuple[str, ...] = ("Main course", "Rice", "Roti", "Dal")  # trays the kitchen page shows; first = main

    @property
    def capacity_per_min(self) -> float:
        """Maximum serving rate of the hall (students/min) while food is available."""
        return self.counters * self.service_rate_per_counter_per_min


@dataclass(frozen=True)
class EngineConfig:
    rate_window_min: float = 5.0
    horizon_min: float = 5.0
    stay_mean_min: float = 17.0
    normal_visit_min: float = 18.0
    routing_update_s: float = 30.0
    routing_smoothing: float = 0.5
    min_share: float = 0.05
    amber_wait_min: float = 5.0
    red_wait_min: float = 10.0
    food_low_penalty_min: float = 2.0
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
    stay_mean_min: float = 17.0
    normal_visit_min: float = 18.0
    stay_sd_min: float = 6.0
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
    messes = tuple(MessConfig(**{**m, "items": tuple(m.get("items", MessConfig.items))}) for m in raw["mess"])
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
    return AppConfig(messes=messes, engine=engine, privacy=privacy, simulation=sim, layout=layout)


def _normalise(shares: dict[str, float], messes: tuple[MessConfig, ...]) -> dict[str, float]:
    ids = {m.id for m in messes}
    if set(shares) != ids:
        raise ValueError(f"share keys {sorted(shares)} must match mess ids {sorted(ids)}")
    total = sum(shares.values())
    return {k: v / total for k, v in shares.items()}
