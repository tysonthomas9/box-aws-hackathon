import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from box_sdk_gen import AiExtractStructuredResponse
from box_sdk_gen.box.errors import BoxAPIError
from pydantic import ValidationError

from kloop.adapters.memory import FakeBoxClient, MemoryStorage
from kloop.extract.live import LiveLedger, recovery
from kloop.extract.provider import BOX_MODEL, BoxAIExtractor, GLMExtractor, parse_answer
from kloop.extract.repository import ConcurrentUpdate, DynamoRepository, Repository
from kloop.extract.service import ExtractionService, digest
from kloop.schemas import Document, ExtractionRow

FIXTURE = Path(__file__).parent / "fixtures/extract/recorded.json"
RECORDINGS = json.loads(FIXTURE.read_text())


@pytest.fixture(params=["memory", "dynamodb"])
def repository(request, aws_session):
    if request.param == "memory":
        return Repository(MemoryStorage())
    table = aws_session.resource("dynamodb").create_table(
        TableName="extraction-test",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )
    return DynamoRepository(table)


class RecordedExtractor:
    def __init__(self, records=RECORDINGS):
        self.records, self.calls = records, 0

    def extract(self, document, identities):
        self.calls += 1
        record = next(r for r in self.records if r["document"] == document.model_dump())
        return parse_answer(record["answer"]), record["extractor"]


def recorded_service(repository, records=RECORDINGS, mode="exceptions"):
    documents = [Document.model_validate(r["document"]) for r in records]
    return ExtractionService(
        FakeBoxClient({"test": documents}), RecordedExtractor(records), repository, mode
    )


def load_pack(service):
    for record in RECORDINGS[:13]:
        d = record["document"]
        assert service.process(d["file_id"], d["version_id"]) == len(record["answer"]["items"])


def test_recorded_gold_and_exact_v2_flags_and_rejected_replay(repository):
    service = recorded_service(repository)
    load_pack(service)
    initial = service.snapshot()
    score = recovery(json.loads(Path("pack/gold.json").read_text()), initial.items)
    assert score["rate"] >= 0.9
    assert len(initial.items) == sum(len(r["answer"]["items"]) for r in RECORDINGS[:13])
    assert not service.reviews()
    changed = RECORDINGS[13]["document"]
    sable = next(i for i in initial.items if i.source_file_id == changed["file_id"])
    quartz = next(
        i
        for i in initial.items
        if i.source_file_id
        == next(
            r["document"]["file_id"] for r in RECORDINGS if r["document"]["name"] == "quartz.txt"
        )
    )
    assert changed["file_id"] == sable.source_file_id
    assert service.process(changed["file_id"], changed["version_id"]) == 1
    assert service.retire(quartz.source_file_id) == 1
    pending = service.reviews()
    assert {tuple(r.reasons) for r in pending} == {("changed_value",), ("source_deleted",)}
    assert {r.item_id for r in pending} == {sable.id, quartz.id}
    assert service.snapshot() == initial
    for r in pending:
        service.decide(r.id, "reject", actor="tester")
    restarted = recorded_service(repository)
    assert restarted.process(changed["file_id"], changed["version_id"]) == 0
    assert restarted.retire(quartz.source_file_id) == 0
    assert not restarted.reviews()
    assert restarted.snapshot() == initial
    assert len([r for r in restarted.reviews(pending_only=False) if r.decision == "rejected"]) == 2


def test_approve_change_retire_and_immutable_snapshot(repository):
    service = recorded_service(repository)
    load_pack(service)
    initial = service.snapshot()
    changed = RECORDINGS[13]["document"]
    service.process(changed["file_id"], changed["version_id"])
    review = service.reviews()[0]
    service.decide(review.id, "approve", actor="tester")
    assert service.decide(review.id, "approve", actor="tester").decision == "approved"
    updated = service.snapshot()
    assert initial.sha256 != updated.sha256
    sable = next(i for i in updated.items if i.id == review.item_id)
    assert "96 GB" in sable.statement
    assert sable.source_version_id == changed["version_id"]
    quartz = next(
        i
        for i in initial.items
        if i.source_file_id
        == next(
            r["document"]["file_id"] for r in RECORDINGS if r["document"]["name"] == "quartz.txt"
        )
    )
    service.retire(quartz.source_file_id)
    service.decide(service.reviews()[0].id, "approve", actor="tester")
    final = service.snapshot()
    assert len(final.items) == len(initial.items) - 1
    assert quartz.id not in {i.id for i in final.items}
    assert repository.storage.get("approved_snapshots", initial.sha256) == initial.model_dump()
    assert digest([i.model_dump(mode="json") for i in initial.items]) == initial.sha256
    corrupted = initial.model_dump()
    corrupted["items"] = []
    with pytest.raises(ValueError, match="corrupt"):
        repository.save_snapshot(corrupted)


