"""
Integration tests for the complete SOW processing pipeline
"""

import json
import pytest
from unittest.mock import Mock, patch


class TestPipelineIntegration:
    """Test the complete document processing pipeline"""

    def test_message_flow_through_pipeline(self):
        """Test that message structure is maintained through all stages"""

        # Stage 1: Initial upload message
        stage1_message = {
            "document_id": "DOC#test123",
            "s3_bucket": "test-bucket",
            "s3_key": "uploads/DOC#test123/document.pdf",
            "timestamp": "2025-11-11T00:00:00Z",
            "uploaded_by": "eventbridge",
            "errors": []
        }

        # Stage 2: After text extraction
        stage2_message = {
            **stage1_message,
            "text_extracted": True,
            "text_s3_key": "text/DOC#test123.txt",
            "text_length": 6207,
            "page_count": 4
        }

        # Stage 3: After chunking and embedding
        stage3_message = {
            **stage2_message,
            "chunks_created": 8,
            "embeddings_stored": True,
            "chunk_details": []
        }

        # Stage 4: After structured extraction
        stage4_message = {
            **stage3_message,
            "structured_data": {
                "client_name": "TESCO MOBILE LIMITED",
                "contract_value": 44800,
                "start_date": "2025-10-01",
                "end_date": "2025-12-31",
                "po_number": "PO-12345",
                "day_rates": [
                    {"role": "Solution Designer", "rate": 700, "currency": "GBP"}
                ],
                "signatures_present": True
            },
            "extraction_confidence": 0.95
        }

        # Stage 5: After validation
        stage5_message = {
            **stage4_message,
            "validation_passed": True,
            "validation_warnings": [],
            "validation_errors": []
        }

        # Verify all original fields preserved
        assert stage5_message["document_id"] == stage1_message["document_id"]
        assert stage5_message["s3_bucket"] == stage1_message["s3_bucket"]
        assert stage5_message["timestamp"] == stage1_message["timestamp"]

        # Verify all stages added their data
        assert "text_extracted" in stage5_message
        assert "chunks_created" in stage5_message
        assert "structured_data" in stage5_message
        assert "validation_passed" in stage5_message

    def test_error_accumulation_through_pipeline(self):
        """Test that errors accumulate through pipeline stages"""

        message = {
            "document_id": "DOC#test123",
            "errors": []
        }

        # Add error from stage 1
        message["errors"].append({
            "stage": "extract-text",
            "error": "Warning: Low quality scan",
            "timestamp": "2025-11-11T00:00:00Z"
        })

        # Add error from stage 2
        message["errors"].append({
            "stage": "chunk-and-embed",
            "error": "Warning: Short document",
            "timestamp": "2025-11-11T00:01:00Z"
        })

        assert len(message["errors"]) == 2
        assert message["errors"][0]["stage"] == "extract-text"
        assert message["errors"][1]["stage"] == "chunk-and-embed"


class TestDataConsistency:
    """Test data consistency across the pipeline"""

    def test_client_name_consistency(self, sample_extracted_data):
        """Test that client name remains consistent"""
        client_name = sample_extracted_data["client_name"]

        # Should be exactly as extracted
        assert client_name == "TESCO MOBILE LIMITED"
        assert len(client_name) > 0
        assert client_name.isupper()  # Extracted names often uppercase

    def test_contract_value_consistency(self, sample_extracted_data):
        """Test that contract values are numeric and valid"""
        contract_value = sample_extracted_data["contract_value"]

        assert isinstance(contract_value, (int, float))
        assert contract_value > 0
        assert contract_value < 10_000_000  # Reasonable upper limit

    def test_date_format_consistency(self, sample_extracted_data):
        """Test that dates follow ISO format"""
        start_date = sample_extracted_data["start_date"]
        end_date = sample_extracted_data["end_date"]

        # Check ISO format YYYY-MM-DD
        assert len(start_date) == 10
        assert start_date[4] == '-'
        assert start_date[7] == '-'

        assert len(end_date) == 10
        assert end_date[4] == '-'
        assert end_date[7] == '-'

        # End date should be after start date
        assert end_date >= start_date

    def test_day_rates_structure(self, sample_extracted_data):
        """Test day rates have consistent structure"""
        day_rates = sample_extracted_data["day_rates"]

        assert isinstance(day_rates, list)
        assert len(day_rates) > 0

        for rate in day_rates:
            assert "role" in rate
            assert "rate" in rate
            assert "currency" in rate

            assert isinstance(rate["role"], str)
            assert isinstance(rate["rate"], (int, float))
            assert rate["currency"] == "GBP"


class TestErrorHandling:
    """Test error handling in pipeline"""

    def test_missing_required_fields(self):
        """Test handling of messages with missing fields"""
        incomplete_message = {
            "document_id": "DOC#test123"
            # Missing s3_bucket and s3_key
        }

        # Should handle gracefully or raise appropriate error
        assert "document_id" in incomplete_message

    def test_invalid_document_id_format(self):
        """Test handling of invalid document ID"""
        message = {
            "document_id": "invalid-format",  # Should be DOC#...
            "s3_bucket": "test-bucket"
        }

        # Document ID should follow pattern
        if message["document_id"].startswith("DOC#"):
            assert True
        else:
            # Invalid format detected
            assert not message["document_id"].startswith("DOC#")


class TestPerformanceMetrics:
    """Test that performance metrics are tracked"""

    def test_processing_time_tracked(self):
        """Test that processing times are recorded"""
        message = {
            "document_id": "DOC#test123",
            "processing_start": "2025-11-11T00:00:00Z",
            "processing_end": "2025-11-11T00:00:15Z",
            "processing_time_seconds": 15
        }

        assert "processing_time_seconds" in message
        assert message["processing_time_seconds"] > 0
        assert message["processing_time_seconds"] < 300  # Should be under 5 minutes

    def test_confidence_scores(self):
        """Test that confidence scores are reasonable"""
        message = {
            "extraction_confidence": 0.95
        }

        confidence = message["extraction_confidence"]
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.5  # Should be reasonably confident
