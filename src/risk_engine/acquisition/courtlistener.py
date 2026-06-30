"""CourtListener (Free Law Project) acquisition source.

Pulls digitized, public-domain appellate **opinions** from the CourtListener
REST API v4 (https://www.courtlistener.com/api/rest/v4/). Appellate opinions
narrate the trial facts an attorney needs (witness-ID circumstances, forensic
testimony, informant deals) and, crucially for the POC, are already clean
digital text — so the OCR step never fires and ``needs_ocr=False`` is the norm
for these documents (README 6.3 OCR machinery stays dormant until scanned
trial-court records are added later).

Design notes:
* ``requests`` is an *optional* dependency (``pip install -e .[acquisition]``).
  It is imported lazily so the core package stays stdlib-only and importable
  without it, mirroring the graceful-degradation pattern used by ``OCRStep``.
* An API token is read from ``COURTLISTENER_API_TOKEN`` (preferred). If absent,
  HTTP Basic auth is used from ``COURTLISTENER_USERNAME`` /
  ``COURTLISTENER_PASSWORD``. ``discover`` (the Search API) answers anonymous
  requests at a low rate limit, but ``fetch`` (the opinions detail endpoint)
  requires auth — a missing credential there raises a clear, actionable error
  rather than a raw HTTP 401. Credentials are read from the environment only and
  never stored in the repo.
* ``discover`` uses the Search API to enumerate candidate cases; ``fetch``
  downloads the full opinion text per the acquisition contract (discover yields
  shells, fetch populates documents).
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable

from ..models import Case, Document
from .base import AcquisitionSource, register_source

#: CourtListener court IDs for Pennsylvania appellate courts, where post-
#: conviction (PCRA) and direct-appeal narratives live.
PA_APPELLATE_COURTS = ("pa", "pasuperct")

#: Scope query (README 4): homicide / sexual-assault convictions.
DEFAULT_QUERY = '"murder" OR "homicide" OR "rape" OR "sexual assault"'


class CourtListenerSource(AcquisitionSource):
    """Acquire appellate opinions from CourtListener for a set of courts.

    The same class serves any jurisdiction: register one instance per
    jurisdiction key with the relevant CourtListener court IDs.
    """

    BASE_URL = "https://www.courtlistener.com/api/rest/v4"

    def __init__(
        self,
        jurisdiction: str,
        display_name: str,
        courts: tuple[str, ...] = PA_APPELLATE_COURTS,
        query: str = DEFAULT_QUERY,
        filed_before: str | None = None,
        token_env: str = "COURTLISTENER_API_TOKEN",
        username_env: str = "COURTLISTENER_USERNAME",
        password_env: str = "COURTLISTENER_PASSWORD",
        min_interval: float = 1.0,
        max_retries: int = 5,
    ) -> None:
        self.jurisdiction = jurisdiction
        self.display_name = display_name
        self.courts = courts
        self.query = query
        self.filed_before = filed_before
        self.token_env = token_env
        self.username_env = username_env
        self.password_env = password_env
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request = 0.0

    # -- HTTP plumbing -----------------------------------------------------

    def _has_credentials(self) -> bool:
        if os.environ.get(self.token_env):
            return True
        return bool(os.environ.get(self.username_env) and os.environ.get(self.password_env))

    def _session(self):
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "CourtListenerSource needs the 'requests' package. "
                "Install it with: pip install -e .[acquisition]"
            ) from exc
        session = requests.Session()
        token = os.environ.get(self.token_env)
        username = os.environ.get(self.username_env)
        password = os.environ.get(self.password_env)
        if token:
            # Token auth is preferred for programmatic access.
            session.headers["Authorization"] = f"Token {token}"
        elif username and password:
            # HTTP Basic auth fallback (works, but a token is recommended).
            session.auth = (username, password)
        session.headers["Accept"] = "application/json"
        return session

    #: Hard ceiling (seconds) on any single 429 wait. CourtListener's DRF
    #: throttling returns a ``Retry-After`` equal to the seconds until the
    #: *daily* window resets — up to ~86400s. Honoring that verbatim would
    #: park the process in a single multi-hour ``time.sleep`` (observed: an
    #: 8.5h hang on the first record). Cap it so we retry promptly and, if the
    #: limit is truly exhausted, fail fast with the actionable 429 error below.
    MAX_RETRY_WAIT = 60.0

    @classmethod
    def _retry_after_seconds(cls, resp, attempt: int) -> float:
        """Seconds to wait after a 429, honoring Retry-After then backing off.

        The result is always clamped to ``MAX_RETRY_WAIT`` so a large
        server-supplied ``Retry-After`` (e.g. a daily-quota reset window) can
        never translate into a multi-hour sleep.
        """
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), cls.MAX_RETRY_WAIT)
            except ValueError:
                pass  # HTTP-date form is unusual here; fall through to backoff
        # Exponential backoff with a sane ceiling (1, 2, 4, 8, ... <= 60s).
        return min(2.0**attempt, cls.MAX_RETRY_WAIT)

    def _get(self, session, path: str, params: dict | None = None) -> dict:
        url = path if path.startswith("http") else f"{self.BASE_URL}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            # Naive client-side rate limiting between every request.
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            resp = session.get(url, params=params, timeout=30)
            self._last_request = time.monotonic()
            if resp.status_code == 429:
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"CourtListener returned 429 Too Many Requests for {url} after "
                        f"{self.max_retries} retries. Anonymous access is throttled hard; "
                        f"set {self.token_env} (get one at "
                        "https://www.courtlistener.com/profile/api-token/) to raise the "
                        "limit, or rerun later with a larger --limit spacing."
                    )
                time.sleep(self._retry_after_seconds(resp, attempt))
                continue
            if resp.status_code == 401 and not self._has_credentials():
                raise RuntimeError(
                    f"CourtListener returned 401 Unauthorized for {url}. This endpoint "
                    f"requires authentication; set {self.token_env} (preferred; get one "
                    "at https://www.courtlistener.com/profile/api-token/) or "
                    f"{self.username_env}/{self.password_env} for HTTP Basic auth."
                )
            if resp.status_code in (401, 403) and self._has_credentials():
                raise RuntimeError(
                    f"CourtListener returned {resp.status_code} for {url} even though "
                    f"credentials are set. The {self.token_env} (or "
                    f"{self.username_env}/{self.password_env}) appears invalid, expired, "
                    "or revoked. Verify it at "
                    "https://www.courtlistener.com/profile/api-token/ and re-export it in "
                    "the same shell that runs risk-engine."
                )
            resp.raise_for_status()
            return resp.json()
        # Unreachable: the loop either returns or raises.
        raise RuntimeError("CourtListener request failed unexpectedly")  # pragma: no cover

    # -- AcquisitionSource contract ---------------------------------------

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        session = self._session()
        seen = 0
        # An empty ``courts`` tuple means no geographic filter — search nationally
        # (the flagged elements are checkable regardless of where a case was tried).
        courts = self.courts or (None,)
        for court in courts:
            params = {
                "type": "o",  # opinions
                "q": self.query,
                "order_by": "dateFiled desc",
            }
            # ``filed_before`` is an *optional* date ceiling. There is no default
            # cap: named-official and discredited-method flags need an official's
            # full record, which spans before and after any single year.
            if self.filed_before:
                params["filed_before"] = self.filed_before
            if court is not None:
                params["court"] = court
            url: str | None = f"{self.BASE_URL}/search/"
            while url:
                payload = self._get(session, url, params)
                params = None  # the `next` URL already encodes the query
                for result in payload.get("results", []):
                    case = self._result_to_case(result)
                    if case is None:
                        continue
                    yield case
                    seen += 1
                    if limit is not None and seen >= limit:
                        return
                url = payload.get("next")

    def fetch(self, case: Case) -> Case:
        opinion_ids = case.features.get("_cl_opinion_ids", [])
        if not opinion_ids or case.documents:
            return case
        session = self._session()
        for opinion_id in opinion_ids:
            data = self._get(session, f"opinions/{opinion_id}/")
            text = self._opinion_text(data)
            case.documents.append(
                Document(
                    doc_id=f"{case.case_id}-OP{opinion_id}",
                    case_id=case.case_id,
                    source_uri=data.get("absolute_url", "")
                    or f"{self.BASE_URL}/opinions/{opinion_id}/",
                    media_type="text/plain",
                    needs_ocr=False,  # appellate opinions are already digital
                    normalized_text=text,
                    metadata={"court": case.features.get("_cl_court", "")},
                )
            )
        return case

    # -- helpers -----------------------------------------------------------

    def _result_to_case(self, result: dict) -> Case | None:
        cluster_id = result.get("cluster_id") or result.get("id")
        if cluster_id is None:
            return None
        opinion_ids = [
            op.get("id") for op in result.get("opinions", []) if op.get("id") is not None
        ]
        date_filed = result.get("dateFiled") or ""
        year = int(date_filed[:4]) if date_filed[:4].isdigit() else None
        case = Case(
            case_id=f"CL-{cluster_id}",
            jurisdiction=self.jurisdiction,
            year=year,
            case_type=None,  # not reliably derivable from opinion metadata
        )
        case.features["_cl_opinion_ids"] = opinion_ids
        case.features["_cl_court"] = result.get("court", "")
        case.features["_cl_case_name"] = result.get("caseName", "")
        case.features["_cl_docket_number"] = result.get("docketNumber", "")
        return case

    @staticmethod
    def _opinion_text(data: dict) -> str:
        for key in ("plain_text", "html_with_citations", "html", "html_lawbox", "xml_harvard"):
            value = data.get(key)
            if value:
                return value
        return ""


# Pennsylvania appellate courts (covers Allegheny County appeals). Registered
# under a distinct key so the Allegheny fixture source stays available for
# offline tests.
register_source(
    CourtListenerSource(
        jurisdiction="pa_appellate_cl",
        display_name="Pennsylvania appellate courts (CourtListener)",
    )
)

# National appellate scope: no court filter, so an applicant from any state is
# matchable (README v2 pivot removed the geographic constraint — intake is the
# front door and the flagged elements are jurisdiction-independent).
register_source(
    CourtListenerSource(
        jurisdiction="appellate_cl",
        display_name="U.S. appellate courts (CourtListener, nationwide)",
        courts=(),
    )
)
