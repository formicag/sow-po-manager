"""
Table-driven validation rules for SOW/PO documents.
Each rule has a deterministic error code, severity, and validation logic.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date
from enum import Enum


class Severity(Enum):
    """Validation severity levels."""
    ERROR = "error"     # Blocks processing
    WARNING = "warning" # Non-blocking concern


class ValidationViolation:
    """Structured validation violation with error code."""
    def __init__(self, code: str, message: str, field: str, severity: Severity):
        self.code = code
        self.message = message
        self.field = field
        self.severity = severity

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "severity": self.severity.value
        }


# Validation thresholds (configurable)
MAX_DAY_RATE = 1200  # GBP
MIN_DAY_RATE = 200   # GBP
MAX_CONTRACT_VALUE = 10000000  # £10M
MAX_CONTRACT_YEARS = 3


class ValidationRule:
    """Base class for validation rules."""
    def __init__(self, code: str, field: str, severity: Severity):
        self.code = code
        self.field = field
        self.severity = severity

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        """
        Validate data against this rule.
        Returns ValidationViolation if rule violated, None otherwise.
        """
        raise NotImplementedError


class ClientNameRequiredRule(ValidationRule):
    """Client name must be present and non-empty."""
    def __init__(self):
        super().__init__("VAL_CLIENT_MISSING", "client_name", Severity.ERROR)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        client_name = data.get("client_name")
        if not client_name or (isinstance(client_name, str) and not client_name.strip()):
            return ValidationViolation(
                self.code,
                "Client name is required",
                self.field,
                self.severity
            )
        return None


class DateRangeRule(ValidationRule):
    """End date must be after start date."""
    def __init__(self):
        super().__init__("VAL_DATE_RANGE", "start_date,end_date", Severity.ERROR)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Skip if either date is missing (handled by DateMissingRule)
        if not start_date or not end_date:
            return None

        try:
            start = datetime.fromisoformat(start_date).date()
            end = datetime.fromisoformat(end_date).date()

            if end <= start:
                return ValidationViolation(
                    self.code,
                    f"End date must be after start date (start={start_date}, end={end_date})",
                    self.field,
                    self.severity
                )
        except ValueError:
            # Skip if date format is invalid (handled by DateFormatRule)
            return None

        return None


class DateMissingRule(ValidationRule):
    """Start and end dates are required."""
    def __init__(self, field: str):
        super().__init__("VAL_DATE_MISSING", field, Severity.ERROR)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        value = data.get(self.field)
        if not value:
            return ValidationViolation(
                self.code,
                f"{self.field.replace('_', ' ').title()} is required",
                self.field,
                self.severity
            )
        return None


class DateFormatRule(ValidationRule):
    """Dates must be in YYYY-MM-DD format."""
    def __init__(self, field: str):
        super().__init__("VAL_DATE_FORMAT", field, Severity.ERROR)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        value = data.get(self.field)
        if not value:
            return None  # Skip if missing (handled by DateMissingRule)

        try:
            datetime.fromisoformat(value).date()
        except (ValueError, AttributeError):
            return ValidationViolation(
                self.code,
                f"Invalid date format for {self.field} (expected YYYY-MM-DD): {value}",
                self.field,
                self.severity
            )

        return None


class DatePastRule(ValidationRule):
    """Warn if contract has already ended."""
    def __init__(self):
        super().__init__("VAL_DATE_PAST", "end_date", Severity.WARNING)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        end_date = data.get("end_date")
        if not end_date:
            return None

        try:
            end = datetime.fromisoformat(end_date).date()
            today = date.today()

            if end < today:
                days_ago = (today - end).days
                return ValidationViolation(
                    self.code,
                    f"Contract ended {days_ago} days ago (end_date={end_date})",
                    self.field,
                    self.severity
                )
        except ValueError:
            return None  # Skip if invalid format

        return None


class DateLongDurationRule(ValidationRule):
    """Warn if contract is longer than 3 years."""
    def __init__(self):
        super().__init__("VAL_DATE_LONG", "start_date,end_date", Severity.WARNING)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        if not start_date or not end_date:
            return None

        try:
            start = datetime.fromisoformat(start_date).date()
            end = datetime.fromisoformat(end_date).date()
            duration_days = (end - start).days

            if duration_days > 365 * MAX_CONTRACT_YEARS:
                duration_years = duration_days / 365
                return ValidationViolation(
                    self.code,
                    f"Contract duration is very long: {duration_days} days ({duration_years:.1f} years)",
                    self.field,
                    self.severity
                )
        except ValueError:
            return None

        return None


class ContractValueMissingRule(ValidationRule):
    """Warn if contract value is not specified."""
    def __init__(self):
        super().__init__("VAL_VALUE_MISSING", "contract_value", Severity.WARNING)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        value = data.get("contract_value")
        if value is None:
            return ValidationViolation(
                self.code,
                "Contract value not specified",
                self.field,
                self.severity
            )
        return None


class ContractValueInvalidRule(ValidationRule):
    """Contract value must be positive."""
    def __init__(self):
        super().__init__("VAL_VALUE_INVALID", "contract_value", Severity.ERROR)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        value = data.get("contract_value")
        if value is not None and value <= 0:
            return ValidationViolation(
                self.code,
                f"Contract value must be positive (got: {value})",
                self.field,
                self.severity
            )
        return None


class ContractValueHighRule(ValidationRule):
    """Warn if contract value is very large."""
    def __init__(self):
        super().__init__("VAL_VALUE_HIGH", "contract_value", Severity.WARNING)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        value = data.get("contract_value")
        if value is not None and value > MAX_CONTRACT_VALUE:
            return ValidationViolation(
                self.code,
                f"Very large contract value: £{value:,.0f} (threshold: £{MAX_CONTRACT_VALUE:,.0f})",
                self.field,
                self.severity
            )
        return None


class DayRateInvalidRule(ValidationRule):
    """Day rates must be positive."""
    def __init__(self):
        super().__init__("VAL_RATE_INVALID", "day_rates", Severity.ERROR)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        day_rates = data.get("day_rates", [])
        for idx, rate_info in enumerate(day_rates):
            rate = rate_info.get("rate", 0)
            role = rate_info.get("role", "Unknown")

            if rate <= 0:
                return ValidationViolation(
                    self.code,
                    f"Day rate must be positive for role at index {idx} (rate={rate})",
                    f"day_rates[{idx}].rate",
                    self.severity
                )
        return None


class DayRateHighRule(ValidationRule):
    """Warn if day rate is very high."""
    def __init__(self):
        super().__init__("VAL_RATE_HIGH", "day_rates", Severity.WARNING)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        day_rates = data.get("day_rates", [])
        for idx, rate_info in enumerate(day_rates):
            rate = rate_info.get("rate", 0)

            if rate > MAX_DAY_RATE:
                return ValidationViolation(
                    self.code,
                    f"Day rate very high at index {idx}: £{rate} (threshold: £{MAX_DAY_RATE})",
                    f"day_rates[{idx}].rate",
                    self.severity
                )
        return None


class DayRateLowRule(ValidationRule):
    """Warn if day rate is very low."""
    def __init__(self):
        super().__init__("VAL_RATE_LOW", "day_rates", Severity.WARNING)

    def validate(self, data: Dict[str, Any]) -> Optional[ValidationViolation]:
        day_rates = data.get("day_rates", [])
        for idx, rate_info in enumerate(day_rates):
            rate = rate_info.get("rate", 0)

            if 0 < rate < MIN_DAY_RATE:
                return ValidationViolation(
                    self.code,
                    f"Day rate very low at index {idx}: £{rate} (threshold: £{MIN_DAY_RATE})",
                    f"day_rates[{idx}].rate",
                    self.severity
                )
        return None


# Validation rule registry (table-driven)
VALIDATION_RULES: List[ValidationRule] = [
    # Client validation
    ClientNameRequiredRule(),

    # Date validations
    DateMissingRule("start_date"),
    DateMissingRule("end_date"),
    DateFormatRule("start_date"),
    DateFormatRule("end_date"),
    DateRangeRule(),
    DatePastRule(),
    DateLongDurationRule(),

    # Contract value validations
    ContractValueMissingRule(),
    ContractValueInvalidRule(),
    ContractValueHighRule(),

    # Day rate validations
    DayRateInvalidRule(),
    DayRateHighRule(),
    DayRateLowRule(),
]


def validate_structured_data(data: Dict[str, Any]) -> Tuple[bool, List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Validate structured data against all rules.

    Returns:
        (validation_passed, errors, warnings)
        - validation_passed: True if no errors (warnings ok)
        - errors: List of error violations as dicts
        - warnings: List of warning violations as dicts
    """
    errors = []
    warnings = []

    for rule in VALIDATION_RULES:
        violation = rule.validate(data)
        if violation:
            if violation.severity == Severity.ERROR:
                errors.append(violation.to_dict())
            else:
                warnings.append(violation.to_dict())

    validation_passed = len(errors) == 0
    return validation_passed, errors, warnings