def one_service(repository, row=None, mode="exceptions"):
    row = row or ExtractionRow(
        kind="fact",
        subject="Sable archive",
        attribute="daily_upload_limit",
        statement="Limit is 73 GB.",
        supporting_quote="Limit is 73 GB.",
    )
    box = Mock()
    box.get_document.side_effect = lambda f, v: Document(
        file_id=f, version_id=v, name="source.txt", text="Limit is 73 GB. Limit is 96 GB."
    )
    provider = Mock()
    provider.extract.return_value = ([row], "box-ai/pinned")
    return ExtractionService(box, provider, repository, mode), provider


def test_omission_never_retires_and_process_noop(repository):
    service, provider = one_service(repository)
    assert service.process("f", "v1") == 1
    assert service.process("f", "v1") == 0
    assert provider.extract.call_count == 1
    original = service.snapshot()
    provider.extract.return_value = ([], "box-ai/pinned")
    assert service.process("f", "v2") == 0
    assert service.snapshot() == original
    assert not service.reviews()


def test_edit_and_persistent_review_mode(repository):
    service, provider = one_service(repository)
    service.set_review_mode("all")
    assert one_service(repository)[0].get_review_mode() == "all"
    service.process("f", "v1")
    assert not service.snapshot().items
    review = service.reviews()[0]
    edited = review.candidate.model_copy(update={"statement": "The limit is 73 GB."})
    with pytest.raises(ValueError, match="identity"):
        service.decide(
            review.id,
            "edit",
            actor="tester",
            edited=edited.model_copy(update={"attribute": "different"}),
        )
    service.decide(review.id, "edit", actor="tester", edited=edited)
    assert service.snapshot().items[0].statement == edited.statement
    assert service.reviews(pending_only=False)[0].decision == "edited"
    with pytest.raises(ValueError, match="already"):
        service.decide(review.id, "reject", actor="tester")
    service.set_review_mode("off")
    provider.extract.return_value = (
        [
            edited.model_copy(
                update={"statement": "Limit is 96 GB.", "supporting_quote": "Limit is 96 GB."}
            )
        ],
        "box-ai/pinned",
    )
    service.process("f", "v2")
    assert not service.reviews()
    assert service.snapshot().items[0].statement == "Limit is 96 GB."
    with pytest.raises(ValueError):
        service.set_review_mode("invalid")


@pytest.mark.parametrize(
    "update,reason",
    [
        ({"supporting_quote": "invented quote"}, "quote_not_in_source"),
        ({"statement": ""}, "missing_statement"),
        ({"kind": "procedure"}, "missing_procedure_fields"),
    ],
)
def test_automatic_checks_flag_bad_rows_even_when_review_off(repository, update, reason):
    service, provider = one_service(repository, mode="off")
    row = provider.extract.return_value[0][0].model_copy(update=update)
    provider.extract.return_value = ([row], "box-ai/pinned")
    service.process("f", "v1")
    assert reason in service.reviews()[0].reasons
    assert not service.snapshot().items


def test_duplicate_and_cross_source_conflict(repository):
    service, provider = one_service(repository)
    row = provider.extract.return_value[0][0]
    provider.extract.return_value = ([row, row], "box-ai/pinned")
    assert service.process("f", "v1") == 1
    service.process("other", "v1")
    assert service.reviews()[0].reasons == ["duplicate"]
    provider.extract.return_value = (
        [
            row.model_copy(
                update={"statement": "Limit is 96 GB.", "supporting_quote": "Limit is 96 GB."}
            )
        ],
        "box-ai/pinned",
    )
    service.process("third", "v1")
    assert {tuple(r.reasons) for r in service.reviews()} == {("duplicate",), ("conflict",)}
    assert len(service.snapshot().items) == 1


