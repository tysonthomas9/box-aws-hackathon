import boto3
import pytest
from moto import mock_aws

from kloop.adapters.aws import DynamoStorage, S3Artifacts
from kloop.adapters.memory import MemoryArtifacts, MemoryStorage


@pytest.fixture
def aws_session():
    with mock_aws():
        yield boto3.Session(
            aws_access_key_id="testing", aws_secret_access_key="testing", region_name="us-east-2"
        )


@pytest.fixture(params=["memory", "dynamodb"])
def storage(request, aws_session):
    if request.param == "memory":
        return MemoryStorage()
    table = aws_session.resource("dynamodb").create_table(
        TableName="contract-test",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"} for key in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )
    return DynamoStorage(table)


@pytest.fixture(params=["memory", "s3"])
def artifacts(request, aws_session):
    if request.param == "memory":
        return MemoryArtifacts()
    client = aws_session.client("s3")
    client.create_bucket(
        Bucket="contract-artifacts", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
    )
    return S3Artifacts(client, "contract-artifacts")
