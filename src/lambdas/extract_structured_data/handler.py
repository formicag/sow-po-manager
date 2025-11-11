"""
Lambda: extract_structured_data
Purpose: Extract structured data from documents using Google Vertex AI (Gemini Flash)
Flow: extraction queue → extract_structured_data → validation queue
"""

import json
import boto3
import logging
import os
from datetime import datetime
import requests
from models import validate_sow_data

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sqs = boto3.client('sqs')

BUCKET_NAME = os.environ.get('BUCKET_NAME')
NEXT_QUEUE_URL = os.environ.get('NEXT_QUEUE_URL')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Check API key
if GEMINI_API_KEY:
    logger.info(f"✅ Gemini API key configured")
else:
    logger.warning("⚠️  GEMINI_API_KEY not set")


EXTRACTION_PROMPT = """
You are a document analysis AI. Extract structured data from this Statement of Work (SOW) document.

Extract the following information:
1. Client name (company receiving the service)
2. Contract total value (in GBP)
3. Contract start date (ISO format: YYYY-MM-DD)
4. Contract end date (ISO format: YYYY-MM-DD)
5. Purchase Order (PO) number (if present)
6. Day rates (list of roles and their daily rates in GBP)
7. Whether signatures are present in the document

Return the data as a JSON object with this structure:
{{
    "client_name": "string",
    "contract_value": number (in GBP),
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "po_number": "string or null",
    "day_rates": [
        {{"role": "string", "rate": number, "currency": "GBP"}}
    ],
    "signatures_present": boolean
}}

If any field cannot be determined from the document, use null.

Document text:
{document_text}

Return ONLY valid JSON, no other text.
"""


def extract_with_gemini(text, max_retries=3):
    """Extract structured data using Gemini REST API."""
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not set")

    for attempt in range(max_retries):
        try:
            logger.info(f"🤖 Attempting Gemini extraction (attempt {attempt + 1}/{max_retries})")

            # Generate content with Gemini REST API
            prompt = EXTRACTION_PROMPT.format(document_text=text[:50000])  # Limit to 50k chars

            # Prepare request payload
            payload = {
                "contents": [{
                    "parts": [{
                        "text": prompt
                    }]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "topP": 0.95,
                    "topK": 40,
                    "maxOutputTokens": 2048,
                }
            }

            # Make API request
            response = requests.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            # Parse response
            result = response.json()
            logger.info(f"📡 API Response keys: {list(result.keys())}")

            # Check for error in response
            if 'error' in result:
                raise Exception(f"Gemini API error: {result['error']}")

            if 'candidates' not in result or not result['candidates']:
                raise Exception(f"No candidates in response: {result}")

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

            # Validate the extracted data
            validated_data = validate_sow_data(extracted_data)

            logger.info(f"✅ Extraction successful!")
            return validated_data, 0.95  # confidence score

        except json.JSONDecodeError as e:
            logger.warning(f"⚠️  JSON parse error on attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                raise

        except Exception as e:
            logger.error(f"❌ Extraction error on attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                raise

    raise Exception("Failed to extract data after max retries")


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
        # 1. Parse incoming message
        message = json.loads(record['body'])
        logger.info(f"📥 RECEIVED MESSAGE:")
        logger.info(json.dumps(message, indent=2))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']
            bucket = message.get('s3_bucket', BUCKET_NAME)
            text_s3_key = message['text_s3_key']

            logger.info(f"🔍 Starting structured extraction for {doc_id}")

            # 3. Download text from S3
            logger.info(f"⬇️  Downloading text from S3: {text_s3_key}")
            response = s3.get_object(Bucket=bucket, Key=text_s3_key)
            full_text = response['Body'].read().decode('utf-8')

            # 4. Extract structured data with Gemini
            structured_data, confidence = extract_with_gemini(full_text)

            logger.info(f"✅ Extracted data:")
            logger.info(json.dumps(structured_data, indent=2))

            # 5. ADD results to message
            message['structured_data'] = structured_data
            message['extraction_confidence'] = confidence

            # 6. Log outgoing message
            logger.info(f"📤 FORWARDING MESSAGE:")
            logger.info(json.dumps(message, indent=2))

            # 7. Send to next queue
            if NEXT_QUEUE_URL:
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
                logger.info(f"✅ Message forwarded to validation queue")

            logger.info(f"✅ STAGE COMPLETE for {doc_id}")

        except Exception as e:
            logger.error(f"❌ ERROR: {str(e)}")
            logger.error(f"   Message was: {json.dumps(message, indent=2)}")

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