def test_conflicting_rows_and_invalid_schema_fail_without_checkpoint(repository):
    service, provider = one_service(repository)
    row = provider.extract.return_value[0][0]
    provider.extract.return_value = (
        [row, row.model_copy(update={"statement": "different"})],
        "box",
    )
    with pytest.raises(ValueError, match="Conflicting"):
        service.process("f", "v1")
    assert repository.read()["revision"] == 0
    with pytest.raises(ValidationError):
        parse_answer({"items": [{"kind": "fact", "stale": "wrong"}]})


def test_atomic_failure_and_ambiguous_success_replay(repository, monkeypatch):
    service, _ = one_service(repository)
    commit = repository.commit

    def fail_before(*args):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(repository, "commit", fail_before)
    with pytest.raises(RuntimeError):
        service.process("f", "v1")
    assert repository.read()["items"] == {}

    def fail_after(*args):
        commit(*args)
        raise RuntimeError("response lost")

    monkeypatch.setattr(repository, "commit", fail_after)
    with pytest.raises(RuntimeError):
        service.process("f", "v1")
    monkeypatch.setattr(repository, "commit", commit)
    assert service.process("f", "v1") == 0
    assert len(service.snapshot().items) == 1


def test_cas_rejects_stale_write_and_state_bound(repository):
    before = repository.read()
    after = deepcopy(before)
    after["review_mode"] = "all"
    repository.commit(before, after)
    with pytest.raises(ConcurrentUpdate):
        repository.commit(before, after)
    before = repository.read()
    after = deepcopy(before)
    after["batches"]["large"] = "x" * 350_000
    with pytest.raises(ValueError, match="bound"):
        repository.commit(before, after)


def test_box_sdk_pinned_table_content_and_pacing():
    sdk = Mock()
    raw = json.loads((FIXTURE.parent / "raw-recorded.json").read_text())[0]
    sdk.ai.create_ai_extract_structured.return_value = AiExtractStructuredResponse.from_dict(raw)
    pause = Mock()
    provider = BoxAIExtractor(sdk, pause=pause)
    doc = Document.model_validate(RECORDINGS[0]["document"])
    rows, name = provider.extract(doc, [])
    provider.extract(doc, [])
    assert name.endswith(BOX_MODEL) and len(rows) == 1
    args, kwargs = sdk.ai.create_ai_extract_structured.call_args
    assert len(args[0]) == 1 and args[0][0].to_dict()["content"] == doc.text
    field = kwargs["fields"][0].to_dict()
    assert field["type"] == "table" and {f["key"] for f in field["fields"]} >= {
        "attribute",
        "supporting_quote",
        "steps",
        "trigger_conditions",
    }
    agent = kwargs["ai_agent"].to_dict()
    assert agent["basic_text"]["model"] == agent["long_text"]["model"] == BOX_MODEL
    pause.assert_called_once()


def test_box_api_error_falls_back_but_invalid_payload_does_not():
    sdk, fallback = Mock(), Mock()
    provider = BoxAIExtractor(sdk, fallback)
    doc = Document.model_validate(RECORDINGS[0]["document"])
    sdk.ai.create_ai_extract_structured.side_effect = BoxAPIError(
        message="temporary", request_info=Mock(), response_info=Mock(status_code=500)
    )
    provider.extract(doc, [])
    fallback.extract.assert_called_once_with(doc, [])
    fallback.reset_mock()
    sdk.ai.create_ai_extract_structured.side_effect = None
    sdk.ai.create_ai_extract_structured.return_value.answer.to_dict.return_value = {"wrong": []}
    with pytest.raises(ValueError):
        provider.extract(doc, [])
    fallback.extract.assert_not_called()


def test_glm_regional_fallback_uses_pinned_model_and_complete_json():
    runtime = Mock(meta=SimpleNamespace(region_name="us-east-2"))
    runtime.converse.return_value = {
        "stopReason": "end_turn",
        "output": {"message": {"content": [{"text": json.dumps(RECORDINGS[0]["answer"])}]}},
    }
    provider = GLMExtractor(runtime)
    doc = Document.model_validate(RECORDINGS[0]["document"])
    assert provider.extract(doc, [])[1] == "bedrock/zai.glm-5"
    assert runtime.converse.call_args.kwargs["modelId"] == "zai.glm-5"
    assert runtime.converse.call_args.kwargs["inferenceConfig"]["maxTokens"] == 4096
    runtime.converse.return_value["stopReason"] = "max_tokens"
    with pytest.raises(ValueError, match="Incomplete"):
        provider.extract(doc, [])
    with pytest.raises(ValueError, match="Region"):
        GLMExtractor(Mock(meta=SimpleNamespace(region_name="us-west-2")))


