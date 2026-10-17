"""One scoped Box Search request, followed by ranking only approved cached passages."""

import logging
import re
import time
from dataclasses import replace
from email.utils import parsedate_to_datetime

from box_sdk_gen.box.errors import BoxAPIError, BoxSDKError
from box_sdk_gen.managers.search import SearchManager
from box_sdk_gen.networking.box_network_client import BoxNetworkClient
from box_sdk_gen.networking.retries import BoxRetryStrategy
from requests import Session

from kloop.answer import SearchIndex

logger = logging.getLogger(__name__)
STOP_WORDS = frozenset(
    "a an and are as at be by can do does for from how in is it listed of on or "
    "please reported should tell that the their then these this to us was what when "
    "where which who why will with would you your according documented".split()
)


class SearchSession(Session):
    """A stalled Search call must leave time for the local fallback and generation."""

    def request(self, *args, **kwargs):
        kwargs["timeout"] = (2, 4)
        return super().request(*args, **kwargs)


def search_terms(question, names=()):
    # Known filenames are stronger disambiguators than generic question words.
    filenames = sorted(
        (name for name in names if name.casefold() in question.casefold()), key=len, reverse=True
    )
    if not filenames:
        filenames = re.findall(r"\b[\w][\w.-]*\.(?:docx|txt|md)\b", question, re.IGNORECASE)
    if filenames:
        stem = re.sub(r"\.(?:docx|txt|md)$", "", filenames[0], flags=re.IGNORECASE)
        return '"' + " ".join(re.findall(r"\w+", stem.replace("_", " "))) + '"'
    terms = [t for t in re.findall(r"[\w-]+", question.casefold()) if t not in STOP_WORDS]
    return " ".join(dict.fromkeys(terms))[:300]


def retry_delay(headers, now):
    value = next((v for k, v in headers.items() if k.casefold() == "retry-after"), "1")
    try:
        return max(1, float(value))
    except (ValueError, TypeError):
        try:
            return max(1, parsedate_to_datetime(value).timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 1


class BoxSearch:
    def __init__(self, sdk, folder_id, *, clock=time.time):
        if not folder_id or folder_id == "0":
            raise ValueError("Configure the approved non-root Box folder")
        self.search = SearchManager(
            auth=sdk.search.auth,
            network_session=sdk.search.network_session.with_retry_strategy(
                BoxRetryStrategy(max_attempts=1, max_retries_on_exception=0)
            ).with_network_client(BoxNetworkClient(requests_session=SearchSession())),
        )
        self.folder_id, self.clock, self.retry_at = folder_id, clock, 0

    def __call__(self, question, evidence):
        query = search_terms(question, (d.name for d in evidence.documents))
        if not query or self.clock() < self.retry_at:
            return evidence
        start = time.monotonic()
        try:
            result = self.search.search_for_content(
                query=query,
                ancestor_folder_ids=[self.folder_id],
                type="file",
                file_extensions=["docx", "txt", "md"],
                content_types=["name", "file_content"],
                limit=10,
                fields=["id", "type", "file_version"],
            )
        except BoxAPIError as error:
            status = error.response_info.status_code
            if status == 429:
                delay = retry_delay(error.response_info.headers, self.clock())
                self.retry_at = self.clock() + delay
                logger.warning(
                    "Box Search throttled; local index during %.2f second cooldown", delay
                )
            else:
                logger.warning("Box Search unavailable status=%s; using local index", status)
            return evidence
        except BoxSDKError:
            logger.warning("Box Search transport unavailable; using local index")
            return evidence
        pairs = {
            (entry.id, entry.file_version.id)
            for entry in (result.entries or [])
            if entry.type == "file" and getattr(entry, "file_version", None)
        }
        approved = {(d.file_id, d.version_id) for d in evidence.documents}
        pairs &= approved
        logger.info(
            "Box Search search_ms=%.2f approved_hits=%d",
            (time.monotonic() - start) * 1000,
            len(pairs),
        )
        if not pairs:
            return evidence
        index = evidence.search_index or SearchIndex.build(
            evidence.documents, approved_quotes=evidence.approved_quotes
        )
        positions = [i for i, c in enumerate(index.chunks) if (c.file_id, c.version_id) in pairs]
        selected = SearchIndex(
            chunks=[index.chunks[i] for i in positions],
            quote_counts=[index.quote_counts[i] for i in positions],
            name_counts=[index.name_counts[i] for i in positions],
        )
        if not selected.retrieve(question):
            return evidence
        return replace(evidence, search_index=selected, retriever="box_search")
