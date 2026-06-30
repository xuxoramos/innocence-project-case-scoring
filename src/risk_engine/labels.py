"""National Registry of Exonerations (NRE) reference loader.

The NRE export is published reference data, not case input (README v2 5.3): it
documents which structural-failure factors were present in known exonerations.
The POC uses it two ways, neither of which ranks or scores cases:

* **Schema-fidelity check** - confirm the categories the flagging engine knows
  about line up with the factors NRE actually records, and surface the failure
  modes the engine is structurally blind to (False Confession, Official
  Misconduct, Inadequate Legal Defense).
* **Named-official reference** - the NRE "Official Misconduct" data is a source
  for the named-official flag built in a later milestone.

It must never be fed into the processing pipeline as extraction text - NRE
records are reference labels, not case documents.

Schema note: this loader targets the NRE "full" CSV export (the file shipped in
``data/raw/exonerations/fullcsv.csv``). In that export the contributing factors
are **individual Yes/No columns**, not a single tags field, and the defendant is
one ``Name`` column. :data:`NRE_FACTOR_COLUMNS` maps the factor columns that line
up with our :class:`~risk_engine.models.FlagCategory` enum; the False-Confession
/ Official-Misconduct / Inadequate-Defense columns have no category counterpart
(they are exactly the structurally-blind failure modes README v2 warns about) but
are still recorded on the record for blind-spot analysis.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .models import FlagCategory

#: Default location of the NRE full CSV export within the repo's data tree.
DEFAULT_NRE_CSV: Path = settings.raw_dir / "exonerations" / "fullcsv.csv"

#: Env var holding the URL of the NRE full CSV export. The National Registry of
#: Exonerations (exonerationregistry.org) publishes its data through a download
#: flow rather than a stable public CSV link, so there is no hard-coded URL: a
#: refresh is opt-in and you supply the URL you were given. The repo ships a
#: snapshot at :data:`DEFAULT_NRE_CSV` so nothing here requires network access.
NRE_CSV_URL_ENV = "NRE_CSV_URL"


def download_nre_csv(
    url: str | None = None,
    dest: str | Path = DEFAULT_NRE_CSV,
) -> Path:
    """Download the NRE full CSV export to ``dest`` and return the path.

    ``url`` (or the ``NRE_CSV_URL`` env var) must point at the CSV export from
    exonerationregistry.org. ``requests`` is an optional dependency (install with
    ``pip install -e .[acquisition]``), imported lazily so the core package stays
    stdlib-only. This only *refreshes* the local snapshot; loading uses the
    on-disk CSV and never reaches the network.
    """
    url = url or os.environ.get(NRE_CSV_URL_ENV)
    if not url:
        raise ValueError(
            "No NRE CSV URL provided. Pass url= or set NRE_CSV_URL to the export "
            "link from exonerationregistry.org. The repo already ships a snapshot "
            f"at {DEFAULT_NRE_CSV}, so a download is only needed to refresh it."
        )
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "download_nre_csv needs the 'requests' package. "
            "Install it with: pip install -e .[acquisition]"
        ) from exc
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


#: NRE Yes/No factor column -> our FlagCategory (only the ones that map).
NRE_FACTOR_COLUMNS: dict[str, FlagCategory] = {
    "Mistaken Witness ID": FlagCategory.WITNESS_ID_CIRCUMSTANCE,
    "Mistaken Cross-group ID?": FlagCategory.WITNESS_ID_CIRCUMSTANCE,
    "False or Misleading Forensic Evidence": FlagCategory.DISCREDITED_FORENSIC_METHOD,
    "Perjury or False Accusation?": FlagCategory.INFORMANT_CIRCUMSTANCE,
    "DNA": FlagCategory.EVIDENCE_PRESERVATION,
    # Official misconduct, split by role (NRE codes these per-actor as Yes/No),
    # so each role's flag has its own case-level ground truth (README v2 6.5).
    "PR: Prosecutor Misconduct": FlagCategory.PROSECUTOR_MISCONDUCT,
    "Extreme judicial misconduct": FlagCategory.JUDICIAL_MISCONDUCT,
    "OF - OM by Police Officer": FlagCategory.POLICE_MISCONDUCT,
    "FA - OM by Forensic Analyst": FlagCategory.EXPERT_WITNESS_MISCONDUCT,
}

#: Recorded but unmapped — NRE failure modes our enum has no schema-check counterpart
#: for. "Official Misconduct" is the case-level ROLLUP of the role-specific columns
#: above; it stays unmapped to avoid double-counting (the per-role columns carry the
#: signal). "False Confession" and "Inadequate Legal Defense" have no flag category
#: (README v2 6.5 blind spots).
NRE_UNMAPPED_FACTOR_COLUMNS: tuple[str, ...] = (
    "False Confession",
    "Official Misconduct",
    "Inadequate Legal Defense",
)

_ALL_FACTOR_COLUMNS = tuple(NRE_FACTOR_COLUMNS) + NRE_UNMAPPED_FACTOR_COLUMNS


@dataclass
class ExonerationRecord:
    """One NRE exoneration, normalized to the fields the POC cares about."""

    nre_id: str = ""
    name: str = ""
    state: str = ""
    county: str = ""
    crime: str = ""
    crime_year: int | None = None
    conviction_year: int | None = None
    #: Human-readable NRE factor-column names that were marked present ("Yes").
    factors: set[str] = field(default_factory=set)

    def categories(self) -> set[FlagCategory]:
        """The FlagCategories this exoneration's mapped NRE factors imply."""
        return {NRE_FACTOR_COLUMNS[f] for f in self.factors if f in NRE_FACTOR_COLUMNS}


def load_known_exonerations(
    csv_path: str | Path = DEFAULT_NRE_CSV,
    *,
    state: str | None = None,
    county: str | None = None,
) -> list[ExonerationRecord]:
    """Load NRE exonerations from the full CSV export, optionally filtered.

    ``state`` / ``county`` filter case-insensitively against ``State`` and
    ``County of Crime`` so you can pull a state/county subset for blind-spot
    analysis. These are reference filters only, not a geographic constraint on
    matching (README v2 removed that) and not a held-out evaluation set.
    """
    records: list[ExonerationRecord] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rec = _row_to_record(row)
            if state and rec.state.lower() != state.lower():
                continue
            if county and rec.county.lower() != county.lower():
                continue
            records.append(rec)
    return records


def _row_to_record(row: dict) -> ExonerationRecord:
    factors = {
        col for col in _ALL_FACTOR_COLUMNS if (row.get(col) or "").strip().lower() == "yes"
    }
    return ExonerationRecord(
        nre_id=(row.get("ID") or "").strip(),
        name=(row.get("Name") or "").strip(),
        state=(row.get("State") or "").strip(),
        county=(row.get("County of Crime") or "").strip(),
        crime=(row.get("Worst Crime Display") or "").strip(),
        crime_year=_year(row.get("Date of Crime Year")),
        conviction_year=_year(row.get("Date of 1st Convic")),
        factors=factors,
    )


def _year(value: str | None) -> int | None:
    """Extract a 4-digit year from a year string or an ISO-ish date string."""
    text = (value or "").strip()
    if text[:4].isdigit():
        return int(text[:4])
    return None
