"""Offline CourtListener **bulk-data** matcher (no API, no rate limit).

The API source (:mod:`risk_engine.acquisition.courtlistener`) discovers candidate
opinions one throttled request at a time, which means linking the whole
exoneration set runs into CourtListener's *daily* request quota. Free Law Project
also publishes the same corpus as quarterly **bulk CSV snapshots** on a public S3
bucket (public-domain, no auth, no rate limit):

    https://com-courtlistener-storage.s3-us-west-2.amazonaws.com/list.html?prefix=bulk-data/

This module joins our exonerations to that bulk data entirely offline. The work
is bounded by the exonerations we hold (~4.3k rows), not by jurisdiction and not
by the size of the corpus:

* **Matching** streams the ``opinion-clusters`` snapshot once and keeps only the
  clusters whose caption shares a surname with one of our exonerees — so the
  in-memory index is sized by *our* set, never by the millions of national
  clusters. Each exoneration is then scored against its surname's clusters with
  the very same name+year scorer the live intake flow uses
  (:func:`risk_engine.retrieval.score_candidate`), so a bulk match and an API
  match mean exactly the same thing.
* **Text** streams the (large) ``opinions`` snapshot once and attaches
  ``plain_text`` only for clusters that actually matched — text for matches only,
  never the whole corpus in memory.

The matcher is pure and offline-testable (feed it file paths to small CSVs). The
network is confined to :func:`download_bulk_snapshots`, a thin helper that fetches
the latest snapshots, mirroring the lazy-``requests`` pattern used elsewhere.
"""

from __future__ import annotations

import bz2
import csv
import gzip
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import settings
from ..models import Case, Document

if TYPE_CHECKING:
    from ..retrieval import CandidateMatch, MatchCriteria

# Opinion (and some cluster) text fields routinely exceed Python's default 128 KB
# per-field CSV cap — a full court opinion is often hundreds of KB. Lift the cap
# to the platform maximum so streaming a snapshot never dies mid-file.
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:  # pragma: no cover - platform C long is narrower than maxsize
    csv.field_size_limit(2**31 - 1)

#: Public bulk-data bucket (no credentials needed; HTTP GET works anonymously).
BULK_BUCKET_URL = "https://com-courtlistener-storage.s3-us-west-2.amazonaws.com"

#: Where snapshots live by default once downloaded.
DEFAULT_BULK_DIR: Path = settings.raw_dir / "courtlistener_bulk"

#: Object-name stems for the snapshots we use (matching needs clusters; text
#: needs opinions; courts is optional metadata we do not require).
CLUSTERS_STEM = "opinion-clusters"
OPINIONS_STEM = "opinions"
COURTS_STEM = "courts"

#: CSV caption fields on the cluster snapshot, best first.
_CLUSTER_NAME_FIELDS = ("case_name", "case_name_full", "case_name_short")
#: CSV text fields on the opinion snapshot, best first (mirrors the API source).
_OPINION_TEXT_FIELDS = (
    "plain_text",
    "html_with_citations",
    "html",
    "html_lawbox",
    "xml_harvard",
)

_DATE_YEAR_RE = re.compile(r"\b(18|19|20)\d{2}\b")


