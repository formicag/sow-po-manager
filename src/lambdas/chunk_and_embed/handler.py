"""
Lambda: chunk_and_embed
Purpose: Chunk text and generate embeddings using Amazon Titan
Flow: chunk queue → chunk_and_embed → extraction queue

FIXED:
- Actually persists embeddings to S3 (was setting embeddings_stored=True without storing)
- Removes PII from logs (no full message dumps, no chunk previews)
- Parameterizes Bedrock region/model via env vars
- Adds retry/timeout config for Bedrock calls
- Validates chunk overlap < chunk_size to prevent infinite loops
- Removes SQS payload bloat (chunk_details with previews)
"""

import json
import os
import logging
from datetime import datetime
from botocore.config import Config
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sqs = boto3.client('sqs')

# Allow region/model to be set per-env and add sane retries/timeouts
BEDROCK_REGION = os.environ.get('BEDROCK_REGION', 'us-east-1')
EMBED_MODEL_ID = os.environ.get('EMBED_MODEL_ID', 'amazon.titan-embed-text-v1')
_cfg = Config(
    retries={'max_attempts': 3, 'mode': 'standard'},
    read_timeout=15,
    connect_timeout=3,
)
bedrock = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION, config=_cfg)

BUCKET_NAME = os.environ.get('BUCKET_NAME')
NEXT_QUEUE_URL = os.environ.get('NEXT_QUEUE_URL')
EMBED_S3_PREFIX = os.environ.get('EMBED_S3_PREFIX', 'embeddings/')  # s3://bucket/embeddings/{doc_id}/

# Chunking parameters (tunable via env)
CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', '1000'))
CHUNK_OVERLAP = int(os.environ.get('CHUNK_OVERLAP', '200'))


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Split text into overlapping chunks with guards."""
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


def generate_embedding(text: str):
    """Generate embedding using Amazon Titan Embeddings."""
    try:
        response = bedrock.invoke_model(
            modelId=EMBED_MODEL_ID,
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'inputText': text
            })
        )

        response_body = json.loads(response['body'].read())
        embedding = response_body.get('embedding')

        return embedding

    except Exception as e:
        logger.error("Embedding error: %s", str(e))
        return None


def lambda_handler(event, context):
    """
    Chunk text and generate embeddings.

    Input (from SQS):
    {
        ... (previous fields) ...,
        "text_extracted": true,
        "text_s3_key": "text/DOC#abc123.txt",
        "text_length": 45230,
        "page_count": 12
    }

    Output (adds to message):
    {
        ... (all input fields) ...,
        "chunks_created": 15,
        "embeddings_persisted": 15,
        "embeddings_s3_prefix": "embeddings/DOC#abc123/"
    }
    """

    for record in event['Records']:
        # 1. Parse incoming message (log keys only; avoid PII)
        message = json.loads(record['body'])
        logger.info("received keys: %s", list(message.keys()))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']
            bucket = message.get('s3_bucket', BUCKET_NAME)
            text_s3_key = message['text_s3_key']

            logger.info("start chunk+embed doc_id=%s", doc_id)

            # 3. Download text from S3
            logger.info("download text s3_key=%s", text_s3_key)
            response = s3.get_object(Bucket=bucket, Key=text_s3_key)
            full_text = response['Body'].read().decode('utf-8')

            # 4. Chunk the text
            logger.info("chunking size=%s overlap=%s", CHUNK_SIZE, CHUNK_OVERLAP)
            chunks = chunk_text(full_text)
            logger.info("created chunks=%s", len(chunks))

            # 5. Generate embeddings for each chunk and persist to S3
            logger.info("generating embeddings...")
            persisted = 0
            embeddings_prefix = f"{EMBED_S3_PREFIX}{doc_id}/"

            for idx, chunk in enumerate(chunks):
                logger.info("chunk %s/%s len=%s", idx + 1, len(chunks), len(chunk))

                # Generate embedding
                embedding = generate_embedding(chunk)

                if embedding:
                    # Persist to S3 instead of storing in SQS message
                    key = f"{embeddings_prefix}{idx:05d}.json"
                    payload = {
                        "document_id": doc_id,
                        "chunk_index": idx,
                        "embedding": embedding,
                        "text_len": len(chunk)
                    }
                    s3.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=json.dumps(payload).encode("utf-8")
                    )
                    persisted += 1

            logger.info("persisted embeddings=%s at s3://%s/%s", persisted, bucket, embeddings_prefix)

            # 6. ADD results to message (no PII, no previews)
            message['chunks_created'] = len(chunks)
            message['embeddings_persisted'] = persisted
            message['embeddings_s3_prefix'] = embeddings_prefix

            # 7. Log outgoing message (keys only, no PII)
            logger.info("forwarding keys: %s", list(message.keys()))

            # 8. Send to next queue
            if NEXT_QUEUE_URL:
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
                logger.info("forwarded to next queue")
            else:
                logger.error("NEXT_QUEUE_URL not set; message not forwarded")

            logger.info("stage complete doc_id=%s", doc_id)

        except Exception as e:
            logger.error("error: %s", str(e))
            logger.error("failed keys: %s", list(message.keys()))

            # Add error to message
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'chunk-and-embed',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })

            # Re-raise so SQS retries → DLQ
            raise

    return {'statusCode': 200}
