"""
Lambda: validate_data
Purpose: Validate extracted structured data with business logic
Flow: validation queue → validate_data → save queue

FIXED:
- Table-driven validation with deterministic error codes
- Removed all PII from logs (only keys, counts, codes)
- NEXT_QUEUE_URL now required (fail fast)
- Removed emojis from logs (grepable output)
- Structured violations with {code, message, field, severity}
"""

import json
import boto3
import logging
import os
from datetime import datetime
from validation_rules import validate_structured_data

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client('sqs')

NEXT_QUEUE_URL = os.environ['NEXT_QUEUE_URL']  # Required - fail fast if missing



def lambda_handler(event, context):
    """
    Validate extracted structured data using table-driven rules.

    Input (from SQS):
    {
        ... (previous fields) ...,
        "structured_data": {
            "client_name": "Virgin Media O2",
            "contract_value": 500000,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "day_rates": [...]
        }
    }

    Output (adds to message):
    {
        ... (all input fields) ...,
        "validation_passed": true/false,
        "validation_errors": [{code, message, field, severity}],
        "validation_warnings": [{code, message, field, severity}]
    }
    """

    for record in event['Records']:
        # 1. Parse incoming message (log keys only, no PII)
        message = json.loads(record['body'])
        logger.info("received keys=%s", list(message.keys()))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']
            structured_data = message.get('structured_data', {})

            logger.info("start_validation doc_id=%s", doc_id)

            # 3. Run table-driven validation
            validation_passed, errors, warnings = validate_structured_data(structured_data)

            # 4. Log results (codes only, no PII)
            logger.info("validation_complete passed=%s errors=%d warnings=%d",
                       validation_passed, len(errors), len(warnings))

            if errors:
                error_codes = [e['code'] for e in errors]
                logger.warning("validation_errors codes=%s", error_codes)

            if warnings:
                warning_codes = [w['code'] for w in warnings]
                logger.info("validation_warnings codes=%s", warning_codes)

            # 5. ADD results to message
            message['validation_passed'] = validation_passed
            message['validation_errors'] = errors
            message['validation_warnings'] = warnings

            # 6. Log outgoing message (keys only, no PII)
            logger.info("forwarding keys=%s", list(message.keys()))

            # 7. Send to next queue (even if validation failed - we still want to save it)
            sqs.send_message(
                QueueUrl=NEXT_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            logger.info("forwarded to_queue=save")

            logger.info("stage_complete doc_id=%s", doc_id)

        except Exception as e:
            logger.error("error stage=validate-data msg=%s", str(e))
            logger.error("failed keys=%s", list(message.keys()))

            # Add error to message
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'validate-data',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })

            # Re-raise so SQS retries → DLQ
            raise

    return {'statusCode': 200}
