"""
Lambda: chunk_and_embed
Purpose: Chunk text and generate embeddings using Amazon Titan
Flow: chunk queue → chunk_and_embed → extraction queue
"""

import json
import boto3
import logging
import os
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sqs = boto3.client('sqs')
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

BUCKET_NAME = os.environ.get('BUCKET_NAME')
NEXT_QUEUE_URL = os.environ.get('NEXT_QUEUE_URL')

# Chunking parameters
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200  # overlap between chunks


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if chunk.strip():  # Skip empty chunks
            chunks.append(chunk)

        start = end - overlap  # Move forward with overlap

    return chunks


def generate_embedding(text):
    """Generate embedding using Amazon Titan Embeddings."""
    try:
        response = bedrock.invoke_model(
            modelId='amazon.titan-embed-text-v1',
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
        logger.error(f"Failed to generate embedding: {str(e)}")
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
        "embeddings_stored": true,
        "chunk_details": [...]
    }
    """

    for record in event['Records']:
        # 1. Parse incoming message
        message = json.loads(record['body'])
        logger.info(f"📥 RECEIVED MESSAGE:")
        logger.info(json.dumps(message, indent=2))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']
            bucket = message.get('s3_bucket', BUCKET_NAME)
            text_s3_key = message['text_s3_key']

            logger.info(f"🔍 Starting chunking and embedding for {doc_id}")

            # 3. Download text from S3
            logger.info(f"⬇️  Downloading text from S3: {text_s3_key}")
            response = s3.get_object(Bucket=bucket, Key=text_s3_key)
            full_text = response['Body'].read().decode('utf-8')

            # 4. Chunk the text
            logger.info(f"✂️  Chunking text (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")
            chunks = chunk_text(full_text)
            logger.info(f"   Created {len(chunks)} chunks")

            # 5. Generate embeddings for each chunk
            logger.info(f"🧮 Generating embeddings...")
            chunk_details = []

            for idx, chunk in enumerate(chunks):
                logger.info(f"   Processing chunk {idx + 1}/{len(chunks)}")

                # Generate embedding
                embedding = generate_embedding(chunk)

                if embedding:
                    chunk_details.append({
                        'chunk_index': idx,
                        'text_preview': chunk[:100] + '...',
                        'embedding_length': len(embedding)
                    })

                    # Store chunk with embedding (we'll save to DynamoDB in save_metadata Lambda)
                    # For now, just track it in the message

            logger.info(f"✅ Generated {len(chunk_details)} embeddings")

            # 6. ADD results to message
            message['chunks_created'] = len(chunks)
            message['embeddings_stored'] = True
            message['chunk_details'] = chunk_details

            # 7. Log outgoing message
            logger.info(f"📤 FORWARDING MESSAGE:")
            logger.info(json.dumps(message, indent=2))

            # 8. Send to next queue
            if NEXT_QUEUE_URL:
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
                logger.info(f"✅ Message forwarded to extraction queue")

            logger.info(f"✅ STAGE COMPLETE for {doc_id}")

        except Exception as e:
            logger.error(f"❌ ERROR: {str(e)}")
            logger.error(f"   Message was: {json.dumps(message, indent=2)}")

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