def _open_text(path: str | Path):
    """Open a possibly bz2/gzip-compressed CSV snapshot as a UTF-8 text stream."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", newline="")
    if suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, encoding="utf-8", newline="")


def _reader(stream) -> csv.DictReader:
    """A DictReader configured for PostgreSQL ``COPY TO`` CSV (ESCAPE '\\')."""
    return csv.DictReader(stream, doublequote=False, escapechar="\\")


def _year_from(value: str | None) -> int | None:
    text = (value or "").strip()
    if text[:4].isdigit():
        return int(text[:4])
    m = _DATE_YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def _first(row: dict, fields: Iterable[str]) -> str:
    for f in fields:
        v = row.get(f)
        if v:
            return v
    return ""


@dataclass(slots=True)
class ClusterRecord:
    """The few opinion-cluster fields the offline join needs."""

    cluster_id: str
    case_name: str
    year: int | None

    def to_case(self) -> Case:
        """A shell :class:`Case` carrying just enough for name+year scoring."""
        case = Case(
            case_id=f"CL-{self.cluster_id}",
            jurisdiction="bulk_cl",
            year=self.year,
            case_type=None,
        )
        case.features["_cl_case_name"] = self.case_name
        case.features["_cl_cluster_id"] = self.cluster_id
        return case


def iter_cluster_records(path: str | Path) -> Iterator[ClusterRecord]:
    """Stream :class:`ClusterRecord` rows from an ``opinion-clusters`` snapshot."""
    with _open_text(path) as stream:
        for row in _reader(stream):
            cluster_id = (row.get("id") or "").strip()
            if not cluster_id:
                continue
            name = _first(row, _CLUSTER_NAME_FIELDS).strip()
            if not name:
                continue
            yield ClusterRecord(
                cluster_id=cluster_id,
                case_name=name,
                year=_year_from(row.get("date_filed")),
            )


class BulkCourtListenerMatcher:
    """Offline name+year matcher over CourtListener bulk-data snapshots.

    Construct it with the snapshot file paths and the exonerations to be matched;
    :meth:`build_index` streams the cluster snapshot once, retaining only clusters
    whose caption shares a surname with one of those exonerations.
    """

    def __init__(
        self,
        clusters_path: str | Path,
        *,
        opinions_path: str | Path | None = None,
    ) -> None:
        self.clusters_path = Path(clusters_path)
        self.opinions_path = Path(opinions_path) if opinions_path else None
        #: surname token -> candidate clusters sharing it (built lazily).
        self._index: dict[str, list[ClusterRecord]] = {}
        self._surnames: set[str] = set()
        self._built = False

    def build_index(self, surnames: Iterable[str]) -> "BulkCourtListenerMatcher":
        """Index only clusters whose caption contains one of ``surnames``.

        Bounding the index by *our* surname set is what keeps this feasible: the
        national cluster corpus has millions of rows, but we keep only the
        handful per exoneree surname.
        """
        from ..retrieval import identity_tokens

        self._surnames = {s for s in surnames if s}
        index: dict[str, list[ClusterRecord]] = {}
        for rec in iter_cluster_records(self.clusters_path):
            tokens = set(identity_tokens(rec.case_name)) & self._surnames
            for token in tokens:
                index.setdefault(token, []).append(rec)
        self._index = index
        self._built = True
        return self

    def best_match(self, criteria: MatchCriteria) -> CandidateMatch | None:
        """Highest-confidence cluster for ``criteria`` (name+year), or ``None``.

        Identical scoring to the live flow: a candidate must clear the name floor
        (:data:`risk_engine.retrieval.NAME_MATCH_FLOOR`); a consistent year breaks
        ties. Returns a metadata-only match (no opinion text yet — see
        :meth:`attach_text`).
        """
        from ..retrieval import score_candidate, surname_token

        key = surname_token(criteria.full_name)
        if key is None:
            return None
        best: CandidateMatch | None = None
        for rec in self._index.get(key, ()):  # empty when surname absent from corpus
            scored = score_candidate(criteria, rec.to_case())
            if scored.is_match and (best is None or scored.confidence > best.confidence):
                best = scored
        return best

    def attach_text(self, cases_by_cluster: dict[str, Case]) -> int:
        """Populate ``documents`` for matched clusters from the opinion snapshot.

        Streams the (large) ``opinions`` snapshot once, attaching ``plain_text``
        (or the best available text field) only for the clusters in
        ``cases_by_cluster``. Returns the number of opinion documents attached. A
        no-op (returns 0) when no opinions snapshot is configured.
        """
        if not self.opinions_path or not cases_by_cluster:
            return 0
        attached = 0
        with _open_text(self.opinions_path) as stream:
            for row in _reader(stream):
                cluster_id = (row.get("cluster_id") or "").strip()
                case = cases_by_cluster.get(cluster_id)
                if case is None:
                    continue
                text = _first(row, _OPINION_TEXT_FIELDS)
                if not text:
                    continue
                opinion_id = (row.get("id") or "").strip()
                case.documents.append(
                    Document(
                        doc_id=f"{case.case_id}-OP{opinion_id}",
                        case_id=case.case_id,
                        source_uri=f"https://www.courtlistener.com/opinions/{opinion_id}/",
                        media_type="text/plain",
                        needs_ocr=False,  # bulk opinions are already digital text
                        normalized_text=text,
                        metadata={"cluster_id": cluster_id},
                    )
                )
                attached += 1
        return attached


# -- snapshot discovery / download (thin network shell) --------------------


def resolve_latest_snapshot(directory: str | Path, stem: str) -> Path | None:
    """Newest local ``{stem}-YYYY-MM-DD.csv[.bz2|.gz]`` file in ``directory``.

    Snapshots are named with their generation date, so lexical max on the
    filename is also the most recent. Returns ``None`` when none are present.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(stem)}-\d{{4}}-\d{{2}}-\d{{2}}\.csv(\.bz2|\.gz)?$")
    matches = sorted(p for p in directory.iterdir() if pattern.match(p.name))
    return matches[-1] if matches else None


