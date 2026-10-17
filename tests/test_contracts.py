import pytest


def test_storage_round_trip_and_isolation(storage):
    value = {"score": 0.75, "nested": [True, None, {"text": "Halvard — 雪"}]}
    storage.put("items", "a", value)
    value["nested"].append("changed")
    result = storage.get("items", "a")
    assert result == {"score": 0.75, "nested": [True, None, {"text": "Halvard — 雪"}]}
    result["nested"].append("also changed")
    assert len(storage.get("items", "a")["nested"]) == 3
    storage.put("versions", "a", {"other": True})
    assert storage.get("versions", "a") == {"other": True}
    assert storage.get("missing", "a") is None


def test_storage_order_replace_delete(storage):
    storage.put("items", "b", {"id": "b"})
    storage.put("items", "a", {"id": "old"})
    storage.put("items", "a", {"id": "a"})
    storage.put("other", "c", {"id": "c"})
    assert storage.list("items") == [{"id": "a"}, {"id": "b"}]
    records = storage.list("items")
    records[0]["id"] = "changed"
    assert storage.get("items", "a") == {"id": "a"}
    storage.delete("items", "a")
    storage.delete("items", "a")
    assert storage.get("items", "a") is None
    assert storage.list("items") == [{"id": "b"}]
    assert storage.list("missing") == []


def test_storage_pagination(storage):
    # Cross DynamoDB's 1 MB query boundary to detect silently truncated listings.
    for number in range(8):
        storage.put("large", str(number), {"id": number, "text": "x" * 150_000})
    assert [value["id"] for value in storage.list("large")] == list(range(8))


def test_artifacts_contract(artifacts):
    with pytest.raises(KeyError):
        artifacts.get("missing")
    artifacts.put("report.json", b'\x00{"score": 0.5}', "application/json")
    assert artifacts.get("report.json") == b'\x00{"score": 0.5}'
    artifacts.put("report.json", b"updated")
    assert artifacts.get("report.json") == b"updated"
    artifacts.delete("report.json")
    artifacts.delete("report.json")
    with pytest.raises(KeyError):
        artifacts.get("report.json")
