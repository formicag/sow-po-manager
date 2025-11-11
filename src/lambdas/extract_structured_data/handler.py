"""
Lambda: extract_structured_data
Purpose: Extract structured data from documents using Google Vertex AI (Gemini Flash)
Flow: extraction queue → extract_structured_data → validation queue
"""

import json
import boto3
import logging
import os
import time
from datetime import datetime
import requests
from schema import validate_sow_data_strict, SchemaValidationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sqs = boto3.client('sqs')

BUCKET_NAME = os.environ['BUCKET_NAME']  # Required
NEXT_QUEUE_URL = os.environ['NEXT_QUEUE_URL']  # Required
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']  # Required
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Validation constants
MAX_TEXT_LENGTH = 50000  # Truncate to prevent prompt injection
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff delays (seconds)


EXTRACTION_PROMPT = """
You are a document analysis AI. Extract structured data from this Statement of Work (SOW) document.

Extract the following information:
1. Client name (company receiving the service)
2. Contract total value (in GBP)
3. Contract start date (ISO format: YYYY-MM-DD)
4. Contract end date (ISO format: YYYY-MM-DD)
5. Purchase Order (PO) number (if present)
6. IR35 status ("Inside", "Outside", or "Not Specified")
7. Day rates (list of roles and their daily rates)
8. Whether signatures are present in the document

Return ONLY the following JSON structure, with no extra fields:
{{
    "client_name": "string",
    "contract_value": number_or_null,
    "start_date": "YYYY-MM-DD_or_null",
    "end_date": "YYYY-MM-DD_or_null",
    "po_number": "string_or_null",
    "ir35_status": "Inside" | "Outside" | "Not Specified" | null,
    "day_rates": [
        {{"role": "string", "rate": number, "currency": "GBP"}}
    ],
    "signatures_present": true_or_false
}}

IMPORTANT: Do not add any extra fields. Only use the exact field names shown above.
If any field cannot be determined, use null.

Document text (truncated to 50000 chars):
{doc_text}

Return ONLY valid JSON, no markdown, no explanation.
"""


def sanitize_text_for_prompt(text: str) -> str:
    """
    Sanitize user text before inserting into prompt.
    Prevents prompt injection by escaping special characters.
    """
    # Truncate to max length
    text = text[:MAX_TEXT_LENGTH]

    # Remove null bytes and other problematic characters
    text = text.replace('\x00', '')

    # No need to escape braces - we use .format() with keyword args
    return text


def extract_with_gemini(text: str) -> tuple:
    """
    Extract structured data using Gemini REST API.
    Returns (validated_data, confidence_score).
    Raises SchemaValidationError if LLM output doesn't match schema.
    """
    # Sanitize input
    safe_text = sanitize_text_for_prompt(text)

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            logger.info("gemini attempt=%d", attempt + 1)

            # Build prompt with sanitized text
            prompt = EXTRACTION_PROMPT.format(doc_text=safe_text)

            # Prepare request payload
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "topP": 0.95,
                    "topK": 40,
                    "maxOutputTokens": 2048,
                }
            }

            # Make API request with timeout
            response = requests.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            # Parse response
            result = response.json()

            # Check for error in response
            if 'error' in result:
                raise Exception(f"Gemini API error: {result['error'].get('message', result['error'])}")

            if 'candidates' not in result or not result['candidates']:
                raise Exception("No candidates in Gemini response")

            json_text = result['candidates'][0]['content']['parts'][0]['text'].strip()

            # Remove markdown code blocks if present
            if json_text.startswith('```json'):
                json_text = json_text[7:]
            if json_text.startswith('```'):
                json_text = json_text[3:]
            if json_text.endswith('```'):
                json_text = json_text[:-3]

            json_text = json_text.strip()

            # Parse JSON
            extracted_data = json.loads(json_text)

            # Strict schema validation (rejects extra fields)
            validated_data = validate_sow_data_strict(extracted_data)

            logger.info("extraction success fields=%s", list(validated_data.keys()))
            return validated_data, 0.95  # confidence score

        except SchemaValidationError as e:
            logger.error("schema_error code=%s field=%s msg=%s", e.code, e.field, str(e))
            # Don't retry schema errors - LLM needs different prompt
            raise

        except json.JSONDecodeError as e:
            logger.warning("json_parse_error attempt=%d", attempt + 1)
            if attempt >= len(RETRY_DELAYS):
                raise Exception(f"JSON parse error after {attempt + 1} attempts: {str(e)}")

        except Exception as e:
            logger.error("extraction_error attempt=%d msg=%s", attempt + 1, str(e))
            if attempt >= len(RETRY_DELAYS):
                raise

        # Exponential backoff
        if attempt < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[attempt]
            logger.info("retry_delay seconds=%d", delay)
            time.sleep(delay)


def lambda_handler(event, context):
    """
    Extract structured data using Vertex AI Gemini Flash.

    Input (from SQS):
    {
        ... (previous fields) ...,
        "text_s3_key": "text/DOC#abc123.txt"
    }

    Output (adds to message):
    {
        ... (all input fields) ...,
        "structured_data": {
            "client_name": "Virgin Media O2",
            "contract_value": 500000,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "day_rates": [...]
        },
        "extraction_confidence": 0.95
    }
    """

    for record in event['Records']:
        # 1. Parse incoming message (log keys only, no PII)
        message = json.loads(record['body'])
        logger.info("received keys=%s", list(message.keys()))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']
            bucket = message.get('s3_bucket', BUCKET_NAME)
            text_s3_key = message['text_s3_key']

            logger.info("start_extraction doc_id=%s", doc_id)

            # 3. Download text from S3
            logger.info("download_text s3_key=%s", text_s3_key)
            response = s3.get_object(Bucket=bucket, Key=text_s3_key)
            full_text = response['Body'].read().decode('utf-8')
            logger.info("text_length=%d", len(full_text))

            # 4. Extract structured data with Gemini
            structured_data, confidence = extract_with_gemini(full_text)

            # 5. ADD results to message
            message['structured_data'] = structured_data
            message['extraction_confidence'] = confidence

            # 6. Log outgoing message (keys only, no PII)
            logger.info("forwarding keys=%s", list(message.keys()))

            # 7. Send to next queue
            sqs.send_message(
                QueueUrl=NEXT_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            logger.info("forwarded to_queue=validation")

            logger.info("stage_complete doc_id=%s", doc_id)

        except Exception as e:
            logger.error("error stage=extract-structured-data msg=%s", str(e))
            logger.error("failed keys=%s", list(message.keys()))

            # Add error to message
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'extract-structured-data',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })

            # Re-raise so SQS retries → DLQ
            raise

    return {'statusCode': 200}
