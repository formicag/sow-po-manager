"""
Lambda: chunk_and_embed
Purpose: Chunk text and generate embeddings using Amazon Titan
Flow: chunk queue → chunk_and_embed → extraction queue

CRITICAL FIXES (v1.6.0):
- Manifest-gated idempotency: only skips if manifest exists AND is complete
- Partial state detection: resumes if chunks exist without complete manifest
- Embedding success ratio guard: fails if < 95% embeddings succeed (configurable)
- Content-hash versioning: SHA256 in manifest + per-chunk for future-proofing
- Exponential backoff with jitter: 5 retries for Bedrock 429/5xx errors
- Payload whitelist: only canonical keys forwarded (no PII leakage)
- Atomic manifest write: written LAST with all metadata
"""

import json
import os
import logging
import hashlib
import time
import random
from datetime import datetime
from botocore.config import Config
from botocore.exceptions import ClientError
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sqs = boto3.client('sqs')

# Bedrock configuration with retries/timeouts
BEDROCK_REGION = os.environ.get('BEDROCK_REGION', 'eu-west-1')
EMBED_MODEL_ID = os.environ.get('EMBED_MODEL_ID', 'amazon.titan-embed-text-v2:0')
_cfg = Config(
    retries={'max_attempts': 3, 'mode': 'standard'},
    read_timeout=15,
    connect_timeout=3,
)
bedrock = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION, config=_cfg)

# Required environment variables (fail fast at module load)
BUCKET_NAME = os.environ['BUCKET_NAME']
NEXT_QUEUE_URL = os.environ['NEXT_QUEUE_URL']

