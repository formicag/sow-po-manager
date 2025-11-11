"""
Lambda: validate_data
Purpose: Validate extracted structured data with business logic
Flow: validation queue → validate_data → save queue
"""

import json
import boto3
import logging
import os
from datetime import datetime, date

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client('sqs')

NEXT_QUEUE_URL = os.environ.get('NEXT_QUEUE_URL')

# Validation thresholds
MAX_DAY_RATE = 1200  # GBP
MIN_DAY_RATE = 200   # GBP
MAX_CONTRACT_VALUE = 10000000  # £10M


def validate_day_rates(day_rates):
    """Validate day rates with business logic."""
    warnings = []
    errors = []

    for rate_info in day_rates:
        role = rate_info.get('role', 'Unknown')
        rate = rate_info.get('rate', 0)

        # Check if rate is within reasonable bounds
        if rate > MAX_DAY_RATE:
            warnings.append(f"Day rate very high for {role}: £{rate}")

        if rate < MIN_DAY_RATE:
            warnings.append(f"Day rate very low for {role}: £{rate}")

        if rate <= 0:
            errors.append(f"Invalid day rate for {role}: £{rate}")

    return errors, warnings


def validate_dates(start_date, end_date):
    """Validate contract dates."""
    errors = []
    warnings = []

    try:
        if start_date:
            start = datetime.fromisoformat(start_date).date()
        else:
            errors.append("Missing start date")
            return errors, warnings

        if end_date:
            end = datetime.fromisoformat(end_date).date()
        else:
            errors.append("Missing end date")
            return errors, warnings

        # Check if end date is after start date
        if end <= start:
            errors.append(f"End date ({end_date}) must be after start date ({start_date})")

        # Check if contract is in the past
        today = date.today()
        if end < today:
            warnings.append(f"Contract has already ended ({end_date})")

        # Check contract duration
        duration_days = (end - start).days
        if duration_days > 365 * 3:  # More than 3 years
            warnings.append(f"Contract duration is very long: {duration_days} days")

    except ValueError as e:
        errors.append(f"Invalid date format: {str(e)}")

    return errors, warnings


def validate_contract_value(contract_value):
    """Validate contract value."""
    errors = []
    warnings = []

    if contract_value is None:
        warnings.append("Contract value not specified")
        return errors, warnings

    if contract_value <= 0:
        errors.append(f"Invalid contract value: £{contract_value}")

    if contract_value > MAX_CONTRACT_VALUE:
        warnings.append(f"Very large contract value: £{contract_value:,.2f}")

    return errors, warnings


def lambda_handler(event, context):
    """
    Validate extracted structured data.

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
        "validation_errors": [...],
        "validation_warnings": [...]
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
            structured_data = message.get('structured_data', {})

            logger.info(f"🔍 Starting validation for {doc_id}")

            all_errors = []
            all_warnings = []

            # 3. Validate client name
            client_name = structured_data.get('client_name')
            if not client_name:
                all_errors.append("Missing client name")

            # 4. Validate contract value
            contract_value = structured_data.get('contract_value')
            errors, warnings = validate_contract_value(contract_value)
            all_errors.extend(errors)
            all_warnings.extend(warnings)

            # 5. Validate dates
            start_date = structured_data.get('start_date')
            end_date = structured_data.get('end_date')
            errors, warnings = validate_dates(start_date, end_date)
            all_errors.extend(errors)
            all_warnings.extend(warnings)

            # 6. Validate day rates
            day_rates = structured_data.get('day_rates', [])
            errors, warnings = validate_day_rates(day_rates)
            all_errors.extend(errors)
            all_warnings.extend(warnings)

            # 7. Determine if validation passed
            validation_passed = len(all_errors) == 0

            logger.info(f"{'✅' if validation_passed else '❌'} Validation complete")
            logger.info(f"   Errors: {len(all_errors)}")
            logger.info(f"   Warnings: {len(all_warnings)}")

            if all_errors:
                logger.warning(f"   Validation errors: {all_errors}")
            if all_warnings:
                logger.info(f"   Validation warnings: {all_warnings}")

            # 8. ADD results to message
            message['validation_passed'] = validation_passed
            message['validation_errors'] = all_errors
            message['validation_warnings'] = all_warnings

            # 9. Log outgoing message
            logger.info(f"📤 FORWARDING MESSAGE:")
            logger.info(json.dumps(message, indent=2))

            # 10. Send to next queue (even if validation failed - we still want to save it)
            if NEXT_QUEUE_URL:
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
                logger.info(f"✅ Message forwarded to save queue")

            logger.info(f"✅ STAGE COMPLETE for {doc_id}")

        except Exception as e:
            logger.error(f"❌ ERROR: {str(e)}")
            logger.error(f"   Message was: {json.dumps(message, indent=2)}")

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
