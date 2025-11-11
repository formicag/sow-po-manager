"""
Pytest configuration and shared fixtures
"""

import pytest
import os
import sys
import boto3
from moto import mock_aws


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for testing"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'eu-west-1'


@pytest.fixture
def mock_s3(aws_credentials):
    """Mock S3 service"""
    with mock_aws():
        s3 = boto3.client('s3', region_name='eu-west-1')
        s3.create_bucket(
            Bucket='test-bucket',
            CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
        )
        yield s3


@pytest.fixture
def mock_dynamodb(aws_credentials):
    """Mock DynamoDB service"""
    with mock_aws():
        dynamodb = boto3.client('dynamodb', region_name='eu-west-1')

        # Create test table
        dynamodb.create_table(
            TableName='test-documents',
            KeySchema=[
                {'AttributeName': 'PK', 'KeyType': 'HASH'},
                {'AttributeName': 'SK', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'PK', 'AttributeType': 'S'},
                {'AttributeName': 'SK', 'AttributeType': 'S'},
                {'AttributeName': 'client_name', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'ClientNameIndex',
                    'KeySchema': [
                        {'AttributeName': 'client_name', 'KeyType': 'HASH'},
                        {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'}
                }
            ],
            BillingMode='PAY_PER_REQUEST'
        )

        yield dynamodb


@pytest.fixture
def mock_sqs(aws_credentials):
    """Mock SQS service"""
    with mock_aws():
        sqs = boto3.client('sqs', region_name='eu-west-1')

        # Create test queues
        sqs.create_queue(QueueName='test-queue')
        sqs.create_queue(QueueName='test-dlq')

        yield sqs


@pytest.fixture
def sample_sow_text():
    """Sample SOW document text for testing"""
    return """
    STATEMENT OF WORK

    Client: TESCO MOBILE LIMITED
    Contract Value: £44,800
    Start Date: 2025-10-01
    End Date: 2025-12-31
    Purchase Order: PO-12345

    RESOURCE RATES:
    Solution Designer: £700 per day

    This agreement is signed by both parties.

    Signature: [Signed]
    Date: 2025-10-01
    """


@pytest.fixture
def sample_extracted_data():
    """Sample extracted SOW data"""
    return {
        "client_name": "TESCO MOBILE LIMITED",
        "contract_value": 44800,
        "start_date": "2025-10-01",
        "end_date": "2025-12-31",
        "po_number": "PO-12345",
        "day_rates": [
            {"role": "Solution Designer", "rate": 700, "currency": "GBP"}
        ],
        "signatures_present": True
    }


@pytest.fixture
def sample_message():
    """Sample SQS message structure"""
    return {
        "document_id": "DOC#test123",
        "s3_bucket": "test-bucket",
        "s3_key": "uploads/DOC#test123/document.pdf",
        "timestamp": "2025-11-11T00:00:00Z",
        "uploaded_by": "test@example.com",
        "errors": []
    }
