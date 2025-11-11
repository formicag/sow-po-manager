"""
Lambda: search_api
Purpose: Vector search and document queries
"""

import json
import boto3
import logging
import os
import numpy as np
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE')
table = dynamodb.Table(DYNAMODB_TABLE)


def decimal_default(obj):
    """JSON encoder for Decimal objects."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def generate_query_embedding(query_text):
    """Generate embedding for search query using Amazon Titan."""
    try:
        response = bedrock.invoke_model(
            modelId='amazon.titan-embed-text-v1',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'inputText': query_text
            })
        )

        response_body = json.loads(response['body'].read())
        embedding = response_body.get('embedding')

        return np.array(embedding)

    except Exception as e:
        logger.error(f"Failed to generate query embedding: {str(e)}")
        return None


def cosine_similarity(vec1, vec2):
    """Calculate cosine similarity between two vectors."""
    dot_product = np.dot(vec1, vec2)
    norm_vec1 = np.linalg.norm(vec1)
    norm_vec2 = np.linalg.norm(vec2)

    if norm_vec1 == 0 or norm_vec2 == 0:
        return 0.0

    return dot_product / (norm_vec1 * norm_vec2)


def search_by_client(client_name):
    """Search documents by client name using GSI1."""
    try:
        response = table.query(
            IndexName='ClientIndex',
            KeyConditionExpression='GSI1PK = :client_pk',
            ExpressionAttributeValues={
                ':client_pk': f"CLIENT#{client_name}"
            },
            ScanIndexForward=False  # Most recent first
        )

        return response.get('Items', [])

    except Exception as e:
        logger.error(f"Error searching by client: {str(e)}")
        return []


def search_all_documents():
    """Get all documents (LATEST pointers only)."""
    try:
        response = table.scan(
            FilterExpression='SK = :sk',
            ExpressionAttributeValues={
                ':sk': 'LATEST'
            }
        )

        return response.get('Items', [])

    except Exception as e:
        logger.error(f"Error scanning documents: {str(e)}")
        return []


def get_document_by_id(doc_id):
    """Get a specific document by ID (LATEST version)."""
    try:
        response = table.get_item(
            Key={
                'PK': doc_id,
                'SK': 'LATEST'
            }
        )

        return response.get('Item')

    except Exception as e:
        logger.error(f"Error getting document: {str(e)}")
        return None


def lambda_handler(event, context):
    """
    Search and query documents.

    Supported query types:
    1. List all documents:
       {"action": "list_all"}

    2. Search by client:
       {"action": "search_by_client", "client_name": "VMO2"}

    3. Get document by ID:
       {"action": "get_document", "document_id": "DOC#abc123"}

    4. Vector search (future):
       {"action": "vector_search", "query": "day rate for developers"}
    """

    try:
        # Parse request body
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event

        action = body.get('action', 'list_all')

        logger.info(f"🔍 Search request: {action}")

        # Route to appropriate handler
        if action == 'list_all':
            logger.info("📋 Listing all documents...")
            results = search_all_documents()

        elif action == 'search_by_client':
            client_name = body.get('client_name')
            if not client_name:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'client_name required'})
                }

            logger.info(f"🔍 Searching for client: {client_name}")
            results = search_by_client(client_name)

        elif action == 'get_document':
            doc_id = body.get('document_id')
            if not doc_id:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'document_id required'})
                }

            logger.info(f"📄 Getting document: {doc_id}")
            result = get_document_by_id(doc_id)
            results = [result] if result else []

        elif action == 'vector_search':
            query_text = body.get('query')
            if not query_text:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'query required'})
                }

            logger.info(f"🔎 Vector search: {query_text}")
            # TODO: Implement vector search
            results = []
            logger.warning("⚠️  Vector search not yet implemented")

        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown action: {action}'})
            }

        logger.info(f"✅ Found {len(results)} results")

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'count': len(results),
                'results': results
            }, default=decimal_default)
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
