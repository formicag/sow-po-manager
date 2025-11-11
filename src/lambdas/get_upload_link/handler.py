"""
Lambda: get_upload_link
Purpose: Generate presigned S3 URL for document upload
"""

import json
import boto3
import logging
import os
import uuid
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')

BUCKET_NAME = os.environ.get('BUCKET_NAME')


def lambda_handler(event, context):
    """
    Generate presigned S3 URL for uploading documents.

    Input (API Gateway or direct invocation):
    {
        "client_name": "VMO2",
        "uploaded_by": "gianluca@colibri.com",
        "file_name": "contract.pdf"
    }

    Output:
    {
        "statusCode": 200,
        "body": {
            "upload_url": "https://...",
            "document_id": "DOC#abc123",
            "expires_in": 3600
        }
    }
    """

    try:
        # Parse request body
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event

        client_name = body.get('client_name', 'Unknown')
        uploaded_by = body.get('uploaded_by', 'unknown@example.com')
        file_name = body.get('file_name', 'document.pdf')

        # Generate unique document ID
        doc_id = f"DOC#{uuid.uuid4()}"
        timestamp = datetime.utcnow().isoformat()

        # S3 key structure: uploads/<doc_id>/<filename>
        s3_key = f"uploads/{doc_id}/{file_name}"

        logger.info(f"🔑 Generating presigned URL for {doc_id}")
        logger.info(f"   Client: {client_name}")
        logger.info(f"   Uploaded by: {uploaded_by}")
        logger.info(f"   S3 key: {s3_key}")

        # Generate presigned URL (valid for 1 hour)
        presigned_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': s3_key,
                'ContentType': 'application/pdf',
                'Metadata': {
                    'client_name': client_name,
                    'uploaded_by': uploaded_by,
                    'document_id': doc_id,
                    'timestamp': timestamp
                }
            },
            ExpiresIn=3600  # 1 hour
        )

        logger.info(f"✅ Presigned URL generated successfully")

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'upload_url': presigned_url,
                'document_id': doc_id,
                's3_key': s3_key,
                'expires_in': 3600,
                'instructions': 'Use PUT request to upload file to upload_url'
            })
        }

    except Exception as e:
        logger.error(f"❌ ERROR: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': str(e)
            })
        }
