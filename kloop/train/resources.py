"""Import census and ledger reconciliation: never infer ownership from model age."""


class ImportSlots:
    def __init__(self, bedrock, ledger, protected):
        self.bedrock, self.ledger, self.protected = bedrock, ledger, protected

    def census(self) -> set[str]:
        return {
            m["modelArn"]
            for p in self.bedrock.get_paginator("list_imported_models").paginate()
            for m in p["modelSummaries"]
        }

    def reserve(self, version_id: str) -> None:
        rows = self.ledger.entries()
        key = f"import:{version_id}"
        # Uncertain reservations occupy slots even before list APIs show them.
        unresolved = [r for r in rows if r["kind"] == "bedrock_import" and not r["resource_id"]]
        if any(r["key"] != key for r in unresolved):
            raise RuntimeError("Reconcile prior pending imports before training")
        models = self.census()
        protected = set(self.protected())
        owned = sorted(
            (
                r
                for r in rows
                if r["kind"] == "bedrock_import"
                and r["resource_id"] in models
                and r["resource_id"] not in protected
                and r["key"] != key
            ),
            key=lambda r: r["name"],
        )
        while len(models) >= 3 and owned:
            row = owned.pop(0)
            self.delete(row["key"])
            # Deletion is asynchronous: a fresh census is the slot authority.
            models = self.census()
        if len(models) >= 3:
            raise RuntimeError("All Bedrock import slots are occupied; POC imports are protected")
        if not any(r["key"] == key for r in rows):
            self.ledger.reserve(key, "bedrock_import", version_id)

    def create(self, version_id: str, role: str, s3_uri: str) -> str:
        key = f"import:{version_id}"
        rows = {r["key"]: r for r in self.ledger.entries()}
        if key not in rows:
            raise RuntimeError("Reserve an import slot before CreateModelImportJob")
        # The same name/token reconciles a timeout without duplicating resources.
        tags = [{"key": "deployment", "value": self.ledger.deployment}]
        response = self.bedrock.create_model_import_job(
            jobName=version_id,
            importedModelName=version_id,
            clientRequestToken=version_id,
            roleArn=role,
            modelDataSource={"s3DataSource": {"s3Uri": s3_uri}},
            jobTags=tags,
            importedModelTags=tags,
        )
        return response["jobArn"]

    def poll(self, version_id: str) -> dict:
        result = self.bedrock.get_model_import_job(jobIdentifier=version_id)
        if result["status"] == "Completed":
            # Resolve LAST, only to the imported model ARN, never the job ARN.
            self.ledger.resolve(f"import:{version_id}", result["importedModelArn"])
        return result

    def delete(self, key: str, *, attempted: bool = True) -> bool:
        row = next((r for r in self.ledger.entries() if r["key"] == key), None)
        if row is None:
            return True
        if row["deployment"] != self.ledger.deployment or row["kind"] != "bedrock_import":
            raise ValueError("Import is outside this deployment's cleanup ledger")
        arn = row["resource_id"]
        if not arn:
            if not attempted:
                self.ledger.remove(row)
                return True
            try:
                result = self.poll(row["name"])
            except self.bedrock.exceptions.ResourceNotFoundException:
                # An uncertain create could still arrive later: retain the reservation.
                raise RuntimeError("Import creation unresolved; retain ledger entry") from None
            if result["status"] == "Failed":
                self.ledger.remove(row)
                return True
            if result["status"] != "Completed":
                return False
            row = next(r for r in self.ledger.entries() if r["key"] == key)
            arn = row["resource_id"]
        if arn in set(self.protected()):
            raise ValueError("Cannot delete base or current import")
        try:
            tags = self.bedrock.list_tags_for_resource(resourceARN=arn)["tags"]
            if {t["key"]: t["value"] for t in tags}.get("deployment") != self.ledger.deployment:
                raise ValueError("Import deployment tag does not match ledger ownership")
            self.bedrock.delete_imported_model(modelIdentifier=arn)
            if arn in self.census():
                return False
        except self.bedrock.exceptions.ResourceNotFoundException:
            pass
        self.ledger.remove(row)
        return True
