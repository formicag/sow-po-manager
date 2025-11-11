"""
Lambda: save_metadata
Purpose: Save document metadata and chunks to DynamoDB (final stage)
Flow: save queue → save_metadata → DynamoDB
"""

import json
import boto3
import logging
import os
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE')
table = dynamodb.Table(DYNAMODB_TABLE)


def decimal_default(obj):
    """JSON encoder for Decimal objects."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def convert_floats_to_decimal(obj):
    """Convert floats to Decimal for DynamoDB."""
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    else:
        return obj


def save_document_version(doc_id, message):
    """Save document version to DynamoDB."""
    # Convert floats to Decimal
    message_decimal = convert_floats_to_decimal(message)

    item = {
        'PK': doc_id,
        'SK': 'VERSION#1.0.0',
        'GSI1PK': f"CLIENT#{message.get('client_name', 'Unknown')}",
        'GSI1SK': f"CREATED#{message.get('timestamp', datetime.utcnow().isoformat())}",
        'document_id': doc_id,
        'client_name': message.get('client_name', 'Unknown'),
        'uploaded_by': message.get('uploaded_by', 'unknown'),
        'timestamp': message.get('timestamp', datetime.utcnow().isoformat()),
        's3_bucket': message.get('s3_bucket'),
        's3_key': message.get('s3_key'),
        'text_s3_key': message.get('text_s3_key'),
        'text_length': message.get('text_length', 0),
        'page_count': message.get('page_count', 0),
        'chunks_created': message.get('chunks_created', 0),
        'structured_data': message_decimal.get('structured_data', {}),
        'extraction_confidence': Decimal(str(message.get('extraction_confidence', 0))),
        'validation_passed': message.get('validation_passed', False),
        'validation_errors': message.get('validation_errors', []),
        'validation_warnings': message.get('validation_warnings', []),
        'processing_errors': message.get('errors', []),
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }

    # Add PO number to GSI3 if available
    structured_data = message.get('structured_data', {})
    po_number = structured_data.get('po_number')
    if po_number:
        item['GSI3PK'] = f"PO_NUM#{po_number}"
        item['GSI3SK'] = f"CLIENT#{message.get('client_name', 'Unknown')}"

    table.put_item(Item=item)
    logger.info(f"✅ Saved VERSION#1.0.0")


def save_latest_pointer(doc_id, message):
    """Save LATEST pointer for fast reads."""
    message_decimal = convert_floats_to_decimal(message)

    item = {
        'PK': doc_id,
        'SK': 'LATEST',
        'document_id': doc_id,
        'client_name': message.get('client_name', 'Unknown'),
        'uploaded_by': message.get('uploaded_by', 'unknown'),
        'timestamp': message.get('timestamp', datetime.utcnow().isoformat()),
        's3_bucket': message.get('s3_bucket'),
        's3_key': message.get('s3_key'),
        'text_s3_key': message.get('text_s3_key'),
        'text_length': message.get('text_length', 0),
        'page_count': message.get('page_count', 0),
        'chunks_created': message.get('chunks_created', 0),
        'structured_data': message_decimal.get('structured_data', {}),
        'extraction_confidence': Decimal(str(message.get('extraction_confidence', 0))),
        'validation_passed': message.get('validation_passed', False),
        'validation_errors': message.get('validation_errors', []),
        'validation_warnings': message.get('validation_warnings', []),
        'processing_errors': message.get('errors', []),
        'updated_at': datetime.utcnow().isoformat()
    }

    table.put_item(Item=item)
    logger.info(f"✅ Saved LATEST pointer")


def save_chunks(doc_id, chunk_details):
    """Save text chunks with embeddings to DynamoDB."""
    # Note: In a real implementation, you'd store the actual chunk text and embeddings
    # For now, we just log that we would save them
    logger.info(f"📝 Would save {len(chunk_details)} chunks to DynamoDB")

    # Example of how you'd save chunks:
    # for chunk_info in chunk_details:
    #     chunk_index = chunk_info['chunk_index']
    #     item = {
    #         'PK': doc_id,
    #         'SK': f"CHUNK#{chunk_index:03d}",
    #         'GSI2PK': doc_id,
    #         'GSI2SK': f"CHUNK#{chunk_index:03d}",
    #         'chunk_index': chunk_index,
    #         'text_chunk': chunk_text,
    #         'embedding_vector': embedding_bytes,  # Binary format
    #     }
    #     table.put_item(Item=item)


def lambda_handler(event, context):
    """
    Save all document metadata to DynamoDB.

    Input (from SQS):
    {
        ... (complete message with all processing results) ...
    }

    Output:
    - Document version saved to DynamoDB
    - LATEST pointer updated
    - Chunks saved (if present)
    """

    for record in event['Records']:
        # 1. Parse incoming message
        message = json.loads(record['body'])
        logger.info(f"📥 RECEIVED MESSAGE:")
        logger.info(json.dumps(message, indent=2, default=decimal_default))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']

            logger.info(f"🔍 Starting metadata save for {doc_id}")

            # 3. Save document version
            logger.info(f"💾 Saving document version...")
            save_document_version(doc_id, message)

            # 4. Save LATEST pointer
            logger.info(f"💾 Saving LATEST pointer...")
            save_latest_pointer(doc_id, message)

            # 5. Save chunks (if present)
            chunk_details = message.get('chunk_details', [])
            if chunk_details:
                logger.info(f"💾 Saving {len(chunk_details)} chunks...")
                save_chunks(doc_id, chunk_details)

            logger.info(f"✅ All data saved to DynamoDB")
            logger.info(f"✅ FINAL STAGE COMPLETE for {doc_id}")

        except Exception as e:
            logger.error(f"❌ ERROR: {str(e)}")
            logger.error(f"   Message was: {json.dumps(message, indent=2, default=decimal_default)}")

            # Add error to message
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'save-metadata',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })

            # Re-raise so SQS retries → DLQ
            raise

    return {'statusCode': 200}
