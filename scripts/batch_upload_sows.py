#!/usr/bin/env python3
"""
Batch upload SOW documents to the processing pipeline

This script:
1. Scans the SOWs/ directory for PDF files
2. Gets presigned upload URLs from get_upload_link Lambda
3. Uploads each PDF to S3
4. Monitors processing progress
"""

import os
import sys
import json
import time
import boto3
import requests
from pathlib import Path
from datetime import datetime

# AWS configuration
AWS_REGION = 'eu-west-1'
GET_UPLOAD_LINK_FUNCTION = 'sow-po-manager-get-upload-link'
DYNAMODB_TABLE = 'sow-po-manager-documents'

# Initialize AWS clients
lambda_client = boto3.client('lambda', region_name=AWS_REGION)
dynamodb = boto3.client('dynamodb', region_name=AWS_REGION)

def get_upload_link(filename):
    """Get presigned upload URL from Lambda"""
    payload = json.dumps({"filename": filename})

    response = lambda_client.invoke(
        FunctionName=GET_UPLOAD_LINK_FUNCTION,
        InvocationType='RequestResponse',
        Payload=payload.encode('utf-8')
    )

    result = json.loads(response['Payload'].read().decode('utf-8'))
    body = json.loads(result['body'])

    return body['upload_url'], body['document_id']


def upload_pdf(upload_url, pdf_path):
    """Upload PDF to presigned S3 URL"""
    with open(pdf_path, 'rb') as f:
        pdf_data = f.read()

    response = requests.put(
        upload_url,
        data=pdf_data,
        headers={'Content-Type': 'application/pdf'}
    )

    return response.status_code == 200


def check_document_status(document_id):
    """Check if document has been processed"""
    try:
        response = dynamodb.query(
            TableName=DYNAMODB_TABLE,
            KeyConditionExpression='PK = :pk AND SK = :sk',
            ExpressionAttributeValues={
                ':pk': {'S': document_id},
                ':sk': {'S': 'VERSION#1.0.0'}
            }
        )

        if response['Items']:
            item = response['Items'][0]
            has_structured_data = 'structured_data' in item
            return 'completed' if has_structured_data else 'processing'

        return 'not_found'
    except Exception as e:
        return 'error'


def main():
    """Main batch upload process"""
    # Find all PDF files in SOWs directory
    sows_dir = Path(__file__).parent.parent / 'SOWs'
    pdf_files = sorted(sows_dir.glob('*.pdf'))

    if not pdf_files:
        print("❌ No PDF files found in SOWs/ directory")
        return

    print(f"\n{'='*60}")
    print(f"  SOW Batch Upload - {len(pdf_files)} documents found")
    print(f"{'='*60}\n")

    uploaded = []
    failed = []

    for i, pdf_path in enumerate(pdf_files, 1):
        filename = pdf_path.name
        print(f"[{i}/{len(pdf_files)}] Processing: {filename}")

        try:
            # Get upload link
            print(f"  → Getting upload link...")
            upload_url, doc_id = get_upload_link(filename)

            # Upload PDF
            print(f"  → Uploading PDF...")
            success = upload_pdf(upload_url, pdf_path)

            if success:
                print(f"  ✅ Uploaded successfully!")
                print(f"     Document ID: {doc_id}")
                uploaded.append({
                    'filename': filename,
                    'document_id': doc_id,
                    'timestamp': datetime.now().isoformat()
                })
            else:
                print(f"  ❌ Upload failed")
                failed.append(filename)

            # Small delay between uploads to avoid rate limits
            time.sleep(1)

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            failed.append(filename)

        print()

    # Summary
    print(f"\n{'='*60}")
    print(f"  Upload Complete")
    print(f"{'='*60}")
    print(f"✅ Uploaded: {len(uploaded)}/{len(pdf_files)} documents")
    if failed:
        print(f"❌ Failed: {len(failed)} documents")
        for f in failed:
            print(f"   - {f}")

    # Save upload manifest
    manifest_path = Path(__file__).parent.parent / 'upload_manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump({
            'upload_date': datetime.now().isoformat(),
            'total_files': len(pdf_files),
            'uploaded': uploaded,
            'failed': failed
        }, f, indent=2)

    print(f"\n📄 Upload manifest saved to: upload_manifest.json")

    # Monitor processing
    if uploaded:
        print(f"\n{'='*60}")
        print(f"  Monitoring Processing (Ctrl+C to stop)")
        print(f"{'='*60}\n")
        print("Waiting 30 seconds for pipeline to start...")
        time.sleep(30)

        completed_count = 0
        max_checks = 20  # Check for ~10 minutes

        for check in range(max_checks):
            print(f"\nCheck {check + 1}/{max_checks}...")

            for doc in uploaded:
                if doc.get('completed'):
                    continue

                status = check_document_status(doc['document_id'])

                if status == 'completed':
                    doc['completed'] = True
                    completed_count += 1
                    print(f"  ✅ {doc['filename'][:50]:<50} - COMPLETED")
                elif status == 'processing':
                    print(f"  ⏳ {doc['filename'][:50]:<50} - Processing...")
                else:
                    print(f"  ⏸️  {doc['filename'][:50]:<50} - Pending...")

            if completed_count == len(uploaded):
                print(f"\n🎉 All {len(uploaded)} documents processed successfully!")
                break

            if check < max_checks - 1:
                print(f"\nProgress: {completed_count}/{len(uploaded)} completed")
                print("Waiting 30 seconds...")
                time.sleep(30)

        if completed_count < len(uploaded):
            print(f"\n⏸️  Processing still in progress: {completed_count}/{len(uploaded)} completed")
            print("   Check DynamoDB or CloudWatch Logs for details")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏸️  Upload interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        sys.exit(1)
