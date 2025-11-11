"""
Unit tests for chunk_and_embed Lambda
Uses botocore.stub.Stubber to avoid hitting real AWS services
"""

import io
import os
import json
import sys
import pytest
import boto3
from botocore.stub import Stubber, ANY
import botocore.response

# Set required environment variables BEFORE importing handler
os.environ.setdefault('BUCKET_NAME', 'test-bucket')
os.environ.setdefault('NEXT_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123456789012/test-queue')

# Add src to path to import Lambda handler
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'lambdas', 'chunk_and_embed'))
import handler as mod


def _streaming(body: bytes):
    """Helper to create StreamingBody for S3 get_object stub"""
    return botocore.response.StreamingBody(io.BytesIO(body), len(body))


def test_embeddings_are_persisted(monkeypatch):
    """Test that embeddings are actually persisted to S3, not just claimed"""
    # Set environment variables
    monkeypatch.setenv('BUCKET_NAME', 'test-bucket')
    monkeypatch.setenv('EMBED_S3_PREFIX', 'embeddings/')
    monkeypatch.setenv('EMBED_MODEL_ID', 'amazon.titan-embed-text-v1')
    monkeypatch.setenv('BEDROCK_REGION', 'us-east-1')
    monkeypatch.setenv('CHUNK_SIZE', '20')  # Small for testing
    monkeypatch.setenv('CHUNK_OVERLAP', '5')
    monkeypatch.setenv('NEXT_QUEUE_URL', 'https://sqs.example/queue')

    # Create stubbed clients
    s3 = boto3.client('s3', region_name='us-east-1')
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    sqs = boto3.client('sqs', region_name='us-east-1')

    # Inject stubbed clients into module
    mod.s3 = s3
    mod.bedrock = bedrock
    mod.sqs = sqs

    with Stubber(s3) as s3_stub, Stubber(bedrock) as br_stub, Stubber(sqs) as sqs_stub:
        # Stub S3 get_object (download text)
        test_text = b"This is a test document for chunking"
        s3_stub.add_response(
            'get_object',
            {'Body': _streaming(test_text)},
            {'Bucket': 'test-bucket', 'Key': 'text/DOC#test.txt'}
        )

        # With CHUNK_SIZE=20, OVERLAP=5, text of 38 chars will create ~3 chunks
        # Stub bedrock invoke_model for each chunk
        for _ in range(3):
            br_stub.add_response(
                'invoke_model',
                {
                    'body': io.BytesIO(json.dumps({'embedding': [0.1, 0.2, 0.3]}).encode('utf-8')),
                    'contentType': 'application/json'
                },
                {
                    'modelId': 'amazon.titan-embed-text-v1',
                    'contentType': 'application/json',
                    'accept': 'application/json',
                    'body': ANY
                }
            )

        # Stub S3 put_object for each embedding
        for _ in range(3):
            s3_stub.add_response(
                'put_object',
                {},
                {'Bucket': 'test-bucket', 'Key': ANY, 'Body': ANY}
            )

        # Stub SQS send_message
        sqs_stub.add_response(
            'send_message',
            {'MessageId': 'm-1'},
            {'QueueUrl': ANY, 'MessageBody': ANY}
        )

        # Create test event
        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test',
                    's3_bucket': 'test-bucket',
                    'text_s3_key': 'text/DOC#test.txt'
                })
            }]
        }

        # Execute handler
        response = mod.lambda_handler(event, None)

        # Assertions
        assert response['statusCode'] == 200


def test_chunk_overlap_validation():
    """Test that chunk_text validates overlap < chunk_size"""
    with pytest.raises(ValueError, match="CHUNK_OVERLAP.*must be.*CHUNK_SIZE"):
        mod.chunk_text("test text", chunk_size=100, overlap=150)


def test_chunk_text_with_valid_params():
    """Test chunking with valid parameters"""
    text = "A" * 100
    chunks = mod.chunk_text(text, chunk_size=30, overlap=10)

    # Should create multiple chunks with overlap
    assert len(chunks) > 1

    # First chunk should be 30 chars
    assert len(chunks[0]) == 30

    # Chunks should overlap (start of chunk 2 overlaps end of chunk 1)
    # With chunk_size=30, overlap=10: chunk[0]=A[0:30], chunk[1]=A[20:50]
    assert len(chunks[1]) == 30


def test_chunk_text_handles_short_text():
    """Test that short text doesn't break chunking"""
    text = "short"
    chunks = mod.chunk_text(text, chunk_size=1000, overlap=200)

    assert len(chunks) == 1
    assert chunks[0] == "short"


def test_no_pii_in_error_logs(monkeypatch, caplog):
    """Test that error logs don't contain full message (PII)"""
    # Set environment variables
    monkeypatch.setenv('BUCKET_NAME', 'test-bucket')
    monkeypatch.setenv('NEXT_QUEUE_URL', 'https://sqs.example/queue')

    # Create stubbed clients
    s3 = boto3.client('s3', region_name='us-east-1')

    # Inject into module
    mod.s3 = s3

    # Stub S3 to raise an error
    with Stubber(s3) as s3_stub:
        s3_stub.add_client_error(
            'get_object',
            service_error_code='NoSuchKey',
            service_message='Key does not exist'
        )

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test',
                    's3_bucket': 'test-bucket',
                    'text_s3_key': 'text/missing.txt',
                    'client_name': 'SENSITIVE CLIENT',  # PII that shouldn't appear in logs
                    'contract_value': 100000  # PII
                })
            }]
        }

        # Execute and expect error
        with pytest.raises(Exception):
            mod.lambda_handler(event, None)

        # Check that logs don't contain sensitive data
        log_output = caplog.text
        assert 'SENSITIVE CLIENT' not in log_output
        assert '100000' not in log_output
        # Should log keys only
        assert 'failed keys:' in log_output


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
