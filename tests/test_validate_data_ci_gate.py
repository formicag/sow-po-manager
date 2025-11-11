# tests/test_validate_data_ci_gate.py
import json
import os
import sys
from pathlib import Path
import importlib
import pytest

# ---------- Fake AWS clients ----------

class FakeSQS:
    def __init__(self):
        self.sent = []  # list of {"QueueUrl":..., "MessageBody":...}

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": "m-1"}


# ---------- Test harness helpers ----------

def _import_handler_with_env(monkeypatch, queue="https://sqs.local/save"):
    """Import handler with required env vars set."""
    monkeypatch.setenv("NEXT_QUEUE_URL", queue)

    # Ensure project root on path
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Also add the Lambda directory to path so validation_rules.py can be imported
    lambda_dir = root / "src" / "lambdas" / "validate_data"
    if str(lambda_dir) not in sys.path:
        sys.path.insert(0, str(lambda_dir))

    # Import (or reload) the handler
    mod = importlib.import_module("src.lambdas.validate_data.handler")
    mod = importlib.reload(mod)
    return mod


def _fake_world(mod, fake_sqs):
    """Monkeypatch module-level AWS clients."""
    mod.sqs = fake_sqs


def _mk_event(document_id="DOC#test", structured_data=None):
    """Create a fake SQS event."""
    if structured_data is None:
        structured_data = {
            "client_name": "Test Corp",
            "contract_value": 100000,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "po_number": "PO-123",
            "ir35_status": "Outside",
            "day_rates": [{"role": "Consultant", "rate": 500, "currency": "GBP"}],
            "signatures_present": True
        }

    msg = {
        "document_id": document_id,
        "s3_bucket": "bkt",
        "structured_data": structured_data
    }
    return {"Records": [{"body": json.dumps(msg)}]}


# ---------- Tests ----------

def test_error_code_determinism(monkeypatch):
    """
    Gate #1: Same invalid input should always produce same error codes
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # Invalid data: missing client_name, end_date before start_date, negative contract value
    invalid_data = {
        "client_name": "",  # Empty (required)
        "contract_value": -1000,  # Negative (invalid)
        "start_date": "2025-12-31",
        "end_date": "2025-01-01",  # Before start date (error)
        "po_number": None,
        "ir35_status": None,
        "day_rates": [{"role": "Test", "rate": -100, "currency": "GBP"}],  # Negative rate
        "signatures_present": False
    }

    event = _mk_event(structured_data=invalid_data)

    # Run twice
    result1 = mod.lambda_handler(event, None)
    msg1 = json.loads(fake_sqs.sent[0]["MessageBody"])
    error_codes1 = sorted([e["code"] for e in msg1["validation_errors"]])

    fake_sqs.sent.clear()

    result2 = mod.lambda_handler(event, None)
    msg2 = json.loads(fake_sqs.sent[0]["MessageBody"])
    error_codes2 = sorted([e["code"] for e in msg2["validation_errors"]])

    # Error codes should be identical (deterministic)
    assert error_codes1 == error_codes2

    # Expected error codes
    assert "VAL_CLIENT_MISSING" in error_codes1 or "VAL_SCHEMA_EMPTY" in error_codes1
    assert "VAL_DATE_RANGE" in error_codes1
    assert "VAL_VALUE_INVALID" in error_codes1
    assert "VAL_RATE_INVALID" in error_codes1


def test_pii_safe_logging_no_values(monkeypatch, caplog):
    """
    Gate #2: CloudWatch logs must NOT contain PII (client names, contract values, rates)
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # Data with PII
    pii_data = {
        "client_name": "Super Secret Bank Ltd",
        "contract_value": 5000000,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "po_number": "PO-CONFIDENTIAL-999",
        "ir35_status": "Inside",
        "day_rates": [
            {"role": "Managing Director", "rate": 1500, "currency": "GBP"},
            {"role": "Senior Partner", "rate": 2000, "currency": "GBP"}
        ],
        "signatures_present": True
    }

    event = _mk_event(structured_data=pii_data)

    with caplog.at_level("INFO"):
        result = mod.lambda_handler(event, None)

    assert result["statusCode"] == 200

    # Verify NO PII in logs
    log_text = " ".join([r.message for r in caplog.records])

    # Should NOT contain client name
    assert "Super Secret Bank" not in log_text
    assert "Secret Bank" not in log_text

    # Should NOT contain contract value
    assert "5000000" not in log_text
    assert "5,000,000" not in log_text

    # Should NOT contain PO number
    assert "CONFIDENTIAL-999" not in log_text

    # Should NOT contain role names
    assert "Managing Director" not in log_text
    assert "Senior Partner" not in log_text

    # Should NOT contain day rates
    assert "1500" not in log_text
    assert "2000" not in log_text

    # SHOULD contain safe logging (keys only, codes only, counts only)
    assert "received keys=" in log_text or "keys=" in log_text
    assert "doc_id=DOC#test" in log_text or "DOC#test" in log_text

    # If there are warnings, should log codes only
    msg = json.loads(fake_sqs.sent[0]["MessageBody"])
    if msg["validation_warnings"]:
        # Warning codes might be logged, but not the actual values
        assert "codes=" in log_text or "VAL_" in log_text


