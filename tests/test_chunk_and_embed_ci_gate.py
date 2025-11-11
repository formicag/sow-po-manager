# tests/test_chunk_and_embed_ci_gate.py
import io
import json
import os
import sys
from pathlib import Path
import importlib
import pytest

# ---------- Fake AWS clients (simple, robust) ----------

class _Stream:
    def __init__(self, b: bytes):
        self._b = b
    def read(self):
        return self._b

class FakeBedrock:
    def __init__(self, embedding=None):
        # Tiny, deterministic embedding
        self._embedding = embedding or [0.1, 0.2, 0.3]

    def invoke_model(self, modelId, contentType, accept, body):
        # Return a Streaming-like dict as boto3 would
        return {"body": _Stream(json.dumps({"embedding": self._embedding}).encode("utf-8"))}

class FakeS3:
    def __init__(self, text_map):
        """
        text_map: dict of {("Bucket","Key"): "text content"}
        """
        self._text_map = { (b, k): v for (b, k), v in text_map.items() }
        self.put_calls = []      # list of dicts with Bucket, Key, Body
        self.objects = {}        # recall what's been written

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        try:
            content = self._text_map[(Bucket, Key)]
        except KeyError:
            # Simulate NoSuchKey via ClientError
            error_response = {
                'Error': {
                    'Code': 'NoSuchKey',
                    'Message': 'The specified key does not exist.'
                }
            }
            raise ClientError(error_response, 'GetObject')
        return {"Body": _Stream(content.encode("utf-8"))}

    def put_object(self, Bucket, Key, Body):
        self.put_calls.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self.objects[(Bucket, Key)] = Body
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000):
        # Count currently stored keys matching Prefix
        count = sum(1 for (b, k) in self.objects.keys() if b == Bucket and k.startswith(Prefix))
        return {"KeyCount": count, "Contents": [{"Key": k} for (b, k) in self.objects.keys() if b == Bucket and k.startswith(Prefix)]}

class FakeSQS:
    def __init__(self):
        self.sent = []  # list of {"QueueUrl":..., "MessageBody":...}

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": "m-1"}

# ---------- Test harness helpers ----------

def _import_handler_with_env(monkeypatch, *, bucket="bkt", queue="https://sqs.local/next",
                             prefix="embeddings/", region="eu-west-1",
                             model="amazon.titan-embed-text-v2:0",
                             chunk_size="1000", chunk_overlap="200"):
    # Set env BEFORE import (module reads required env on import)
    monkeypatch.setenv("BUCKET_NAME", bucket)
    monkeypatch.setenv("NEXT_QUEUE_URL", queue)
    monkeypatch.setenv("EMBED_S3_PREFIX", prefix)
    monkeypatch.setenv("BEDROCK_REGION", region)
    monkeypatch.setenv("EMBED_MODEL_ID", model)
    monkeypatch.setenv("CHUNK_SIZE", chunk_size)
    monkeypatch.setenv("CHUNK_OVERLAP", chunk_overlap)

    # Ensure project root on path (repo layout: /src/lambdas/...)
    root = Path(__file__).resolve().parents[1]  # repo root (…/tests/..)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Import (or reload) the handler
    mod = importlib.import_module("src.lambdas.chunk_and_embed.handler")
    mod = importlib.reload(mod)  # ensure fresh import per test
    return mod

def _fake_world(mod, fake_s3, fake_sqs, fake_br):
    # Monkeypatch module-level AWS clients
    mod.s3 = fake_s3
    mod.sqs = fake_sqs
    mod.bedrock = fake_br

def _mk_event(document_id="DOC#test", bucket="bkt", text_key="text/DOC#test.txt"):
    msg = {
        "document_id": document_id,
        "s3_bucket": bucket,
        "text_extracted": True,
        "text_s3_key": text_key,
        "text_length": 42,
        "page_count": 1
    }
    return {"Records": [{"body": json.dumps(msg)}]}

# ---------- Tests ----------