def download_bulk_snapshots(
    dest_dir: str | Path = DEFAULT_BULK_DIR,
    *,
    stems: Iterable[str] = (CLUSTERS_STEM, OPINIONS_STEM),
    bucket_url: str = BULK_BUCKET_URL,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Path]:
    """Download the latest bulk snapshot for each stem into ``dest_dir``.

    Lists the public ``bulk-data/`` prefix, picks the newest object per stem, and
    streams it to disk. ``requests`` is an optional dependency (install with
    ``pip install -e .[acquisition]``), imported lazily so the core package stays
    stdlib-only. Returns ``{stem: local_path}`` for what was fetched.
    """
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "download_bulk_snapshots needs the 'requests' package. "
            "Install it with: pip install -e .[acquisition]"
        ) from exc

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    keys = _list_bulk_keys(requests, bucket_url)
    out: dict[str, Path] = {}
    for stem in stems:
        key = _latest_key_for_stem(keys, stem)
        if key is None:
            raise RuntimeError(
                f"No bulk-data object found for stem {stem!r} at {bucket_url}. "
                "Browse the bucket to confirm the current file names."
            )
        dest = dest_dir / os.path.basename(key)
        if progress is not None:
            progress(f"downloading {key} -> {dest}")
        with requests.get(f"{bucket_url}/{key}", stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        fh.write(chunk)
        out[stem] = dest
    return out


def _list_bulk_keys(requests_mod, bucket_url: str) -> list[str]:
    """List object keys under the ``bulk-data/`` prefix (handles S3 pagination)."""
    import xml.etree.ElementTree as ET

    keys: list[str] = []
    token: str | None = None
    while True:
        params = {"list-type": "2", "prefix": "bulk-data/"}
        if token:
            params["continuation-token"] = token
        resp = requests_mod.get(bucket_url, params=params, timeout=60)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"s3": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

        def _find(el, tag):
            return el.find(f"s3:{tag}", ns) if ns else el.find(tag)

        for contents in (root.findall("s3:Contents", ns) if ns else root.findall("Contents")):
            key_el = _find(contents, "Key")
            if key_el is not None and key_el.text:
                keys.append(key_el.text)
        truncated = _find(root, "IsTruncated")
        if truncated is None or truncated.text != "true":
            break
        next_token = _find(root, "NextContinuationToken")
        token = next_token.text if next_token is not None else None
        if not token:
            break
    return keys


def _latest_key_for_stem(keys: Iterable[str], stem: str) -> str | None:
    pattern = re.compile(rf"(^|/){re.escape(stem)}-\d{{4}}-\d{{2}}-\d{{2}}\.csv(\.bz2|\.gz)?$")
    matches = sorted(k for k in keys if pattern.search(k))
    return matches[-1] if matches else None