def test_live_ledger_reserves_before_create_and_resolves_last(tmp_path):
    ledger = LiveLedger(tmp_path / "ledger.json")
    ledger.reserve("folder", "unique-name")
    assert json.loads(ledger.path.read_text())["folder"]["state"] == "pending"
    ledger.observed("folder", "123")
    assert json.loads(ledger.path.read_text())["folder"]["resource_id"] is None
    ledger.resolve("folder", "123")
    assert json.loads(ledger.path.read_text())["folder"]["state"] == "resolved"
    with pytest.raises(ValueError, match="Existing"):
        LiveLedger(ledger.path)


def test_restored_same_version_proposes_reinstatement(repository):
    service, _ = one_service(repository)
    service.process("f", "v1")
    identity = service.snapshot().items[0].id
    service.retire("f")
    service.decide(service.reviews()[0].id, "approve", actor="tester")
    assert not service.snapshot().items
    assert service.process("f", "v1") == 1
    review = service.reviews()[0]
    assert review.item_id == identity and review.reasons == ["source_restored"]
    service.decide(review.id, "approve", actor="tester")
    assert service.snapshot().items[0].id == identity
    assert service.process("f", "v1") == 0


def test_stable_supplied_identity_survives_model_wording_changes(repository):
    service, provider = one_service(repository)
    service.process("f", "v1")
    original = service.snapshot().items[0]
    row = provider.extract.return_value[0][0].model_copy(
        update={
            "item_id": original.id,
            "subject": "Sable",
            "attribute": "upload_cap",
            "statement": "Limit is 96 GB.",
            "supporting_quote": "Limit is 96 GB.",
        }
    )
    provider.extract.return_value = ([row], "box")
    service.process("f", "v2")
    review = service.reviews()[0]
    assert review.item_id == original.id and review.attribute_id == original.attribute_id
    assert review.reasons == ["changed_value"]
    row.item_id = "foreign"
    provider.extract.return_value = ([row], "box")
    with pytest.raises(ValueError, match="identity"):
        service.process("f", "v3")


def test_explicit_retirement_notice_requires_review(repository):
    service, provider = one_service(repository)
    service.process("f", "v1")
    initial = service.snapshot()
    row = provider.extract.return_value[0][0].model_copy(
        update={
            "action": "retire",
            "statement": "Limit is retired.",
            "supporting_quote": "Limit is retired.",
        }
    )
    provider.extract.return_value = ([row], "box")
    service.box.get_document.side_effect = lambda f, v: Document(
        file_id=f, version_id=v, name="source", text="Limit is retired."
    )
    service.process("f", "v2")
    assert service.reviews()[0].reasons == ["explicit_retirement"]
    assert service.snapshot() == initial
    service.decide(service.reviews()[0].id, "approve", actor="tester")
    assert not service.snapshot().items


def test_rejected_semantics_stay_rejected_in_new_version(repository):
    service, _ = one_service(repository, mode="all")
    service.process("f", "v1")
    service.decide(service.reviews()[0].id, "reject", actor="tester")
    service.process("f", "v2")
    assert not service.reviews() and not service.snapshot().items
    assert all(r.decision == "rejected" for r in service.reviews(pending_only=False))


def test_runtime_factory_uses_ccg_and_named_items_table(monkeypatch):
    from kloop.extract import runtime
    from kloop.sync.ports import Extraction

    session, sdk = Mock(), Mock()
    session.client.return_value.meta.region_name = "us-east-2"
    monkeypatch.setenv("KLOOP_BOX_FOLDER_ID", "folder")
    monkeypatch.setenv("KLOOP_ITEMS_TABLE", "items-table")
    auth = Mock()
    monkeypatch.setattr(runtime, "token_provider", auth)
    monkeypatch.setattr(runtime, "sdk_client", Mock(return_value=sdk))
    service: Extraction = runtime.factory(session)
    assert callable(service.process) and callable(service.retire)
    assert auth.call_args.kwargs["mode"] == "ccg"
    session.resource.return_value.Table.assert_called_once_with("items-table")


