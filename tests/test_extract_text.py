"""
Unit tests for extract_text Lambda function
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from io import BytesIO

# Set required environment variables BEFORE importing handler
os.environ.setdefault('BUCKET_NAME', 'test-bucket')
os.environ.setdefault('NEXT_QUEUE_URL', 'https://sqs.test.local/next')

# Add Lambda to path with specific name to avoid conflicts
extract_text_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'lambdas', 'extract_text')
if extract_text_path not in sys.path:
    sys.path.insert(0, extract_text_path)


class TestExtractText:
    """Test PDF text extraction"""

    @patch('sys.modules')
    def test_lambda_handler_success(self, mock_modules):
        """Test successful PDF text extraction"""
        # Import handler fresh
        import importlib
        if 'handler' in sys.modules:
            del sys.modules['handler']

        sys.path.insert(0, extract_text_path)
        import handler

        # Mock AWS clients
        handler.sqs = Mock()
        handler.s3 = Mock()

        # Mock PdfReader
        from unittest.mock import MagicMock
        mock_page1 = Mock()
        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2 = Mock()
        mock_page2.extract_text.return_value = "Page 2 content"
        mock_reader = Mock()
        mock_reader.pages = [mock_page1, mock_page2]

        # Mock S3
        handler.s3.get_object.return_value = {'Body': Mock(read=lambda: b'%PDF-1.4 mock pdf content')}

        # Patch PdfReader
        with patch('handler.PdfReader', return_value=mock_reader):
            event = {
                'Records': [{
                    'body': json.dumps({
                        'document_id': 'DOC#test123',
                        's3_bucket': 'test-bucket',
                        's3_key': 'uploads/DOC#test123/document.pdf',
                        'timestamp': '2025-11-11T00:00:00Z'
                    })
                }]
            }

            result = handler.lambda_handler(event, None)

            assert result['statusCode'] == 200
            handler.s3.get_object.assert_called_once()
            handler.s3.put_object.assert_called_once()
            handler.sqs.send_message.assert_called_once()

        # Mock S3 get_object
        mock_pdf_content = b'%PDF-1.4 mock pdf content'
        mock_s3.get_object.return_value = {
            'Body': Mock(read=lambda: mock_pdf_content)
        }

        # Mock PdfReader
        mock_page1 = Mock()
        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2 = Mock()
        mock_page2.extract_text.return_value = "Page 2 content"

        mock_reader = Mock()
        mock_reader.pages = [mock_page1, mock_page2]
        mock_pdf_reader.return_value = mock_reader

        # Create test event
        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test123',
                    's3_bucket': 'test-bucket',
                    's3_key': 'uploads/DOC#test123/document.pdf',
                    'timestamp': '2025-11-11T00:00:00Z'
                })
            }]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200
        mock_s3.get_object.assert_called_once()
        mock_s3.put_object.assert_called_once()
        mock_sqs.send_message.assert_called_once()

    @patch('handler.s3')
    def test_lambda_handler_pdf_error(self, mock_s3):
        """Test handling of PDF processing errors"""
        from handler import lambda_handler

        # Mock S3 to return invalid PDF
        mock_s3.get_object.return_value = {
            'Body': Mock(read=lambda: b'not a pdf')
        }

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test123',
                    's3_bucket': 'test-bucket',
                    's3_key': 'uploads/test.pdf'
                })
            }]
        }

        with pytest.raises(Exception):
            lambda_handler(event, None)

    @patch('handler.sqs')
    @patch('handler.s3')
    @patch('handler.PdfReader')
    def test_lambda_handler_empty_pdf(self, mock_pdf_reader, mock_s3, mock_sqs):
        """Test extraction from empty PDF"""
        from handler import lambda_handler

        # Mock empty PDF
        mock_s3.get_object.return_value = {
            'Body': Mock(read=lambda: b'%PDF-1.4')
        }

        mock_reader = Mock()
        mock_reader.pages = []
        mock_pdf_reader.return_value = mock_reader

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test123',
                    's3_bucket': 'test-bucket',
                    's3_key': 'uploads/empty.pdf'
                })
            }]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200
        # Should still process but with empty text


class TestMessageContract:
    """Test that message contract is maintained"""

    @patch('handler.sqs')
    @patch('handler.s3')
    @patch('handler.PdfReader')
    def test_message_fields_preserved(self, mock_pdf_reader, mock_s3, mock_sqs):
        """Test that all input fields are preserved in output"""
        from handler import lambda_handler

        # Setup mocks
        mock_s3.get_object.return_value = {
            'Body': Mock(read=lambda: b'%PDF-1.4')
        }

        mock_page = Mock()
        mock_page.extract_text.return_value = "Test content"
        mock_reader = Mock()
        mock_reader.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader

        # Input message with extra fields
        input_message = {
            'document_id': 'DOC#test123',
            's3_bucket': 'test-bucket',
            's3_key': 'uploads/test.pdf',
            'timestamp': '2025-11-11T00:00:00Z',
            'uploaded_by': 'test@example.com',
            'custom_field': 'custom_value'
        }

        event = {
            'Records': [{
                'body': json.dumps(input_message)
            }]
        }

        lambda_handler(event, None)

        # Get the message sent to SQS
        call_args = mock_sqs.send_message.call_args
        sent_message = json.loads(call_args[1]['MessageBody'])

        # All original fields should be preserved
        assert sent_message['document_id'] == input_message['document_id']
        assert sent_message['s3_bucket'] == input_message['s3_bucket']
        assert sent_message['timestamp'] == input_message['timestamp']
        assert sent_message['custom_field'] == input_message['custom_field']

        # New fields should be added
        assert 'text_extracted' in sent_message
        assert 'text_s3_key' in sent_message
        assert 'text_length' in sent_message
        assert 'page_count' in sent_message