def test_s3_persistence_and_manifest(monkeypatch):
    """
    Gate #1: At least one chunk file written under embeddings/.../
             AND one manifest.json written under embeddings/.../
    """
    mod = _import_handler_with_env(monkeypatch)

    # Provide a small text so we get >=1 chunk
    text_map = {("bkt", "text/DOC#test.txt"): "hello world document"}
    fake_s3 = FakeS3(text_map)
    fake_sqs = FakeSQS()
    fake_br = FakeBedrock()

    _fake_world(mod, fake_s3, fake_sqs, fake_br)

    # Execute
    event = _mk_event()
    result = mod.lambda_handler(event, None)
    assert result["statusCode"] == 200

    # Inspect S3 writes
    keys = [c["Key"] for c in fake_s3.put_calls]
    chunk_keys = [k for k in keys if k.endswith(".json") and not k.endswith("manifest.json")]
    manifest_keys = [k for k in keys if k.endswith("/manifest.json")]

    assert len(chunk_keys) >= 1, "Expected at least one chunk persisted to S3"
    assert len(manifest_keys) == 1, "Expected exactly one manifest.json written"

def test_sqs_message_purity_and_canonical_keys(monkeypatch):
    """
    Gate #2: SQS message body has:
       - NO previews/raw text (e.g., no 'text_preview', no full text)
       - The canonical added keys are present ONLY:
         chunks_created, embeddings_persisted, embeddings_s3_prefix, embeddings_manifest
    (Message may still include upstream fields like document_id, s3_bucket, text_s3_key — that's fine.)
    """
    mod = _import_handler_with_env(monkeypatch)

    # World
    text_map = {("bkt", "text/DOC#test.txt"): "small text to embed"}
    fake_s3 = FakeS3(text_map)
    fake_sqs = FakeSQS()
    fake_br = FakeBedrock()
    _fake_world(mod, fake_s3, fake_sqs, fake_br)

    # Execute
    event = _mk_event()
    _ = mod.lambda_handler(event, None)

    # Exactly one message expected
    assert len(fake_sqs.sent) == 1
    body = fake_sqs.sent[0]["MessageBody"]
    assert isinstance(body, str)
    msg = json.loads(body)

    # No previews/raw text
    assert "text_preview" not in body
    assert "chunk_details" not in body
    # Guard against sneaky raw text leakage
    assert "hello world document" not in body
    assert "small text to embed" not in body

    # Canonical keys exist
    must_keys = {"chunks_created", "embeddings_persisted", "embeddings_s3_prefix", "embeddings_manifest"}
    assert must_keys.issubset(msg.keys()), f"Missing canonical keys: {must_keys - set(msg.keys())}"

    # And they look sane
    assert isinstance(msg["chunks_created"], int) and msg["chunks_created"] >= 1
    assert isinstance(msg["embeddings_persisted"], int) and msg["embeddings_persisted"] >= 1
    assert isinstance(msg["embeddings_s3_prefix"], str) and msg["embeddings_s3_prefix"].startswith("embeddings/DOC#test")
    assert isinstance(msg["embeddings_manifest"], str) and msg["embeddings_manifest"].endswith("/manifest.json")

def test_chunk_overlap_guard_raises(monkeypatch):
    """
    Gate #3: CHUNK_OVERLAP >= CHUNK_SIZE should raise ValueError
    """
    # Import with bad config
    with pytest.raises(ValueError, match="CHUNK_OVERLAP.*must be.*CHUNK_SIZE"):
        mod = _import_handler_with_env(monkeypatch, chunk_size="100", chunk_overlap="100")
        # Try to chunk text with the module's chunk_text function
        mod.chunk_text("some text", chunk_size=100, overlap=100)

def test_next_queue_url_required(monkeypatch):
    """
    Gate #4: Missing NEXT_QUEUE_URL should raise KeyError at module import
    """
    # Don't set NEXT_QUEUE_URL
    monkeypatch.setenv("BUCKET_NAME", "bkt")
    # Deliberately omit NEXT_QUEUE_URL
    monkeypatch.delenv("NEXT_QUEUE_URL", raising=False)

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Remove module from cache if present
    if "src.lambdas.chunk_and_embed.handler" in sys.modules:
        del sys.modules["src.lambdas.chunk_and_embed.handler"]

    with pytest.raises(KeyError, match="NEXT_QUEUE_URL"):
        importlib.import_module("src.lambdas.chunk_and_embed.handler")