def test_superseded_review_cannot_overwrite_newer_proposal(repository):
    service, provider = one_service(repository, mode="all")
    service.process("f", "v1")
    older = service.reviews()[0]
    row = provider.extract.return_value[0][0].model_copy(
        update={"statement": "Limit is 96 GB.", "supporting_quote": "Limit is 96 GB."}
    )
    provider.extract.return_value = ([row], "box")
    service.process("f", "v2")
    with pytest.raises(ValueError, match="superseded"):
        service.decide(older.id, "approve", actor="tester")
    service.decide(older.id, "reject", actor="tester")
    assert len(service.reviews()) == 1


def test_recovery_treats_subject_word_separators_equally_but_requires_value():
    from kloop.schemas import Item

    gold = json.loads(Path("pack/gold.json").read_text())[9]
    item = Item(
        attribute_id="a",
        id="i",
        kind="fact",
        subject="quartz_recovery_package",
        statement=gold["statement"],
        supporting_quote=gold["supporting_quote"],
        source_file_id="f",
        source_version_id="v",
        extractor="box",
        status="approved",
    )
    assert recovery([gold], [item])["rate"] == 1
    item.statement = "The Quartz recovery package is stored in cabinet Q-15."
    assert recovery([gold], [item])["rate"] == 0


def test_recorded_responses_match_pinned_model_and_frozen_source_text():
    responses = json.loads((FIXTURE.parent / "raw-recorded.json").read_text())
    assert len(RECORDINGS) == len(responses) == 14
    for index, (record, raw) in enumerate(zip(RECORDINGS, responses, strict=True)):
        assert raw["completion_reason"] == "done"
        assert raw["ai_agent_info"]["models"] == [{"name": BOX_MODEL, "provider": "aws"}]
        assert [r.model_dump() for r in parse_answer(raw["answer"])] == record["answer"]["items"]
        path = Path("pack/v2/documents" if index == 13 else "pack/documents")
        assert record["document"]["text"] == (path / record["document"]["name"]).read_text()


@pytest.mark.parametrize("action", ["approve", "edit"])
def test_deleted_source_blocks_initial_pending_upsert_until_reextracted(repository, action):
    service, _ = one_service(repository, mode="all")
    service.process("f", "v1")
    pending = service.reviews()[0]
    assert service.retire("f") == service.retire("f") == 0
    deleted = repository.read()
    kwargs = {"edited": pending.candidate} if action == "edit" else {}
    with pytest.raises(ValueError, match="source.*deleted"):
        service.decide(pending.id, action, actor="tester", **kwargs)
    assert repository.read() == deleted
    assert not service.snapshot().items
    assert service.process("f", "v1") == 1
    restored = next(r for r in service.reviews() if r.id != pending.id)
    service.decide(restored.id, "approve", actor="tester")
    service.decide(pending.id, "reject", actor="tester")
    assert len(service.snapshot().items) == 1
    assert service.process("f", "v1") == 0
    assert service.decide(pending.id, "reject", actor="tester").decision == "rejected"


@pytest.mark.parametrize("action", ["approve", "edit"])
def test_deleted_source_blocks_pending_new_attribute_beside_approved_item(repository, action):
    service, provider = one_service(repository)
    service.process("f", "v1")
    approved = service.snapshot()
    service.set_review_mode("all")
    row = provider.extract.return_value[0][0].model_copy(update={"attribute": "new_attribute"})
    provider.extract.return_value = ([row], "box")
    service.process("f", "v2")
    pending = service.reviews()[0]
    assert service.retire("f") == 1
    deleted = repository.read()
    kwargs = {"edited": pending.candidate} if action == "edit" else {}
    with pytest.raises(ValueError, match="source.*deleted"):
        service.decide(pending.id, action, actor="tester", **kwargs)
    assert repository.read() == deleted
    assert service.snapshot() == approved
    service.decide(pending.id, "reject", actor="tester")
    assert service.retire("f") == 0
    service.process("f", "v2")
    assert (
        next(r for r in service.reviews(pending_only=False) if r.id == pending.id).decision
        == "rejected"
    )
    assert all(r.candidate.attribute != "new_attribute" for r in service.reviews())
