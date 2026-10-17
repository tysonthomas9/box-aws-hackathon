import io
import json
from pathlib import Path

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from kloop.answer import SYSTEM_PROMPT, Answerer, ModelWarming, retrieve
from kloop.answer.bedrock import ImportedModelClient
from kloop.schemas import Document

BASE = "arn:aws:bedrock:us-east-2:123456789012:imported-model/aaaaaaaaaaaa"
TRAINED = "arn:aws:bedrock:us-east-2:123456789012:imported-model/bbbbbbbbbbbb"


def doc(id, text):
    return Document(file_id=id, version_id="v7", name=f"{id}.txt", text=text)


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def invoke(self, model_id, payload):
        self.calls.append((model_id, payload))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class Time:
    now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_modes_pin_model_and_use_training_prompt_and_fixed_template():
    model = Model([{"generation": "Mira (Source: kestrel.txt)"}] * 2)
    answerer = Answerer(model)
    for method, arn in ((answerer.answer_without, BASE), (answerer.answer_with, TRAINED)):
        result = method("Who owns Kestrel?", arn)
        assert result.model_arn == arn
        assert result.answer == "Mira (Source: kestrel.txt)"
        assert result.latency_ms >= 0
        assert result.citations == []
    assert [call[0] for call in model.calls] == [BASE, TRAINED]
    assert model.calls[0][1] == {
        "prompt": f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\nWho owns Kestrel?<|im_end|>\n<|im_start|>assistant\n",
        "max_gen_len": 256,
        "temperature": 0,
    }
    pack = json.loads(Path("poc/company-knowledge/pack.json").read_text())
    assert SYSTEM_PROMPT == pack["system_prompt"]


def test_search_returns_only_referenced_retrieved_sources_with_exact_offsets():
    documents = [doc("b", "The Kestrel owner is Mira."), doc("a", "The pump pressure is low.")]
    model = Model([{"generation": "Mira [1]. Invented [99]."}])
    result = Answerer(model).answer_search("Kestrel owner", BASE, documents)
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert (citation.file_id, citation.version_id) == ("b", "v7")
    assert citation.quote == documents[0].text[citation.start : citation.end]
    assert citation.label == "1"
    assert "Mira" in model.calls[0][1]["prompt"]
    assert "pump" not in model.calls[0][1]["prompt"]


def test_bm25_term_frequency_length_normalization_and_deterministic_ties():
    docs = [doc("b", "kestrel"), doc("a", "kestrel"), doc("c", "kestrel " + "other " * 30)]
    assert [c.file_id for c in retrieve("kestrel", docs)] == ["a", "b", "c"]
    assert [c.file_id for c in retrieve("kestrel", list(reversed(docs)), 1)] == ["a"]
    assert retrieve("no match", docs) == []
    assert retrieve("", docs) == []
    assert retrieve("kestrel", []) == []
    assert retrieve("kestrel", [doc("p", "!!!")]) == []
    with pytest.raises(ValueError):
        retrieve("kestrel", docs, 0)


def test_chunking_preserves_exact_text_and_retrieves_later_chunk():
    text = " \n" + "prefix " * 190 + "Kestrel Mira owner" + " tail" * 190
    document = doc("long", text)
    citations = retrieve("Kestrel Mira", [document], 1)
    assert len(citations) == 1
    assert citations[0].start > 0
    assert citations[0].quote == text[citations[0].start : citations[0].end]
    assert "Kestrel Mira" in citations[0].quote


def test_no_match_and_uncited_answers_do_not_invent_citations():
    model = Model([{"generation": "Unknown [1]"}, {"generation": "Mira"}])
    answerer = Answerer(model)
    assert answerer.answer_search("unrelated", BASE, [doc("a", "kestrel")]).citations == []
    assert "Available reference documents" not in model.calls[0][1]["prompt"]
    assert answerer.answer_search("kestrel", BASE, [doc("a", "kestrel")]).citations == []


def test_cold_start_retry_status_latency_and_warm_up():
    timer = Time()
    statuses = []
    model = Model([ModelWarming(), ModelWarming(), {"generation": "READY"}])
    answerer = Answerer(model, clock=timer.clock, sleep=timer.sleep, on_status=statuses.append)
    result = answerer.warm_up(BASE)
    assert result.answer == "READY"
    assert result.latency_ms == 6000
    assert statuses == ["warming", "warming"]
    assert len(model.calls) == 3
    assert model.calls[0][1]["max_gen_len"] == 16
    assert all(call == model.calls[0] for call in model.calls)


def test_cold_start_budget_is_bounded_and_other_errors_propagate():
    timer = Time()
    model = Model([ModelWarming()] * 100)
    answerer = Answerer(model, clock=timer.clock, sleep=timer.sleep)
    with pytest.raises(ModelWarming):
        answerer.answer_without("question", BASE)
    assert timer.now == 240
    assert len(model.calls) < 20
    denied = PermissionError("denied")
    with pytest.raises(PermissionError) as error:
        Answerer(Model([denied])).answer_without("question", BASE)
    assert error.value is denied


@pytest.mark.parametrize("generation", [None, 7, "", "  "])
def test_malformed_response_fails_visibly(generation):
    with pytest.raises(ValueError, match="generation"):
        Answerer(Model([{"generation": generation}])).answer_without("question", BASE)


@pytest.mark.parametrize("arn", ["", BASE.replace("us-east-2", "us-east-1"), "model-id"])
def test_reject_wrong_region_and_unpinned_model(arn):
    model = Model([])
    with pytest.raises(ValueError, match="ARN"):
        Answerer(model).answer_without("question", arn)
    assert model.calls == []


def test_empty_question_and_invalid_retry_budget():
    with pytest.raises(ValueError, match="question"):
        Answerer(Model([])).answer_with("  ", TRAINED)
    for budget in (-1, 241, float("nan")):
        with pytest.raises(ValueError):
            Answerer(Model([]), retry_seconds=budget)


def test_live_adapter_maps_only_model_not_ready_and_closes_body():
    runtime = boto3.client(
        "bedrock-runtime",
        region_name="us-east-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    adapter = ImportedModelClient(runtime)
    stream = io.BytesIO(b'{"generation":"READY"}')
    with Stubber(runtime) as stub:
        stub.add_client_error("invoke_model", "ModelNotReadyException")
        stub.add_client_error("invoke_model", "AccessDeniedException")
        stub.add_response(
            "invoke_model",
            {
                "body": StreamingBody(stream, len(stream.getvalue())),
                "contentType": "application/json",
            },
            {
                "modelId": BASE,
                "body": '{"prompt": "test"}',
                "contentType": "application/json",
                "accept": "application/json",
            },
        )
        with pytest.raises(ModelWarming):
            adapter.invoke(BASE, {"prompt": "test"})
        with pytest.raises(runtime.exceptions.AccessDeniedException):
            adapter.invoke(BASE, {"prompt": "test"})
        assert adapter.invoke(BASE, {"prompt": "test"}) == {"generation": "READY"}
        assert stream.closed
        stub.assert_no_pending_responses()


def test_live_adapter_rejects_other_region():
    runtime = boto3.client(
        "bedrock-runtime",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with pytest.raises(ValueError, match="Region"):
        ImportedModelClient(runtime)
