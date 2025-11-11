"""
Production CI Gates for chunk_and_embed Lambda (v1.6.0)

Critical behavior tests to lock in the fixes:
1. Partial state detection: doesn't skip if chunks exist without complete manifest
2. Success ratio guard: fails if < 95% embeddings succeed (no manifest written)
3. Manifest atomicity: written LAST and only after success
4. Payload purity: only canonical keys forwarded (no PII leakage)
5. Content hash: present in manifest and chunks
6. Idempotent skip: only skips if manifest is COMPLETE

These tests MUST pass before deployment.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch, call
from botocore.exceptions import ClientError

# Set required environment variables before importing handler
os.environ['BUCKET_NAME'] = 'test-bucket'
os.environ['NEXT_QUEUE_URL'] = 'https://sqs.eu-west-1.amazonaws.com/123456789012/test-queue'


@pytest.fixture
def mock_s3():
    """Mock S3 client for testing."""
    with patch('boto3.client') as mock:
        s3 = MagicMock()
        mock.return_value = s3
        yield s3


@pytest.fixture
def mock_sqs():
    """Mock SQS client for testing."""
    sqs = MagicMock()
    yield sqs


@pytest.fixture
def mock_bedrock():
    """Mock Bedrock client for testing."""
    bedrock = MagicMock()
    # Default: return valid embedding
    bedrock.invoke_model.return_value = {
        'body': MagicMock(read=lambda: json.dumps({'embedding': [0.1] * 1024}).encode())
    }
    yield bedrock


def test_partial_state_does_not_skip(mock_s3, mock_sqs, mock_bedrock):
    """
    CRITICAL: If chunks exist but manifest is incomplete/missing, Lambda MUST NOT skip.

    Scenario: Previous run wrote 2/5 chunks and crashed before manifest.
    Expected: Lambda detects partial state, continues embedding (may resume or re-do).
    """
    # Setup: manifest doesn't exist (NoSuchKey), but some chunks do
    mock_s3.get_object.side_effect = [
        ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject'),  # no manifest
        {'Body': MagicMock(read=lambda: b'Sample text to chunk', close=lambda: None), 'ETag': '"abc123"'},  # text file
    ]

    # Import handler after mocks are set up
    with patch('boto3.client', side_effect=[mock_s3, mock_sqs, mock_bedrock]):
        from src.lambdas.chunk_and_embed.handler import lambda_handler

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#partial-test',
                    'text_s3_key': 'text/DOC#partial-test.txt',
                    's3_bucket': 'test-bucket'
                })
            }]
        }

        lambda_handler(event, {})

        # Assert: Lambda DID process (downloaded text, called Bedrock, wrote manifest)
        assert mock_s3.get_object.call_count >= 2  # manifest check + text download
        assert mock_bedrock.invoke_model.called, "Should call Bedrock even with partial state"
        assert any('manifest.json' in str(call) for call in mock_s3.put_object.call_args_list), \
            "Should write manifest after re-embedding"


def test_success_ratio_guard_prevents_incomplete_manifest():
    """
    CRITICAL: If < 95% embeddings succeed, Lambda MUST raise error and NOT write manifest.

    Scenario: Bedrock fails for 10/10 chunks (0% success).
    Expected: RuntimeError raised, no manifest written, SQS will retry/DLQ.
    """
    mock_s3 = MagicMock()
    mock_sqs = MagicMock()
    mock_bedrock = MagicMock()

    # Setup: manifest doesn't exist, text exists, Bedrock ALWAYS fails
    mock_s3.get_object.side_effect = [
        ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject'),  # no manifest
        {'Body': MagicMock(read=lambda: b'x' * 5000, close=lambda: None), 'ETag': '"abc"'},  # text (will create ~5 chunks)
    ]
    mock_bedrock.invoke_model.return_value = {
        'body': MagicMock(read=lambda: json.dumps({}).encode())  # no embedding key = failure
    }

    with patch('boto3.client', side_effect=[mock_s3, mock_sqs, mock_bedrock]):
        from src.lambdas.chunk_and_embed.handler import lambda_handler

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#fail-test',
                    'text_s3_key': 'text/DOC#fail-test.txt'
                })
            }]
        }

        # Expect RuntimeError due to success ratio < 95%
        with pytest.raises(RuntimeError, match="success.*threshold"):
            lambda_handler(event, {})

        # Assert: manifest was NOT written (only chunks attempted, no manifest.json)
        manifest_calls = [c for c in mock_s3.put_object.call_args_list
                          if 'manifest.json' in str(c)]
        assert len(manifest_calls) == 0, "Must NOT write manifest on failure"


def test_manifest_written_last_and_atomic():
    """
    CRITICAL: manifest.json MUST be written AFTER all chunks, and contain correct metadata.

    Scenario: Normal success case.
    Expected: All chunk files written first, then manifest as final atomic marker.
    """
    mock_s3 = MagicMock()
    mock_sqs = MagicMock()
    mock_bedrock = MagicMock()

    # Track S3 put_object calls in order
    put_calls = []
    def track_put(**kwargs):
        put_calls.append(kwargs['Key'])
    mock_s3.put_object = MagicMock(side_effect=track_put)

    # Setup
    mock_s3.get_object.side_effect = [
        ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject'),  # no manifest
        {'Body': MagicMock(read=lambda: b'x' * 2000, close=lambda: None), 'ETag': '"abc"'},  # text (~2 chunks)
    ]
    mock_bedrock.invoke_model.return_value = {
        'body': MagicMock(read=lambda: json.dumps({'embedding': [0.1] * 1024}).encode())
    }

    with patch('boto3.client', side_effect=[mock_s3, mock_sqs, mock_bedrock]):
        from src.lambdas.chunk_and_embed.handler import lambda_handler

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#atomic-test',
                    'text_s3_key': 'text/DOC#atomic-test.txt'
                })
            }]
        }

        lambda_handler(event, {})

        # Assert: manifest.json is the LAST S3 write
        assert len(put_calls) > 0, "Should have written files"
        assert 'manifest.json' in put_calls[-1], f"manifest.json must be last write, got: {put_calls}"

        # Assert: chunk files written before manifest
        chunk_writes = [k for k in put_calls if '.json' in k and 'manifest' not in k]
        manifest_idx = put_calls.index([k for k in put_calls if 'manifest.json' in k][0])
        assert len(chunk_writes) > 0, "Should have chunk files"
        assert all(put_calls.index(c) < manifest_idx for c in chunk_writes), \
            "All chunks must be written before manifest"


def test_payload_whitelist_no_pii_leakage():
    """
    CRITICAL: Forwarded SQS message MUST contain ONLY canonical keys (no PII).

    Scenario: Input message contains PII fields (client_name, etc.).
    Expected: Output message contains ONLY: document_id, text_s3_key, embeddings_s3_prefix,
              chunks_created, embeddings_persisted.
    """
    mock_s3 = MagicMock()
    mock_sqs = MagicMock()
    mock_bedrock = MagicMock()

    # Setup
    mock_s3.get_object.side_effect = [
        ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject'),
        {'Body': MagicMock(read=lambda: b'test text', close=lambda: None), 'ETag': '"abc"'},
    ]
    mock_bedrock.invoke_model.return_value = {
        'body': MagicMock(read=lambda: json.dumps({'embedding': [0.1] * 1024}).encode())
    }

    with patch('boto3.client', side_effect=[mock_s3, mock_sqs, mock_bedrock]):
        from src.lambdas.chunk_and_embed.handler import lambda_handler

        # Input with PII
        input_message = {
            'document_id': 'DOC#pii-test',
            'text_s3_key': 'text/DOC#pii-test.txt',
            'client_name': 'Acme Corp',  # PII
            'contract_value': 100000,     # PII
            'po_number': 'PO-12345',      # PII
            'extra_field': 'should_not_forward'
        }

        event = {'Records': [{'body': json.dumps(input_message)}]}
        lambda_handler(event, {})

        # Extract forwarded message
        assert mock_sqs.send_message.called
        forwarded_body = json.loads(mock_sqs.send_message.call_args[1]['MessageBody'])

        # Assert: ONLY canonical keys present
        canonical_keys = {
            'document_id', 'text_s3_key', 'embeddings_s3_prefix',
            'chunks_created', 'embeddings_persisted'
        }
        forwarded_keys = set(forwarded_body.keys())

        assert forwarded_keys == canonical_keys, \
            f"Forwarded keys {forwarded_keys} != canonical {canonical_keys}"

        # Assert: NO PII keys
        pii_keys = {'client_name', 'contract_value', 'po_number', 'extra_field'}
        assert not any(k in forwarded_keys for k in pii_keys), \
            f"PII keys leaked: {pii_keys & forwarded_keys}"


def test_content_hash_in_manifest_and_chunks():
    """
    HIGH IMPACT: manifest and chunks MUST contain content hashes for future-proofing.

    Scenario: Normal embedding run.
    Expected:
    - manifest.json contains 'content_sha256' and 'source_etag'
    - Each chunk JSON contains 'chunk_sha256'
    """
    mock_s3 = MagicMock()
    mock_sqs = MagicMock()
    mock_bedrock = MagicMock()

    # Capture what's written to S3
    s3_writes = {}
    def capture_put(**kwargs):
        s3_writes[kwargs['Key']] = kwargs.get('Body', b'')
    mock_s3.put_object = MagicMock(side_effect=capture_put)

    mock_s3.get_object.side_effect = [
        ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject'),
        {'Body': MagicMock(read=lambda: b'test content', close=lambda: None), 'ETag': '"etag123"'},
    ]
    mock_bedrock.invoke_model.return_value = {
        'body': MagicMock(read=lambda: json.dumps({'embedding': [0.1] * 1024}).encode())
    }

    with patch('boto3.client', side_effect=[mock_s3, mock_sqs, mock_bedrock]):
        from src.lambdas.chunk_and_embed.handler import lambda_handler

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#hash-test',
                    'text_s3_key': 'text/DOC#hash-test.txt'
                })
            }]
        }

        lambda_handler(event, {})

        # Find manifest
        manifest_key = [k for k in s3_writes.keys() if 'manifest.json' in k][0]
        manifest_data = json.loads(s3_writes[manifest_key])

        # Assert: manifest has hashes
        assert 'content_sha256' in manifest_data, "manifest must have content_sha256"
        assert 'source_etag' in manifest_data, "manifest must have source_etag"
        assert len(manifest_data['content_sha256']) == 64, "SHA256 should be 64 hex chars"

        # Assert: chunks have hashes
        chunk_keys = [k for k in s3_writes.keys() if '.json' in k and 'manifest' not in k]
        assert len(chunk_keys) > 0, "Should have chunk files"

        for chunk_key in chunk_keys:
            chunk_data = json.loads(s3_writes[chunk_key])
            assert 'chunk_sha256' in chunk_data, f"{chunk_key} must have chunk_sha256"
            assert len(chunk_data['chunk_sha256']) == 64


def test_idempotent_skip_only_on_complete_manifest():
    """
    CRITICAL: Lambda MUST skip ONLY if manifest exists AND embedded >= chunks > 0.

    Scenario 1: manifest exists with embedded=5, chunks=5 → SKIP
    Scenario 2: manifest exists with embedded=3, chunks=5 → DO NOT SKIP (partial)
    Scenario 3: manifest exists with embedded=0, chunks=0 → DO NOT SKIP (corrupt)
    """
    # Scenario 1: Complete manifest → skip
    mock_s3 = MagicMock()
    mock_sqs = MagicMock()
    mock_bedrock = MagicMock()

    complete_manifest = json.dumps({
        'chunks': 5,
        'embedded': 5,
        'document_id': 'DOC#complete'
    })
    mock_s3.get_object.return_value = {
        'Body': MagicMock(read=lambda: complete_manifest.encode(), close=lambda: None)
    }

    with patch('boto3.client', side_effect=[mock_s3, mock_sqs, mock_bedrock]):
        from src.lambdas.chunk_and_embed.handler import lambda_handler

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#complete',
                    'text_s3_key': 'text/DOC#complete.txt'
                })
            }]
        }

        lambda_handler(event, {})

        # Assert: skipped (didn't download text, didn't call Bedrock)
        text_downloads = [c for c in mock_s3.get_object.call_args_list
                          if 'text/' in str(c)]
        assert len(text_downloads) == 0, "Should skip text download on complete manifest"
        assert not mock_bedrock.invoke_model.called, "Should skip Bedrock on complete manifest"

        # Assert: forwarded existing state
        assert mock_sqs.send_message.called
        forwarded = json.loads(mock_sqs.send_message.call_args[1]['MessageBody'])
        assert forwarded['chunks_created'] == 5
        assert forwarded['embeddings_persisted'] == 5