def test_table_driven_validation_all_rules(monkeypatch):
    """
    Gate #3: All validation rules should execute from VALIDATION_RULES table
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # Import validation_rules to count rules
    from src.lambdas.validate_data.validation_rules import VALIDATION_RULES

    # At least 10 rules should exist
    assert len(VALIDATION_RULES) >= 10

    # Run validation with valid data
    valid_data = {
        "client_name": "Test Corp",
        "contract_value": 100000,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "po_number": None,
        "ir35_status": "Outside",
        "day_rates": [{"role": "Consultant", "rate": 500, "currency": "GBP"}],
        "signatures_present": True
    }

    event = _mk_event(structured_data=valid_data)
    result = mod.lambda_handler(event, None)

    assert result["statusCode"] == 200
    msg = json.loads(fake_sqs.sent[0]["MessageBody"])

    # Should pass with no errors
    assert msg["validation_passed"] is True
    assert len(msg["validation_errors"]) == 0


def test_next_queue_url_required(monkeypatch):
    """
    Gate #4: Missing NEXT_QUEUE_URL should raise KeyError at module import
    """
    # Deliberately omit NEXT_QUEUE_URL
    monkeypatch.delenv("NEXT_QUEUE_URL", raising=False)

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Add Lambda directory to path
    lambda_dir = root / "src" / "lambdas" / "validate_data"
    if str(lambda_dir) not in sys.path:
        sys.path.insert(0, str(lambda_dir))

    # Remove modules from cache
    if "src.lambdas.validate_data.handler" in sys.modules:
        del sys.modules["src.lambdas.validate_data.handler"]
    if "validation_rules" in sys.modules:
        del sys.modules["validation_rules"]

    with pytest.raises(KeyError, match="NEXT_QUEUE_URL"):
        importlib.import_module("src.lambdas.validate_data.handler")


def test_structured_violations_format(monkeypatch):
    """
    Gate #5: Each violation must have {code, message, field, severity}
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # Invalid data to trigger multiple violations
    invalid_data = {
        "client_name": "",  # VAL_CLIENT_MISSING
        "contract_value": -1000,  # VAL_VALUE_INVALID
        "start_date": "2025-12-31",
        "end_date": "2025-01-01",  # VAL_DATE_RANGE
        "po_number": None,
        "ir35_status": None,
        "day_rates": [{"role": "Test", "rate": 0, "currency": "GBP"}],  # VAL_RATE_INVALID
        "signatures_present": False
    }

    event = _mk_event(structured_data=invalid_data)
    result = mod.lambda_handler(event, None)

    msg = json.loads(fake_sqs.sent[0]["MessageBody"])

    # Should have errors
    assert len(msg["validation_errors"]) > 0

    # Each error must have correct structure
    for error in msg["validation_errors"]:
        assert "code" in error
        assert "message" in error
        assert "field" in error
        assert "severity" in error

        # Code should start with VAL_
        assert error["code"].startswith("VAL_")

        # Severity should be "error"
        assert error["severity"] == "error"

        # Message should be non-empty string
        assert isinstance(error["message"], str)
        assert len(error["message"]) > 0

        # Field should be non-empty string
        assert isinstance(error["field"], str)
        assert len(error["field"]) > 0


