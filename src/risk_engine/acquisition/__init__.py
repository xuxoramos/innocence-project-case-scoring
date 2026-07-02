"""Data acquisition layer.

Each jurisdiction is an :class:`AcquisitionSource`. New small cities are added
by registering a new source — no other module changes. POC ships an Allegheny
County (Pittsburgh) source; others can be plugged in immediately.
"""

from .base import AcquisitionSource, get_source, list_sources, register_source
from .bulk_courtlistener import (
    DEFAULT_BULK_DIR,
    BulkCourtListenerMatcher,
    download_bulk_snapshots,
    resolve_latest_snapshot,
)
from .courtlistener import PA_APPELLATE_COURTS, CourtListenerSource
from .demo_marvel import DemoMarvelSource
from .pittsburgh import AlleghenyCountySource

__all__ = [
    "AcquisitionSource",
    "register_source",
    "get_source",
    "list_sources",
    "AlleghenyCountySource",
    "CourtListenerSource",
    "DemoMarvelSource",
    "PA_APPELLATE_COURTS",
    "BulkCourtListenerMatcher",
    "download_bulk_snapshots",
    "resolve_latest_snapshot",
    "DEFAULT_BULK_DIR",
]
