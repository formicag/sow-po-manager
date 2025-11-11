"""
Lambda: extract_text
Purpose: Extract text from PDF documents
Flow: SQS → extract_text → chunk queue
"""

import json
import boto3
import logging
import os
from datetime import datetime
from pypdf import PdfReader
from io import BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sqs = boto3.client('sqs')

BUCKET_NAME = os.environ.get('BUCKET_NAME')
NEXT_QUEUE_URL = os.environ.get('NEXT_QUEUE_URL')


def lambda_handler(event, context):
    """
    Extract text from PDF documents.

    Input (from SQS):
    {
        "document_id": "DOC#abc123",
        "s3_bucket": "sow-documents-xyz",
        "s3_key": "uploads/contract.pdf",
        "client_name": "VMO2",
        "uploaded_by": "gianluca@colibri.com",
        "timestamp": "2025-11-10T14:30:00Z",
        "errors": []
    }

    Output (adds to message):
    {
        ... (all input fields) ...,
        "text_extracted": true,
        "text_s3_key": "text/DOC#abc123.txt",
        "text_length": 45230,
        "page_count": 12
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
            s3_key = message['s3_key']

            logger.info(f"🔍 Starting text extraction for {doc_id}")
            logger.info(f"   S3 path: s3://{bucket}/{s3_key}")

            # 3. Download PDF from S3
            logger.info(f"⬇️  Downloading PDF from S3...")
            response = s3.get_object(Bucket=bucket, Key=s3_key)
            pdf_bytes = response['Body'].read()

            # 4. Extract text from PDF
            logger.info(f"📄 Extracting text from PDF...")
            pdf_file = BytesIO(pdf_bytes)
            pdf_reader = PdfReader(pdf_file)

            page_count = len(pdf_reader.pages)
            logger.info(f"   Found {page_count} pages")

            # Extract text from all pages
            full_text = ""
            for page_num, page in enumerate(pdf_reader.pages, 1):
                text = page.extract_text()
                full_text += f"\n--- Page {page_num} ---\n{text}"
                logger.info(f"   Extracted page {page_num}/{page_count}")

            text_length = len(full_text)
            logger.info(f"✅ Text extraction complete: {text_length} characters")

            # 5. Save extracted text to S3
            text_s3_key = f"text/{doc_id}.txt"
            logger.info(f"⬆️  Uploading text to S3: {text_s3_key}")

            s3.put_object(
                Bucket=bucket,
                Key=text_s3_key,
                Body=full_text.encode('utf-8'),
                ContentType='text/plain'
            )

            # 6. ADD results to message (don't replace!)
            message['text_extracted'] = True
            message['text_s3_key'] = text_s3_key
            message['text_length'] = text_length
            message['page_count'] = page_count

            # 7. Log outgoing message
            logger.info(f"📤 FORWARDING MESSAGE:")
            logger.info(json.dumps(message, indent=2))

            # 8. Send to next queue
            if NEXT_QUEUE_URL:
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
                logger.info(f"✅ Message forwarded to chunk queue")

            logger.info(f"✅ STAGE COMPLETE for {doc_id}")

        except Exception as e:
            logger.error(f"❌ ERROR: {str(e)}")
            logger.error(f"   Message was: {json.dumps(message, indent=2)}")

            # Add error to message
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'extract-text',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })

            # Re-raise so SQS retries → DLQ
            raise

    return {'statusCode': 200}