# Optional tuning parameters
EMBED_S3_PREFIX = os.environ.get('EMBED_S3_PREFIX', 'embeddings/')
CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', '1000'))
CHUNK_OVERLAP = int(os.environ.get('CHUNK_OVERLAP', '200'))
EMBED_SUCCESS_MIN_RATIO = float(os.environ.get('EMBED_SUCCESS_MIN_RATIO', '0.95'))


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Split text into overlapping chunks with validation."""
    if overlap >= chunk_size:
        raise ValueError(f"CHUNK_OVERLAP({overlap}) must be < CHUNK_SIZE({chunk_size})")

    chunks = []
    n = len(text)
    start = 0

    while start < n:
        end = min(start + chunk_size, n)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)

    return chunks


def generate_embedding_with_backoff(text: str, max_attempts: int = 5) -> list:
    """
    Generate embedding with exponential backoff for transient failures.
    Retries on 429, 500, 502, 503, 504 errors with jitter.
    """
    for attempt in range(max_attempts):
        try:
            response = bedrock.invoke_model(
                modelId=EMBED_MODEL_ID,
                contentType='application/json',
                accept='application/json',
                body=json.dumps({'inputText': text})
            )
            response_body = json.loads(response['body'].read())
            return response_body.get('embedding')

        except ClientError as e:
            error_code = e.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 500)
            if error_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                # Exponential backoff with jitter: 1s, 2s, 4s, 8s
                sleep_time = min(8, 2 ** attempt) + random.random()
                logger.warning("bedrock %s attempt=%s/%s sleep=%.2fs",
                             error_code, attempt + 1, max_attempts, sleep_time)
                time.sleep(sleep_time)
                continue
            # Non-retryable or max attempts reached
            logger.error("bedrock error code=%s attempt=%s: %s", error_code, attempt + 1, str(e))
            return None

        except Exception as e:
            logger.error("embedding error attempt=%s: %s", attempt + 1, str(e))
            if attempt < max_attempts - 1:
                time.sleep(min(8, 2 ** attempt) + random.random())
                continue
            return None

    return None


def _put_manifest(bucket: str, key: str, manifest_obj: dict):
    """Write manifest.json atomically."""
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest_obj, indent=2).encode('utf-8')
    )


def lambda_handler(event, context):
    """
    Chunk text and generate embeddings with robust idempotency and failure handling.

    Input (from SQS):
    {
        "document_id": "DOC#abc123",
        "text_s3_key": "text/DOC#abc123.txt",
        "text_length": 45230,
        ...
    }

    Output (whitelisted envelope):
    {
        "document_id": "DOC#abc123",
        "text_s3_key": "text/DOC#abc123.txt",
        "embeddings_s3_prefix": "embeddings/DOC#abc123/",
        "chunks_created": 15,
        "embeddings_persisted": 15
    }
    """

    for record in event['Records']:
        message = json.loads(record['body'])
        logger.info("received keys: %s", list(message.keys()))

        try:
            # Extract required fields
            doc_id = message['document_id']
            bucket = message.get('s3_bucket', BUCKET_NAME)
            text_s3_key = message['text_s3_key']

            logger.info("start chunk+embed doc_id=%s", doc_id)

            embeddings_prefix = f"{EMBED_S3_PREFIX}{doc_id}/"
            manifest_key = f"{embeddings_prefix}manifest.json"

            # --- IDEMPOTENCY: skip only if manifest exists AND is complete ---
            try:
                manifest_resp = s3.get_object(Bucket=bucket, Key=manifest_key)
                manifest_data = json.loads(manifest_resp['Body'].read().decode('utf-8'))

                chunks_total = int(manifest_data.get('chunks', 0))
                embedded_count = int(manifest_data.get('embedded', 0))

                # Complete only if embedded >= chunks and chunks > 0
                if embedded_count >= chunks_total > 0:
                    logger.info("idempotent skip: complete manifest doc_id=%s chunks=%s embedded=%s",
                              doc_id, chunks_total, embedded_count)

                    # Forward whitelisted envelope
                    forward = {
                        'document_id': doc_id,
                        'text_s3_key': text_s3_key,
                        'embeddings_s3_prefix': embeddings_prefix,
                        'chunks_created': chunks_total,
                        'embeddings_persisted': embedded_count,
                    }
                    sqs.send_message(QueueUrl=NEXT_QUEUE_URL, MessageBody=json.dumps(forward))
                    logger.info("forwarded existing state doc_id=%s", doc_id)
                    continue
                else:
                    # Partial state detected
                    logger.warning("partial manifest detected doc_id=%s embedded=%s chunks=%s — will resume/repair",
                                 doc_id, embedded_count, chunks_total)

            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    logger.info("no manifest found; fresh embedding run")
                else:
                    logger.warning("manifest check failed: %s (continuing)", str(e))
            except Exception as e:
                logger.warning("manifest check error: %s (continuing)", str(e))

            # --- DOWNLOAD TEXT ---
            logger.info("download text s3_key=%s", text_s3_key)
            text_resp = s3.get_object(Bucket=bucket, Key=text_s3_key)
            full_text = text_resp['Body'].read().decode('utf-8')
            source_etag = text_resp.get('ETag', '').strip('"')

            # Content hash for future-proofing (detect re-embedding needs)
            content_sha256 = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
            logger.info("content sha256=%s etag=%s", content_sha256[:16], source_etag[:16])

            # --- CHUNK TEXT ---
            logger.info("chunking size=%s overlap=%s", CHUNK_SIZE, CHUNK_OVERLAP)
            chunks = chunk_text(full_text)
            logger.info("created chunks=%s", len(chunks))

            # --- GENERATE AND PERSIST EMBEDDINGS ---
            logger.info("generating embeddings...")
            persisted = 0

            for idx, chunk in enumerate(chunks):
                logger.info("chunk %s/%s len=%s", idx + 1, len(chunks), len(chunk))

                # Generate with backoff
                embedding = generate_embedding_with_backoff(chunk)

                if not embedding:
                    logger.warning("embedding failed chunk=%s", idx)
                    continue

                # Persist with chunk content hash for future integrity checks
                chunk_sha256 = hashlib.sha256(chunk.encode('utf-8')).hexdigest()
                key = f"{embeddings_prefix}{idx:05d}.json"
                payload = {
                    'document_id': doc_id,
                    'chunk_index': idx,
                    'embedding': embedding,
                    'text_len': len(chunk),
                    'chunk_sha256': chunk_sha256
                }

                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=json.dumps(payload).encode('utf-8')
                )
                persisted += 1

            logger.info("persisted embeddings=%s/%s", persisted, len(chunks))

            # --- SUCCESS RATIO GUARD ---
            success_ratio = persisted / max(1, len(chunks))
            if success_ratio < EMBED_SUCCESS_MIN_RATIO:
                error_msg = f"embed success {success_ratio:.2%} < {EMBED_SUCCESS_MIN_RATIO:.0%} threshold"
                logger.error(error_msg)
                raise RuntimeError(error_msg + " — aborting (no manifest written)")

            # --- ATOMIC MANIFEST WRITE (success marker) ---
            manifest = {
                'document_id': doc_id,
                'embeddings_prefix': embeddings_prefix,
                'model': EMBED_MODEL_ID,
                'chunks': len(chunks),
                'embedded': persisted,
                'source_etag': source_etag,
                'content_sha256': content_sha256,
                'success_ratio': success_ratio,
                'created_at': datetime.utcnow().isoformat() + 'Z',
            }

            _put_manifest(bucket, manifest_key, manifest)
            logger.info("wrote manifest s3://%s/%s", bucket, manifest_key)

            # --- FORWARD WHITELISTED ENVELOPE (no PII) ---
            forward = {
                'document_id': doc_id,
                'text_s3_key': text_s3_key,
                'embeddings_s3_prefix': embeddings_prefix,
                'chunks_created': len(chunks),
                'embeddings_persisted': persisted,
            }

            logger.info("forwarding keys: %s", list(forward.keys()))
            sqs.send_message(QueueUrl=NEXT_QUEUE_URL, MessageBody=json.dumps(forward))
            logger.info("stage complete doc_id=%s", doc_id)

        except Exception as e:
            logger.error("error: %s", str(e))
            logger.error("failed keys: %s", list(message.keys()))

            # Add error envelope
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'chunk-and-embed',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })

            # Re-raise for SQS retry → DLQ
            raise

    return {'statusCode': 200}
