"""Medical seals fail closed; isolated auditors never return held-out content."""

import json
import shutil
from collections import Counter

import pytest

from kloop.adapters.memory import MemoryArtifacts, MemoryStorage
from kloop.answer import SYSTEM_PROMPT
from kloop.eval import Bindings, ReportWriter, promotion_gate
from kloop.eval.build_medical import SIZES, inputs
from kloop.eval.datasets import digest, encoded, lexical_audit, load_dev, load_dev_for_hash
from kloop.eval.medical import ROOT, audit_training, category_counts, load_medical, seal
from kloop.eval.runtime import AuditVerifier
from kloop.schemas import EvalReport, EvalResult


def test_medical_sizes_sources_criteria_and_document_cap():
    source, selected = inputs(ROOT)
    source = {i["id"]: i for i in source}
    selected = {i["id"] for i in selected}
    index = json.loads((ROOT / "case-index.json").read_bytes())
    inventory = {f["id"]: f for f in json.loads((ROOT / "inventory.json").read_bytes())["files"]}
    for split in ["dev", "hidden"]:
        cases = load_medical(split).cases
        assert len(cases) == (60 if split == "dev" else 150)
        assert Counter(index[c.question.id]["category"] for c in cases) == SIZES[split]
        documents = Counter()
        for c in cases:
            ids = set(c.question.source_item_ids)
            assert ids <= source.keys()
            if c.bucket:
                assert ids and ids.isdisjoint(selected)
                assert c.question.expected_answer != "I don't know"
            else:
                assert ids <= selected
            if c.question.kind in {"procedure", "two_fact", "rule_in_question"}:
                assert c.criteria
            for criterion in c.criteria:
                if c.question.kind != "rule_in_question":
                    assert any(
                        criterion.supporting_quote == source[id]["supporting_quote"]
                        for id in criterion.source_item_ids
                    )
            documents.update({source[id]["source_file_id"] for id in ids})
        if split == "hidden":
            assert max(documents.values()) <= 2
            assert len(documents) >= 75
            fact_areas = {
                inventory[source[id]["source_file_id"]]["path"].split("/")[1]
                for c in cases
                if index[c.question.id]["category"] == "fact"
                for id in c.question.source_item_ids
            }
            assert fact_areas == {
                "clinical-medical",
                "commercial-heor",
                "pharmacovigilance",
                "quality-manufacturing",
                "regulatory-affairs",
            }


def test_split_overlap_and_training_audit_is_content_free():
    dev, hidden = load_medical("dev"), load_medical("hidden")
    rows = b"".join(
        encoded(
            {
                "messages": [
                    {"role": "system", "content": ""},
                    {"role": "user", "content": c.question.question},
                ]
            }
        )
        + b"\n"
        for c in dev.cases
    )
    assert lexical_audit(rows, hidden, immutable_training_hash=digest(rows))["passed"]
    collision = encoded(
        {
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": hidden.cases[0].question.question},
            ]
        }
    )
    verdict = audit_training(collision, immutable_training_hash=digest(collision))
    assert verdict["passed"] is False
    assert verdict["splits"]["hidden"]["collisions"] >= 1
    assert hidden.cases[0].question.question not in json.dumps(verdict)
    with pytest.raises(ValueError, match="immutable training"):
        audit_training(collision, immutable_training_hash="0" * 64)


def test_medical_tampering_and_resealed_tampering_fail(tmp_path):
    shutil.copytree(ROOT, tmp_path / "medical")
    root = tmp_path / "medical"
    path = root / "sealed/hidden.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_medical("hidden", root)
    value = json.loads((root / "seal.json").read_bytes())
    value["splits"]["hidden"]["sha256"] = digest(path.read_bytes())
    (root / "seal.json").write_bytes(encoded(value))
    with pytest.raises(ValueError, match="seal hash"):
        seal(root)


def test_medical_categories_report_all_modes_and_reject_incomplete_rows():
    dataset = load_medical("dev")
    rows = [
        EvalResult(
            question_id=c.question.id,
            kind=c.question.kind,
            mode=mode,
            answer=c.question.expected_answer,
            passed=True,
            score=1,
            invented=False,
            bucket=c.bucket,
        )
        for mode in ["without", "with", "search"]
        for c in dataset.cases
    ]
    report = EvalReport(
        id="medical",
        model_version_id="test",
        split="dev",
        question_set_sha256=dataset.sha256,
        results=rows,
        scores={},
    )
    counts = category_counts(report)
    for mode in ["without", "with", "search"]:
        assert {k: v["total"] for k, v in counts[mode].items()} == SIZES["dev"]
    report.results.pop()
    with pytest.raises(ValueError, match="Incomplete"):
        category_counts(report)


