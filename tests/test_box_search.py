from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from box_sdk_gen.box.errors import BoxAPIError

from kloop.answer import Answerer, SearchIndex
from kloop.answer.box_search import BoxSearch, search_terms
from kloop.schemas import Document
from kloop.web.jobs import SearchEvidence

BASE = "arn:aws:bedrock:us-east-2:123456789012:imported-model/aaaaaaaaaaaa"


@pytest.fixture
def evidence():
    documents = [
        Document(
            file_id="approved", version_id="v1", name="Policy.docx", text="The date is Monday."
        ),
        Document(file_id="other", version_id="v2", name="Other.docx", text="The date is Tuesday."),
    ]
    quotes = {(d.file_id, d.version_id): [d.text] for d in documents}
    return SearchEvidence(documents, quotes, SearchIndex.build(documents, approved_quotes=quotes))


def hit(file="approved", version="v1", type="file"):
    return SimpleNamespace(id=file, file_version=SimpleNamespace(id=version), type=type)


def retriever(monkeypatch, entries=()):
    search = Mock()
    search.search_for_content.return_value = SimpleNamespace(entries=list(entries))
    constructor = Mock(return_value=search)
    monkeypatch.setattr("kloop.answer.box_search.SearchManager", constructor)
    sdk = Mock()
    clock = SimpleNamespace(now=100)
    value = BoxSearch(sdk, "428391006380", clock=lambda: clock.now)
    return value, search, sdk, clock


def test_box_search_scope_and_approval_filter_keep_exact_source_citations(monkeypatch, evidence):
    box, search, sdk, _ = retriever(monkeypatch, [hit(), hit("unapproved"), hit(type="folder")])
    selected = box("What date is in Policy.docx?", evidence)
    assert selected.retriever == "box_search"
    citations = selected.search_index.retrieve("date")
    assert len(citations) == 1
    assert citations[0].model_dump(exclude={"label"}) == evidence.search_index.retrieve(
        "Policy.docx date"
    )[0].model_dump(exclude={"label"})
    call = search.search_for_content.call_args.kwargs
    assert call == {
        "query": '"Policy"',
        "ancestor_folder_ids": ["428391006380"],
        "type": "file",
        "file_extensions": ["docx", "txt", "md"],
        "content_types": ["name", "file_content"],
        "limit": 10,
        "fields": ["id", "type", "file_version"],
    }
    strategy = sdk.search.network_session.with_retry_strategy.call_args.args[0]
    assert strategy.max_attempts == 1
    assert strategy.max_retries_on_exception == 0
    search.search_for_content.assert_called_once()
    model = Mock()
    model.invoke.return_value = {"generation": "Monday [1]"}
    result = Answerer(model).answer_search(
        "date", BASE, selected.documents, search_index=selected.search_index
    )
    assert result.citations == citations
    assert result.model_arn == BASE


@pytest.mark.parametrize(
    "entries", [[], [hit(version="v2")], [hit("unapproved")], [hit(version=None)]]
)
def test_empty_unapproved_and_version_mismatched_results_use_local_index(
    monkeypatch, evidence, entries
):
    box, search, _, _ = retriever(monkeypatch, entries)
    assert box("date", evidence) is evidence
    assert evidence.retriever == "local"
    assert len(evidence.search_index.retrieve("date")) == 2
    search.search_for_content.assert_called_once()


def test_429_falls_back_once_and_honors_retry_after_without_delaying_the_answer(
    monkeypatch, evidence
):
    box, search, _, clock = retriever(monkeypatch, [hit()])
    error = BoxAPIError(
        request_info=None,
        response_info=SimpleNamespace(status_code=429, headers={"Retry-After": "60"}),
        message="Rate limited",
    )
    search.search_for_content.side_effect = [error, SimpleNamespace(entries=[hit()])]
    assert box("date", evidence) is evidence
    assert box.retry_at == 160
    clock.now = 159
    assert box("date", evidence) is evidence
    assert search.search_for_content.call_count == 1
    clock.now = 160
    assert box("date", evidence).retriever == "box_search"
    assert search.search_for_content.call_count == 2


def test_transient_search_error_keeps_local_approved_passages(monkeypatch, evidence):
    box, search, _, _ = retriever(monkeypatch)
    search.search_for_content.side_effect = BoxAPIError(
        request_info=None, response_info=SimpleNamespace(status_code=503), message="Unavailable"
    )
    assert box("date", evidence) is evidence


def test_box_hit_without_matching_approved_passage_uses_local_fallback(monkeypatch, evidence):
    box, _, _, _ = retriever(monkeypatch, [hit()])
    assert box("Tuesday", evidence) is evidence


def test_query_uses_known_filename_or_safe_question_keywords():
    copy = "CTD Module 1 DEMO COPY BLA-6546-89 20261017.docx"
    assert (
        search_terms(f"For the {copy}, what is the submission date?", [copy])
        == '"CTD Module 1 DEMO COPY BLA 6546 89 20261017"'
    )
    assert (
        search_terms("Who is the owner of the owner support procedure?")
        == "owner support procedure"
    )
    assert search_terms("what is the") == ""


def test_search_timeout_keeps_the_local_index_and_transport_is_bounded(monkeypatch, evidence):
    from box_sdk_gen.box.errors import BoxSDKError
    from requests import Session

    from kloop.answer.box_search import SearchSession

    box, search, _, _ = retriever(monkeypatch)
    search.search_for_content.side_effect = BoxSDKError(message="Timed out")
    assert box("date", evidence) is evidence
    request = Mock()
    monkeypatch.setattr(Session, "request", request)
    SearchSession().request("GET", "https://api.box.com/2.0/search", timeout=(5, 60))
    assert request.call_args.kwargs["timeout"] == (2, 4)


@pytest.mark.parametrize("hybrid", [False, True])
def test_worker_persists_the_actual_retriever_with_the_answer(evidence, hybrid):
    from dataclasses import replace

    from kloop.web.jobs import JobService, MemoryJobs, Worker

    jobs = JobService(MemoryJobs(), Mock())
    model = Mock()
    model.invoke.return_value = {"generation": "Monday [1]"}
    chosen = replace(evidence, retriever="box_search") if hybrid else evidence
    worker = Worker(jobs, model, lambda _: evidence, search_retriever=lambda *_: chosen)
    job = jobs.create("Policy.docx date", "search", BASE, "base", "a" * 64)
    worker.run(job.id)
    completed = jobs.get(job.id)
    assert completed.status == "succeeded"
    assert completed.retriever == ("box_search" if hybrid else "local")
    assert completed.citations[0]["version_id"] == "v1"
