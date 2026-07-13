"""Base classes and registry for jurisdiction acquisition sources."""

from __future__ import annotations

import abc
from collections.abc import Iterable

from ..models import Case

_SOURCES: dict[str, "AcquisitionSource"] = {}


class AcquisitionSource(abc.ABC):
    """Acquires raw public court records for one jurisdiction.

    Implementations only need to know how to enumerate cases and fetch the
    documents for one. Pittsburgh ships first; other small cities register
    their own subclass.
    """

    #: Stable jurisdiction key, e.g. ``"allegheny_pa"``.
    jurisdiction: str = ""
    #: Human-readable name, e.g. ``"Allegheny County, PA (Pittsburgh)"``.
    display_name: str = ""
    #: Offline fixture source (no network). The minimum-viable-text threshold
    #: (spec v3 item 5) is skipped for these, so small deterministic fixtures
    #: still flag; live sources apply the threshold and route thin text to the
    #: manual-paste fallback (item 4).
    offline: bool = False

    @abc.abstractmethod
    def discover(self, limit: int | None = None) -> Iterable[Case]:
        """Yield shell ``Case`` objects (no documents fetched yet)."""

    @abc.abstractmethod
    def fetch(self, case: Case) -> Case:
        """Download documents for ``case`` and populate ``case.documents``."""


def register_source(source: AcquisitionSource) -> AcquisitionSource:
    if not source.jurisdiction:
        raise ValueError("source.jurisdiction must be set")
    _SOURCES[source.jurisdiction] = source
    return source


def get_source(jurisdiction: str) -> AcquisitionSource:
    try:
        return _SOURCES[jurisdiction]
    except KeyError:
        raise KeyError(f"No acquisition source registered for {jurisdiction!r}") from None


def list_sources() -> list[str]:
    return sorted(_SOURCES)