def test_demo_starter_prompts_are_complete_and_copy_edit_is_explicit():
    scenarios = json.loads((ROOT.parents[1] / "pack/demo-scenarios.json").read_bytes())
    ordered = {s["id"]: s for s in scenarios["scenarios"]}
    assert scenarios["order"] == [1, 2, 4, 5, 3, 6]
    assert all(s["question"].strip() and s["expected"].strip() for s in ordered.values())
    assert all(s["source_item_ids"] for s in ordered.values() if s["id"] != 5)
    change = ordered[3]
    assert change["source_file_id"] == "2532303047465"
    assert change["edit_copy_only"] is True
    assert "27 October 2025" in change["expected_before"]
    assert "28 October 2025" in change["expected"]
    assert change["steps"]


def medical_report(passes, mode="with"):
    dataset = load_medical("dev")
    return EvalReport(
        id="medical-gate",
        model_version_id="test",
        split="dev",
        question_set_sha256=dataset.sha256,
        results=[
            EvalResult(
                question_id=c.question.id,
                kind=c.question.kind,
                mode=mode,
                answer="test",
                passed=i in passes,
                score=int(i in passes),
                bucket=c.bucket,
            )
            for i, c in enumerate(dataset.cases)
        ],
        scores={},
    )


def test_gate_allowlist_accepts_medical_and_rejects_unknown_partial_or_wrong_kind():
    dataset = load_medical("dev")
    assert load_dev_for_hash(dataset.sha256) == dataset
    historical = load_dev()
    assert load_dev_for_hash(historical.sha256) == historical
    with pytest.raises(ValueError, match="Unknown frozen dev"):
        load_dev_for_hash("a" * 64)
    before, after = medical_report(set()), medical_report({0})
    assert promotion_gate(before, after, report_uri="r").passed
    wrong = after.model_copy(deep=True)
    wrong.results[0].kind = "unrelated"
    with pytest.raises(ValueError, match="kinds differ"):
        promotion_gate(before, wrong, report_uri="r")
    after.results.pop()
    with pytest.raises(ValueError):
        promotion_gate(before, after, report_uri="r")


def test_runtime_audits_medical_rows_against_s3_hidden_before_training():
    artifacts = MemoryArtifacts()
    for name in ["seal.json", "sealed/hidden.jsonl"]:
        artifacts.put("sealed/medical/" + name, (ROOT / name).read_bytes())
    training = encoded({"messages": [{"content": ""}, {"content": "abcdefgh xyzzy mnemotechnic"}]})
    snapshot = seal()["training_snapshot_sha256"]

    def publish(body):
        manifest = dict(
            snapshot_hash=snapshot,
            dev_set_hash=load_medical("dev").sha256,
            system_prompt_sha256=digest(SYSTEM_PROMPT.encode()),
            train_sha256=digest(body),
        )
        manifest_bytes = encoded(manifest)
        sha = digest(manifest_bytes)
        artifacts.put(f"training/data/{sha}/manifest.json", manifest_bytes)
        artifacts.put(f"training/data/{sha}/train.jsonl", body)
        return sha

    audit_sha = AuditVerifier(artifacts).verify(publish(training), snapshot)
    verdict = json.loads(artifacts.get(f"evaluations/audits/{audit_sha}.json"))
    assert verdict["passed"] and set(verdict["splits"]) == {"dev", "hidden"}
    hidden_text = load_medical("hidden").cases[0].question.question
    collision = encoded({"messages": [{"content": ""}, {"content": hidden_text}]})
    with pytest.raises(ValueError, match="sealed lexical overlap"):
        AuditVerifier(artifacts).verify(publish(collision), snapshot)


def test_persisted_medical_summary_includes_all_categories_without_hidden_text():
    report = medical_report(set())
    artifacts, storage, copied = MemoryArtifacts(), MemoryStorage(), []
    bindings = Bindings(
        corpus_sha256="a" * 64,
        audit_sha256="b" * 64,
        manifest_sha256="c" * 64,
        model_arns={"with": "test"},
        serving_version="test",
    )
    writer = ReportWriter(artifacts, storage, lambda name, body: copied.append(json.loads(body)))
    writer.save(report, bindings)
    assert {k: v["total"] for k, v in copied[0]["medical_counts"]["with"].items()} == SIZES["dev"]
    assert "results" not in copied[0]
    assert not any("46+6" in c for c in copied[0]["caveats"])
