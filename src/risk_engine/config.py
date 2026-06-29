"""Lightweight, dependency-free runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    data_root: Path = ROOT / "data"
    raw_dir: Path = ROOT / "data" / "raw"
    processed_dir: Path = ROOT / "data" / "processed"
    # Below this OCR/extraction confidence floor, flags are suppressed rather
    # than surfaced as low-confidence (README 6.3). Calibrated during the POC.
    confidence_floor: float = 0.6
    default_jurisdiction: str = "allegheny_pa"

    @classmethod
    def from_env(cls) -> "Settings":
        floor = float(os.environ.get("RISK_ENGINE_CONFIDENCE_FLOOR", "0.6"))
        return cls(confidence_floor=floor)


settings = Settings()
