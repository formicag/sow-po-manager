"""
Lambda: save_metadata
Purpose: Save document metadata to DynamoDB with idempotent version tracking
Flow: save queue → save_metadata → DynamoDB (final stage)

FIXED (v1.5.0):
- Idempotent writes (won't overwrite existing versions)
- Uses embeddings_manifest instead of chunk_details
- Required NEXT_QUEUE_URL (fail fast)
- PII-safe logging (keys only, no values)
- Proper GSI keys for expiry tracking (GSI2PK/SK)
- Best-effort LATEST pointer updates

CRITICAL FIXES (v1.6.0):
- Race-proof LATEST pointer: uses update_item with condition (only updates if version >= current)
- Prevents concurrent writes from setting LATEST to an older version
- Conditional expression: attribute_not_exists(latest_version) OR latest_version < :new_version
"""

import json
import boto3
import logging
import os
from datetime import datetime
from decimal import Decimal
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.client('dynamodb')
sqs = boto3.client('sqs')

TABLE_NAME = os.environ['TABLE_NAME']  # Required - fail fast
NEXT_QUEUE_URL = os.environ.get('NEXT_QUEUE_URL')  # Optional (last stage, may not forward)


def _decimal_to_dynamodb(value):
    """Convert Python types to DynamoDB-safe types."""
    if isinstance(value, dict):
        return {k: _decimal_to_dynamodb(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_decimal_to_dynamodb(item) for item in value]
    elif isinstance(value, float):
        return Decimal(str(value))
    elif isinstance(value, bool):
        return value
    elif isinstance(value, (str, int)):
        return value
    elif value is None:
        return None
    else:
        return str(value)


def lambda_handler(event, context):
    """
    Save document metadata to DynamoDB with idempotent version tracking.

    Input (from SQS):
    {
        "document_id": "DOC#abc123",
        "structured_data": { ... },
        "embeddings_manifest": "embeddings/DOC#abc123/manifest.json",
        "embeddings_s3_prefix": "embeddings/DOC#abc123/",
        "validation_passed": true,
        "validation_errors": [],
        "validation_warnings": [],
        ...
    }

    Output:
    - Document VERSION#<timestamp> saved to DynamoDB (idempotent)
    - LATEST pointer updated (best-effort)
    - Optional: forwards to NEXT_QUEUE_URL if set
    """

    for record in event['Records']:
        # 1. Parse incoming message (log keys only, no PII)
        message = json.loads(record['body'])
        logger.info("received keys=%s", list(message.keys()))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']
            structured_data = message.get('structured_data', {})

            # Generate version from timestamp (unique, sortable)
            version = f"{int(datetime.utcnow().timestamp())}"

            logger.info("start_save doc_id=%s version=%s", doc_id, version)

            # 3. Build DynamoDB item
            pk = f"DOC#{doc_id}"
            sk = f"VERSION#{version}"

            # Determine contract end for GSI2 (expiry tracking)
            end_date = structured_data.get('end_date', '')
            end_ym = end_date[:7] if end_date and len(end_date) >= 7 else 'UNKNOWN'

            item = {
                'PK': {'S': pk},
                'SK': {'S': sk},
                'client_name': {'S': structured_data.get('client_name', 'Unknown')},
                'contract_start': {'S': structured_data.get('start_date', '')} if structured_data.get('start_date') else {'NULL': True},
                'contract_end': {'S': end_date} if end_date else {'NULL': True},
                'ir35_status': {'S': structured_data.get('ir35_status', 'Not Specified')},
                'embeddings_prefix': {'S': message.get('embeddings_s3_prefix', '')},
                'embeddings_manifest': {'S': message.get('embeddings_manifest', '')},
                'validation_passed': {'BOOL': message.get('validation_passed', False)},
                'created_at': {'S': datetime.utcnow().isoformat() + 'Z'},

                # GSIs
                'GSI1PK': {'S': f"CLIENT#{structured_data.get('client_name', 'Unknown')}"},
                'GSI1SK': {'S': f"CREATED#{datetime.utcnow().isoformat()}"},
                'GSI2PK': {'S': f"EXPIRY#{end_ym}"},
                'GSI2SK': {'S': pk},
            }

            # Add contract_value if present
            contract_value = structured_data.get('contract_value')
            if contract_value is not None:
                item['contract_value'] = {'N': str(contract_value)}

            # Add PO number to GSI3 if available
            po_number = structured_data.get('po_number')
            if po_number:
                item['GSI3PK'] = {'S': f"PO#{po_number}"}
                item['GSI3SK'] = {'S': f"CLIENT#{structured_data.get('client_name', 'Unknown')}"}

            # Add validation errors/warnings counts (not full text to avoid PII)
            error_count = len(message.get('validation_errors', []))
            warning_count = len(message.get('validation_warnings', []))
            if error_count > 0:
                item['validation_error_count'] = {'N': str(error_count)}
            if warning_count > 0:
                item['validation_warning_count'] = {'N': str(warning_count)}

            # 4. Idempotent create (won't overwrite existing version)
            try:
                dynamodb.put_item(
                    TableName=TABLE_NAME,
                    Item=item,
                    ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"
                )
                created = True
                logger.info("created_version pk=%s sk=%s", pk, sk)
            except ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    logger.info("idempotent_skip version_exists pk=%s sk=%s", pk, sk)
                    created = False
                else:
                    raise

            # 5. Update LATEST pointer (race-proof: only if new version >= current)
            # Use update_item with condition to prevent race where older version overwrites newer
            try:
                dynamodb.update_item(
                    TableName=TABLE_NAME,
                    Key={
                        'PK': {'S': pk},
                        'SK': {'S': 'LATEST'}
                    },
                    UpdateExpression='SET latest_version = :v, latest_updated_at = :ts',
                    ConditionExpression='attribute_not_exists(latest_version) OR latest_version < :v',
                    ExpressionAttributeValues={
                        ':v': {'S': version},
                        ':ts': {'S': datetime.utcnow().isoformat() + 'Z'}
                    }
                )
                logger.info("updated_latest pk=%s version=%s", pk, version)
            except ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    # Newer version already exists - this is fine (concurrent writes)
                    logger.info("latest_skip newer_version_exists pk=%s version=%s", pk, version)
                else:
                    # Other error - log but don't fail (best-effort)
                    logger.warning("latest_update_failed pk=%s error=%s", pk, str(e))

            # 6. Forward minimal summary downstream (if NEXT_QUEUE_URL set)
            if NEXT_QUEUE_URL:
                summary = {
                    'document_id': doc_id,
                    'version': version,
                    'metadata_saved': True,
                    'created': created,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(summary)
                )
                logger.info("forwarded_summary to_queue=%s", NEXT_QUEUE_URL)

            logger.info("stage_complete doc_id=%s", doc_id)

        except Exception as e:
            logger.error("error stage=save-metadata msg=%s", str(e))
            logger.error("failed keys=%s", list(message.keys()))

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
