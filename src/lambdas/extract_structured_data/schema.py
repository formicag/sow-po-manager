"""
Strict JSON Schema for SOW/PO document extraction.
Rejects extra/unknown fields, enforces types and formats.
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime

# JSON Schema for extracted SOW data
SOW_SCHEMA = {
    "type": "object",
    "required": ["client_name"],
    "additionalProperties": False,  # Reject unknown fields
    "properties": {
        "client_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200
        },
        "contract_value": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 100000000  # £100M max
        },
        "start_date": {
            "type": ["string", "null"],
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"  # YYYY-MM-DD
        },
        "end_date": {
            "type": ["string", "null"],
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        },
        "po_number": {
            "type": ["string", "null"],
            "maxLength": 100
        },
        "ir35_status": {
            "type": ["string", "null"],
            "enum": ["Inside", "Outside", "Not Specified", None]
        },
        "day_rates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["role", "rate", "currency"],
                "additionalProperties": False,
                "properties": {
                    "role": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100
                    },
                    "rate": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 5000  # £5k/day max
                    },
                    "currency": {
                        "type": "string",
                        "enum": ["GBP", "USD", "EUR"]
                    }
                }
            }
        },
        "signatures_present": {
            "type": "boolean"
        }
    }
}


class SchemaValidationError(ValueError):
    """Raised when data doesn't match schema."""
    def __init__(self, code: str, message: str, field: Optional[str] = None):
        self.code = code
        self.field = field
        super().__init__(message)


def validate_against_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """
    Validate data against JSON schema.
    Raises SchemaValidationError if validation fails.
    """
    # Check type
    if schema.get("type") == "object" and not isinstance(data, dict):
        raise SchemaValidationError(
            "VAL_SCHEMA_TYPE",
            f"Expected object, got {type(data).__name__}"
        )

    # Check required fields
    required = schema.get("required", [])
    for field in required:
        if field not in data:
            raise SchemaValidationError(
                "VAL_SCHEMA_REQUIRED",
                f"Required field '{field}' is missing",
                field=field
            )
        if data[field] is None or (isinstance(data[field], str) and not data[field].strip()):
            raise SchemaValidationError(
                "VAL_SCHEMA_EMPTY",
                f"Required field '{field}' cannot be empty",
                field=field
            )

    # Check for extra fields
    if schema.get("additionalProperties") is False:
        allowed_fields = set(schema.get("properties", {}).keys())
        extra_fields = set(data.keys()) - allowed_fields
        if extra_fields:
            raise SchemaValidationError(
                "VAL_SCHEMA_EXTRA",
                f"Unknown fields not allowed: {', '.join(sorted(extra_fields))}",
                field=list(extra_fields)[0]
            )

    # Validate each property
    properties = schema.get("properties", {})
    for field, value in data.items():
        if field not in properties:
            continue  # Already caught by additionalProperties check

        field_schema = properties[field]

        # Handle null values
        field_type = field_schema.get("type")
        if value is None:
            if isinstance(field_type, list) and "null" in field_type:
                continue  # Null is allowed
            elif field_type == "null":
                continue
            elif field not in required:
                continue  # Optional field can be null
            else:
                raise SchemaValidationError(
                    "VAL_SCHEMA_NULL",
                    f"Field '{field}' cannot be null",
                    field=field
                )

        # Type checking
        if field_type:
            expected_types = [field_type] if isinstance(field_type, str) else [t for t in field_type if t != "null"]
            python_types = {
                "string": str,
                "number": (int, float),
                "boolean": bool,
                "array": list,
                "object": dict
            }

            valid_type = False
            for expected in expected_types:
                if expected in python_types:
                    if isinstance(value, python_types[expected]):
                        valid_type = True
                        break

            if not valid_type:
                raise SchemaValidationError(
                    "VAL_SCHEMA_TYPE",
                    f"Field '{field}' has wrong type: expected {expected_types}, got {type(value).__name__}",
                    field=field
                )

        # String validations
        if isinstance(value, str):
            if "minLength" in field_schema and len(value) < field_schema["minLength"]:
                raise SchemaValidationError(
                    "VAL_SCHEMA_LENGTH",
                    f"Field '{field}' too short: min {field_schema['minLength']}, got {len(value)}",
                    field=field
                )
            if "maxLength" in field_schema and len(value) > field_schema["maxLength"]:
                raise SchemaValidationError(
                    "VAL_SCHEMA_LENGTH",
                    f"Field '{field}' too long: max {field_schema['maxLength']}, got {len(value)}",
                    field=field
                )
            if "pattern" in field_schema:
                import re
                if not re.match(field_schema["pattern"], value):
                    raise SchemaValidationError(
                        "VAL_SCHEMA_FORMAT",
                        f"Field '{field}' doesn't match required format: {field_schema['pattern']}",
                        field=field
                    )
            if "enum" in field_schema and value not in field_schema["enum"]:
                raise SchemaValidationError(
                    "VAL_SCHEMA_ENUM",
                    f"Field '{field}' must be one of: {field_schema['enum']}, got '{value}'",
                    field=field
                )

        # Number validations
        if isinstance(value, (int, float)):
            if "minimum" in field_schema and value < field_schema["minimum"]:
                raise SchemaValidationError(
                    "VAL_SCHEMA_RANGE",
                    f"Field '{field}' below minimum: min {field_schema['minimum']}, got {value}",
                    field=field
                )
            if "maximum" in field_schema and value > field_schema["maximum"]:
                raise SchemaValidationError(
                    "VAL_SCHEMA_RANGE",
                    f"Field '{field}' above maximum: max {field_schema['maximum']}, got {value}",
                    field=field
                )

        # Array validations
        if isinstance(value, list) and "items" in field_schema:
            for i, item in enumerate(value):
                try:
                    validate_against_schema(item, field_schema["items"])
                except SchemaValidationError as e:
                    raise SchemaValidationError(
                        e.code,
                        f"In {field}[{i}]: {str(e)}",
                        field=f"{field}[{i}].{e.field}" if e.field else f"{field}[{i}]"
                    )


def validate_sow_data_strict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strict validation of extracted SOW data against schema.
    Raises SchemaValidationError if validation fails.

    Returns the validated data (unchanged if valid).
    """
    if not isinstance(data, dict):
        raise SchemaValidationError(
            "VAL_SCHEMA_TYPE",
            f"Expected dict, got {type(data).__name__}"
        )

    # Validate against schema
    validate_against_schema(data, SOW_SCHEMA)

    # Return validated data (no modifications needed)
    return data
