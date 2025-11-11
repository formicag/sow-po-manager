"""
Unit tests for extract_structured_data Lambda function
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add Lambda to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'lambdas', 'extract_structured_data'))

from models import validate_sow_data


class TestModels:
    """Test data validation functions"""

    def test_validate_sow_data_valid_input(self):
        """Test validation with valid SOW data"""
        data = {
            "client_name": "TESCO MOBILE LIMITED",
            "contract_value": 44800,
            "start_date": "2025-10-01",
            "end_date": "2025-12-31",
            "po_number": "PO-12345",
            "day_rates": [
                {"role": "Solution Designer", "rate": 700, "currency": "GBP"}
            ],
            "signatures_present": True
        }

        result = validate_sow_data(data)

        assert result["client_name"] == "TESCO MOBILE LIMITED"
        assert result["contract_value"] == 44800.0
        assert result["start_date"] == "2025-10-01"
        assert result["end_date"] == "2025-12-31"
        assert result["po_number"] == "PO-12345"
        assert len(result["day_rates"]) == 1
        assert result["day_rates"][0]["role"] == "Solution Designer"
        assert result["day_rates"][0]["rate"] == 700.0
        assert result["signatures_present"] is True

    def test_validate_sow_data_minimal_input(self):
        """Test validation with minimal required data"""
        data = {
            "client_name": "Test Client"
        }

        result = validate_sow_data(data)

        assert result["client_name"] == "Test Client"
        assert result["contract_value"] is None
        assert result["start_date"] is None
        assert result["end_date"] is None
        assert result["po_number"] is None
        assert result["day_rates"] == []
        assert result["signatures_present"] is False

    def test_validate_sow_data_missing_client_name(self):
        """Test validation fails without client name"""
        data = {
            "contract_value": 10000
        }

        with pytest.raises(ValueError, match="client_name is required"):
            validate_sow_data(data)

    def test_validate_sow_data_empty_client_name(self):
        """Test validation fails with empty client name"""
        data = {
            "client_name": "   "
        }

        with pytest.raises(ValueError, match="client_name is required"):
            validate_sow_data(data)

    def test_validate_sow_data_type_coercion(self):
        """Test that types are properly coerced"""
        data = {
            "client_name": "Test Client",
            "contract_value": "50000",  # String should convert to float
            "signatures_present": 1  # Truthy value should convert to bool
        }

        result = validate_sow_data(data)

        assert result["contract_value"] == 50000.0
        assert result["signatures_present"] is True

    def test_validate_sow_data_invalid_contract_value(self):
        """Test handling of invalid contract value"""
        data = {
            "client_name": "Test Client",
            "contract_value": "invalid"
        }

        result = validate_sow_data(data)

        # Invalid values should be set to None
        assert result["contract_value"] is None

    def test_validate_sow_data_multiple_day_rates(self):
        """Test validation with multiple day rates"""
        data = {
            "client_name": "Test Client",
            "day_rates": [
                {"role": "Developer", "rate": 600, "currency": "GBP"},
                {"role": "Architect", "rate": 800, "currency": "GBP"},
                {"role": "Manager", "rate": 700, "currency": "GBP"}
            ]
        }

        result = validate_sow_data(data)

        assert len(result["day_rates"]) == 3
        assert result["day_rates"][0]["role"] == "Developer"
        assert result["day_rates"][1]["role"] == "Architect"
        assert result["day_rates"][2]["role"] == "Manager"


class TestExtractWithGemini:
    """Test Gemini extraction function"""

    @patch('handler.requests.post')
    def test_extract_with_gemini_success(self, mock_post):
        """Test successful Gemini extraction"""
        from handler import extract_with_gemini

        # Mock successful Gemini response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "client_name": "Test Client",
                            "contract_value": 10000,
                            "start_date": "2025-01-01",
                            "end_date": "2025-12-31",
                            "po_number": None,
                            "day_rates": [],
                            "signatures_present": False
                        })
                    }]
                }
            }],
            "usageMetadata": {},
            "modelVersion": "gemini-2.5-flash"
        }
        mock_post.return_value = mock_response

        result, confidence = extract_with_gemini("Sample text")

        assert result["client_name"] == "Test Client"
        assert result["contract_value"] == 10000.0
        assert confidence == 0.95

    @patch('handler.requests.post')
    def test_extract_with_gemini_with_markdown(self, mock_post):
        """Test Gemini extraction with markdown code blocks"""
        from handler import extract_with_gemini

        # Mock response with markdown code blocks
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": "```json\n" + json.dumps({
                            "client_name": "Test Client",
                            "contract_value": 5000,
                            "start_date": None,
                            "end_date": None,
                            "po_number": None,
                            "day_rates": [],
                            "signatures_present": False
                        }) + "\n```"
                    }]
                }
            }],
            "usageMetadata": {},
            "modelVersion": "gemini-2.5-flash"
        }
        mock_post.return_value = mock_response

        result, confidence = extract_with_gemini("Sample text")

        assert result["client_name"] == "Test Client"
        assert result["contract_value"] == 5000.0

    @patch('handler.requests.post')
    def test_extract_with_gemini_api_error(self, mock_post):
        """Test handling of Gemini API error"""
        from handler import extract_with_gemini

        # Mock API error response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": {
                "code": 500,
                "message": "Internal server error"
            }
        }
        mock_post.return_value = mock_response

        with pytest.raises(Exception, match="Gemini API error"):
            extract_with_gemini("Sample text")

    @patch('handler.requests.post')
    def test_extract_with_gemini_no_candidates(self, mock_post):
        """Test handling when no candidates in response"""
        from handler import extract_with_gemini

        # Mock response with no candidates
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [],
            "usageMetadata": {}
        }
        mock_post.return_value = mock_response

        with pytest.raises(Exception, match="No candidates in response"):
            extract_with_gemini("Sample text")


class TestLambdaHandler:
    """Test Lambda handler function"""

    @patch('handler.sqs')
    @patch('handler.s3')
    @patch('handler.extract_with_gemini')
    def test_lambda_handler_success(self, mock_extract, mock_s3, mock_sqs):
        """Test successful Lambda execution"""
        from handler import lambda_handler

        # Mock S3 get_object
        mock_s3.get_object.return_value = {
            'Body': Mock(read=lambda: b'Sample SOW document text')
        }

        # Mock Gemini extraction
        mock_extract.return_value = (
            {
                "client_name": "Test Client",
                "contract_value": 10000,
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "po_number": None,
                "day_rates": [],
                "signatures_present": False
            },
            0.95
        )

        # Create test event
        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test123',
                    's3_bucket': 'test-bucket',
                    'text_s3_key': 'text/DOC#test123.txt',
                    'timestamp': '2025-11-11T00:00:00Z'
                })
            }]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200
        mock_s3.get_object.assert_called_once()
        mock_extract.assert_called_once()
        mock_sqs.send_message.assert_called_once()

    @patch('handler.s3')
    def test_lambda_handler_s3_error(self, mock_s3):
        """Test Lambda handling of S3 errors"""
        from handler import lambda_handler

        # Mock S3 error
        mock_s3.get_object.side_effect = Exception("S3 error")

        event = {
            'Records': [{
                'body': json.dumps({
                    'document_id': 'DOC#test123',
                    's3_bucket': 'test-bucket',
                    'text_s3_key': 'text/DOC#test123.txt'
                })
            }]
        }

        with pytest.raises(Exception):
            lambda_handler(event, None)