def test_validation_warnings_non_blocking(monkeypatch):
    """
    Gate #6: Warnings should not block processing (validation_passed=True even with warnings)
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # Data that triggers warnings but no errors
    warning_data = {
        "client_name": "Test Corp",
        "contract_value": 15000000,  # VAL_VALUE_HIGH (warning, not error)
        "start_date": "2020-01-01",
        "end_date": "2024-01-01",  # VAL_DATE_PAST (warning, already ended)
        "po_number": None,
        "ir35_status": None,
        "day_rates": [
            {"role": "Consultant", "rate": 100, "currency": "GBP"}  # VAL_RATE_LOW (warning)
        ],
        "signatures_present": True
    }

    event = _mk_event(structured_data=warning_data)
    result = mod.lambda_handler(event, None)

    assert result["statusCode"] == 200
    msg = json.loads(fake_sqs.sent[0]["MessageBody"])

    # Should pass validation despite warnings
    assert msg["validation_passed"] is True
    assert len(msg["validation_errors"]) == 0

    # But should have warnings
    assert len(msg["validation_warnings"]) > 0

    # Each warning should have correct structure
    for warning in msg["validation_warnings"]:
        assert "code" in warning
        assert "severity" in warning
        assert warning["severity"] == "warning"


def test_date_range_validation(monkeypatch):
    """
    Gate #7: Date range validation (end must be after start)
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # End date before start date
    invalid_dates = {
        "client_name": "Test Corp",
        "contract_value": 100000,
        "start_date": "2025-12-31",
        "end_date": "2025-01-01",  # Before start
        "po_number": None,
        "ir35_status": None,
        "day_rates": [],
        "signatures_present": True
    }

    event = _mk_event(structured_data=invalid_dates)
    result = mod.lambda_handler(event, None)

    msg = json.loads(fake_sqs.sent[0]["MessageBody"])

    # Should fail validation
    assert msg["validation_passed"] is False

    # Should have VAL_DATE_RANGE error
    error_codes = [e["code"] for e in msg["validation_errors"]]
    assert "VAL_DATE_RANGE" in error_codes


def test_rate_validation_boundaries(monkeypatch):
    """
    Gate #8: Day rate validation (must be positive, warn if too high/low)
    """
    mod = _import_handler_with_env(monkeypatch)
    fake_sqs = FakeSQS()
    _fake_world(mod, fake_sqs)

    # Zero/negative rate (error)
    zero_rate_data = {
        "client_name": "Test Corp",
        "contract_value": 100000,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "po_number": None,
        "ir35_status": None,
        "day_rates": [{"role": "Test", "rate": 0, "currency": "GBP"}],
        "signatures_present": True
    }

    event = _mk_event(structured_data=zero_rate_data)
    result = mod.lambda_handler(event, None)

    msg = json.loads(fake_sqs.sent[0]["MessageBody"])

    # Should fail with VAL_RATE_INVALID
    assert msg["validation_passed"] is False
    error_codes = [e["code"] for e in msg["validation_errors"]]
    assert "VAL_RATE_INVALID" in error_codes

    # Test high rate (warning)
    fake_sqs.sent.clear()
    high_rate_data = {
        "client_name": "Test Corp",
        "contract_value": 100000,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "po_number": None,
        "ir35_status": None,
        "day_rates": [{"role": "Test", "rate": 2000, "currency": "GBP"}],  # Very high
        "signatures_present": True
    }

    event = _mk_event(structured_data=high_rate_data)
    result = mod.lambda_handler(event, None)

    msg = json.loads(fake_sqs.sent[0]["MessageBody"])

    # Should pass but with warning
    assert msg["validation_passed"] is True
    warning_codes = [w["code"] for w in msg["validation_warnings"]]
    assert "VAL_RATE_HIGH" in warning_codes
