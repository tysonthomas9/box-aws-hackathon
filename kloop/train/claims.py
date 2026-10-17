"""Generation-scoped question ownership prevents duplicates between batches."""

from kloop.train.data import normalized, sha256


def claim_question(table, generation, batch, question):
    try:
        table.put_item(
            Item={
                "pk": f"training_helper_questions:{generation}",
                "sk": sha256(normalized(question).encode()),
                "batch": batch,
            },
            ConditionExpression="attribute_not_exists(pk) OR #batch = :batch",
            ExpressionAttributeNames={"#batch": "batch"},
            ExpressionAttributeValues={":batch": batch},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True
