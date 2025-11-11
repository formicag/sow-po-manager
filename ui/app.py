"""
Local Flask UI for SOW/PO Document Management
Features:
- Document upload to S3 via presigned URLs
- Document search and viewing
- Smart port selection (finds free port reliably)
"""

import os
import socket
import boto3
import json
import logging
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# AWS clients
lambda_client = boto3.client('lambda', region_name='eu-west-1')


def find_free_port(start_port=5000, max_port=5100):
    """
    Find a free port by actually binding to it.
    This ensures the reported port matches the actual port used.
    """
    for port in range(start_port, max_port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind(('127.0.0.1', port))
            sock.close()
            logger.info(f"✅ Found free port: {port}")
            return port
        except OSError:
            logger.debug(f"Port {port} is in use, trying next...")
            sock.close()
            continue

    raise RuntimeError(f"No free ports found in range {start_port}-{max_port}")


@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/api/get-upload-url', methods=['POST'])
def get_upload_url():
    """
    Get presigned S3 URL for document upload.

    Request body:
    {
        "client_name": "VMO2",
        "uploaded_by": "gianluca@colibri.com",
        "file_name": "contract.pdf"
    }
    """
    try:
        data = request.get_json()

        # Invoke Lambda function to get presigned URL
        response = lambda_client.invoke(
            FunctionName='sow-po-manager-get-upload-link',
            InvocationType='RequestResponse',
            Payload=json.dumps(data)
        )

        # Parse Lambda response
        result = json.loads(response['Payload'].read())

        if result.get('statusCode') == 200:
            body = json.loads(result['body'])
            return jsonify(body), 200
        else:
            return jsonify({'error': 'Failed to get upload URL'}), 500

    except Exception as e:
        logger.error(f"Error getting upload URL: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/search', methods=['POST'])
def search_documents():
    """
    Search documents.

    Request body:
    {
        "action": "list_all" | "search_by_client" | "get_document",
        "client_name": "VMO2" (optional),
        "document_id": "DOC#abc123" (optional)
    }
    """
    try:
        data = request.get_json()

        # Invoke search Lambda function
        response = lambda_client.invoke(
            FunctionName='sow-po-manager-search-api',
            InvocationType='RequestResponse',
            Payload=json.dumps(data)
        )

        # Parse Lambda response
        result = json.loads(response['Payload'].read())

        if result.get('statusCode') == 200:
            body = json.loads(result['body'])
            return jsonify(body), 200
        else:
            error_body = json.loads(result.get('body', '{}'))
            return jsonify(error_body), result.get('statusCode', 500)

    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'service': 'sow-po-manager-ui'}), 200


if __name__ == '__main__':
    # Find a free port (smart port selection)
    port = find_free_port(start_port=5000, max_port=5100)

    logger.info("=" * 60)
    logger.info("SOW/PO Document Management System - Local UI")
    logger.info("=" * 60)
    logger.info(f"🚀 Starting server on http://localhost:{port}")
    logger.info(f"📝 Press Ctrl+C to stop")
    logger.info("=" * 60)

    # Run Flask app
    app.run(
        host='127.0.0.1',
        port=port,
        debug=True,
        use_reloader=True
    )
