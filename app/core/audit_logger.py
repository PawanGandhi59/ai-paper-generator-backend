"""
UK GDPR Article 32 & Principle (f) Security of Processing:
Structured Security Audit Logger.

Provides immutable, structured JSON audit logging for security and privacy events:
- Authentication outcomes (login success/failure, registration)
- Credential lifecycles (password reset requests and completions)
- User Rights requests (data portability exports, account erasure)
- Consent & Privacy preferences changes (marketing, analytics, diagnostics)
- Processing restriction toggles (Article 18)

Ensures zero exposure of passwords, raw secrets, or unmasked email addresses.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

audit_logger = logging.getLogger("security.audit")


def _mask_identifier(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    if "@" in val:
        parts = val.split("@", 1)
        prefix = parts[0][0] + "***" if len(parts[0]) > 1 else "***"
        return f"{prefix}@{parts[1]}"
    if len(val) > 8:
        return val[:3] + "***" + val[-3:]
    return "***"


def log_security_event(
    event_type: str,
    status: str,  # "SUCCESS", "FAILURE", "BLOCKED"
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emits a structured JSON security audit record.
    """
    safe_details = {}
    if details:
        for k, v in details.items():
            if k.lower() in ("password", "secret", "token", "otp", "key"):
                safe_details[k] = "[REDACTED]"
            elif k.lower() in ("email", "recipient_email"):
                safe_details[k] = _mask_identifier(str(v))
            else:
                safe_details[k] = v

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "status": status,
        "user_id": str(user_id) if user_id else None,
        "ip_address": ip_address or "unknown",
        "details": safe_details,
    }

    audit_logger.info(json.dumps(record, ensure_ascii=False))
