"""
Simple validation for structured data extraction from SOW documents.
No external dependencies - uses only Python built-ins.
"""

from typing import Dict, List, Optional, Any


def validate_day_rate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a day rate entry."""
    return {
        "role": str(data.get("role", "")),
        "rate": float(data.get("rate", 0)) if data.get("rate") is not None else None,
        "currency": str(data.get("currency", "GBP"))
    }


def validate_sow_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize extracted SOW data.

    Args:
        data: Raw extracted data dictionary

    Returns:
        Validated and normalized data dictionary

    Raises:
        ValueError: If required fields are missing or invalid
    """
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data)}")

    # Validate and normalize
    validated = {
        "client_name": str(data.get("client_name", "")).strip(),
        "contract_value": None,
        "start_date": None,
        "end_date": None,
        "po_number": None,
        "day_rates": [],
        "signatures_present": bool(data.get("signatures_present", False))
    }

    # Contract value
    if data.get("contract_value") is not None:
        try:
            validated["contract_value"] = float(data["contract_value"])
        except (ValueError, TypeError):
            validated["contract_value"] = None

    # Dates
    for date_field in ["start_date", "end_date"]:
        if data.get(date_field):
            validated[date_field] = str(data[date_field]).strip() or None

    # PO number
    if data.get("po_number"):
        validated["po_number"] = str(data["po_number"]).strip() or None

    # Day rates
    if data.get("day_rates") and isinstance(data["day_rates"], list):
        validated["day_rates"] = [
            validate_day_rate(rate)
            for rate in data["day_rates"]
            if isinstance(rate, dict)
        ]

    # Basic validation - client_name is required
    if not validated["client_name"]:
        raise ValueError("client_name is required and cannot be empty")

    return validated
