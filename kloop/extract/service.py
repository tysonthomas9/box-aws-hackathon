"""Atomic, replay-safe extraction and human review, separate from effective items."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal

from kloop.extract.hashing import digest
from kloop.extract.repository import Repository
from kloop.ports import BoxClient
from kloop.schemas import ApprovedSnapshot, ExtractionRow, Item, Review


def normalized(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").split())


def content(row: ExtractionRow) -> dict:
    return row.model_dump(exclude={"supporting_quote", "item_id"})


class ExtractionService:
    def __init__(
        self,
        box: BoxClient,
        extractor,
        repository: Repository,
        review_mode: Literal["off", "exceptions", "all"] = "exceptions",
    ):
        if review_mode not in {"off", "exceptions", "all"}:
            raise ValueError("Unknown review mode")
        self.box, self.extractor, self.repository = box, extractor, repository
        self.review_mode = review_mode

    @staticmethod
    def _identity(file_id: str, row: ExtractionRow, state: dict | None = None) -> tuple[str, str]:
        if row.item_id:
            known = [
                r
                for r in (state or {}).get("reviews", {}).values()
                if r["item_id"] == row.item_id
                and r["source_file_id"] == file_id
                and r["candidate"]["kind"] == row.kind
            ]
            if not known:
                raise ValueError("Extraction references an unknown or foreign item identity")
            return row.item_id, known[0]["attribute_id"]
        attribute = digest([row.kind, normalized(row.subject), normalized(row.attribute)])
        return digest([file_id, attribute]), attribute

    @staticmethod
    def _apply(state: dict, review: Review) -> None:
        if review.decision not in {"approved", "edited"}:
            return
        current = state["items"].get(review.item_id)
        if review.candidate.action == "retire":
            if current:
                state["items"][review.item_id] = {**current, "status": "retired"}
            return
        row = review.candidate
        item = Item(
            id=review.item_id,
            attribute_id=review.attribute_id,
            kind=row.kind,
            subject=row.subject,
            statement=row.statement,
            trigger_conditions=row.trigger_conditions,
            steps=row.steps,
            supporting_quote=row.supporting_quote,
            source_file_id=review.source_file_id,
            source_version_id=review.source_version_id,
            extractor=review.extractor,
            status="approved",
        )
        state["items"][item.id] = item.model_dump(mode="json")

    def _propose(self, state, file_id, version_id, row, extractor, text=None, epoch=0) -> bool:
        item_id, attribute_id = self._identity(file_id, row, state)
        review_id = digest([item_id, version_id, row.model_dump(), extractor, epoch])
        if review_id in state["reviews"]:
            return False
        current = state["items"].get(item_id)
        reasons = []
        invalid = []
        for key in ("subject", "statement", "supporting_quote"):
            if not getattr(row, key).strip():
                invalid.append(f"missing_{key}")
        if text is not None and (not row.supporting_quote or row.supporting_quote not in text):
            invalid.append("quote_not_in_source")
        if row.kind == "procedure" and (not row.steps or not row.trigger_conditions):
            invalid.append("missing_procedure_fields")
        if row.action == "retire":
            reasons.append("source_deleted" if text is None else "explicit_retirement")
            if current is None:
                invalid.append("unknown_retirement")
        elif current and current["status"] == "retired":
            reasons.append("source_restored")
        elif (
            current
            and current["status"] == "approved"
            and (
                current["statement"] != row.statement
                or current["steps"] != row.steps
                or current["trigger_conditions"] != row.trigger_conditions
            )
        ):
            reasons.append("changed_value")
        for other_id, other in state["items"].items():
            if other_id == item_id or other["status"] != "approved":
                continue
            if other["attribute_id"] == attribute_id:
                reasons.append("duplicate" if other["statement"] == row.statement else "conflict")
        mode = state.get("review_mode", self.review_mode)
        if mode == "all":
            reasons.append("review_all")
        reasons = sorted(set(reasons + invalid))
        rejected = any(
            old["item_id"] == item_id
            and old["decision"] == "rejected"
            and content(ExtractionRow.model_validate(old["candidate"])) == content(row)
            for old in state["reviews"].values()
        )
        auto = not invalid and (not reasons or mode == "off")
        review = Review(
            id=review_id,
            item_id=item_id,
            attribute_id=attribute_id,
            source_file_id=file_id,
            source_version_id=version_id,
            extractor=extractor,
            candidate=row,
            reasons=reasons,
            decision="rejected" if rejected else "approved" if auto else "pending",
            decided_by="automatic_checks" if auto and not rejected else None,
        )
        state["reviews"][review_id] = review.model_dump(mode="json")
        self._apply(state, review)
        return True

    def process(self, file_id: str, version_id: str) -> int:
        before = self.repository.read()
        source = before.get("sources", {}).get(file_id, {"epoch": 0, "deleted": False})
        epoch = source["epoch"] + int(source["deleted"])
        batch_id = digest(["process", file_id, version_id, epoch])
        if batch_id in before["batches"]:
            return 0
        document = self.box.get_document(file_id, version_id)
        if (document.file_id, document.version_id) != (file_id, version_id):
            raise ValueError("Box returned a different source version")
        identities = [
            {
                "item_id": r["item_id"],
                "subject": r["candidate"]["subject"],
                "attribute": r["candidate"]["attribute"],
            }
            for r in before["reviews"].values()
            if r["source_file_id"] == file_id
        ]
        rows, extractor = self.extractor.extract(document, identities)
        after = deepcopy(before)
        changes = 0
        seen = set()
        for row in rows:
            # Identical model rows are one proposal. Conflicting rows for a single
            # identity fail closed instead of auto-approving whichever came first.
            identity = self._identity(file_id, row, after)[0]
            fingerprint = digest(row.model_dump())
            if (identity, fingerprint) in seen:
                continue
            if any(key == identity for key, _ in seen):
                raise ValueError("Conflicting extraction rows for one identity")
            seen.add((identity, fingerprint))
            changes += self._propose(
                after, file_id, version_id, row, extractor, document.text, epoch
            )
        after["batches"][batch_id] = {"file_id": file_id, "version_id": version_id}
        after.setdefault("sources", {})[file_id] = {"epoch": epoch, "deleted": False}
        self.repository.commit(before, after)
        return changes

    def retire(self, file_id: str) -> int:
        before = self.repository.read()
        after = deepcopy(before)
        changes = 0
        source = before.get("sources", {}).get(file_id, {"epoch": 0, "deleted": False})
        epoch = source["epoch"] + int(not source["deleted"])
        for item in before["items"].values():
            if item["source_file_id"] != file_id or item["status"] != "approved":
                continue
            # Recover the stable attribute label from its original proposal.
            prior = next(r for r in before["reviews"].values() if r["item_id"] == item["id"])
            row = ExtractionRow.model_validate(prior["candidate"]).model_copy(
                update={
                    "action": "retire",
                    "statement": item["statement"],
                    "supporting_quote": item["supporting_quote"],
                    "trigger_conditions": item["trigger_conditions"],
                    "steps": item["steps"],
                }
            )
            changes += self._propose(
                after, file_id, item["source_version_id"], row, "source-deletion", epoch=epoch
            )
        if changes or not source["deleted"]:
            after.setdefault("sources", {})[file_id] = {"epoch": epoch, "deleted": True}
            self.repository.commit(before, after)
        return changes

    def get_review_mode(self) -> str:
        return self.repository.read().get("review_mode", self.review_mode)

    def set_review_mode(self, mode: Literal["off", "exceptions", "all"]) -> None:
        if mode not in {"off", "exceptions", "all"}:
            raise ValueError("Unknown review mode")
        before = self.repository.read()
        if before.get("review_mode", self.review_mode) == mode:
            return
        after = deepcopy(before)
        after["review_mode"] = mode
        self.repository.commit(before, after)

    def reviews(self, *, pending_only: bool = True) -> list[Review]:
        return [
            Review.model_validate(r)
            for r in self.repository.read()["reviews"].values()
            if not pending_only or r["decision"] == "pending"
        ]

    def decide(
        self,
        review_id: str,
        action: Literal["approve", "edit", "reject"],
        *,
        actor: str,
        edited: ExtractionRow | None = None,
    ) -> Review:
        if not actor.strip() or action not in {"approve", "edit", "reject"}:
            raise ValueError("A valid action and reviewer are required")
        before = self.repository.read()
        review = Review.model_validate(before["reviews"][review_id])
        target = {"approve": "approved", "edit": "edited", "reject": "rejected"}[action]
        if review.decision != "pending":
            if review.decision == target and (edited is None or edited == review.candidate):
                return review
            raise ValueError("Review already decided")
        # A superseded version must be re-extracted, not approved over newer knowledge.
        versions = [r for r in before["reviews"].values() if r["item_id"] == review.item_id]
        if action != "reject" and versions[-1]["id"] != review.id:
            raise ValueError("Review has been superseded by a newer source version")
        if action == "edit":
            if (
                edited is None
                or self._identity(review.source_file_id, edited, before)
                != (review.item_id, review.attribute_id)
                or edited.action != review.candidate.action
            ):
                raise ValueError("Edits must retain the item identity and action")
            review.candidate = edited
        elif edited is not None:
            raise ValueError("Only edit accepts an edited candidate")
        # Source text checks already appear in the review; a human may explicitly
        # approve a flagged proposal. Item validation still rejects missing fields.
        review.decision, review.decided_by = target, actor
        review.decided_at = datetime.now(UTC).isoformat()
        after = deepcopy(before)
        self._apply(after, review)
        after["reviews"][review_id] = review.model_dump(mode="json")
        self.repository.commit(before, after)
        return review

    def snapshot(self) -> ApprovedSnapshot:
        items = [
            Item.model_validate(v)
            for _, v in sorted(self.repository.read()["items"].items())
            if v["status"] == "approved"
        ]
        value = [item.model_dump(mode="json") for item in items]
        snapshot = ApprovedSnapshot(sha256=digest(value), items=items)
        self.repository.save_snapshot(snapshot.model_dump(mode="json"))
        return snapshot
