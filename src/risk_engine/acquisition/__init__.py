"""Data acquisition layer.

Each jurisdiction is an :class:`AcquisitionSource`. New small cities are added
by registering a new source — no other module changes. POC ships an Allegheny
County (Pittsburgh) source; others can be plugged in immediately.
"""

from .base import AcquisitionSource, get_source, list_sources, register_source
from .pittsburgh import AlleghenyCountySource

__all__ = [
    "AcquisitionSource",
    "register_source",
    "get_source",
    "list_sources",
    "AlleghenyCountySource",
]
