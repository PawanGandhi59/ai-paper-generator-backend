import os
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/legal", tags=["Legal & Privacy"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PRIVACY_NOTICE_PATH = os.path.join(BASE_DIR, "docs", "legal", "PRIVACY-NOTICE.md")
COOKIE_POLICY_PATH = os.path.join(BASE_DIR, "docs", "legal", "COOKIE-POLICY.md")


def _read_doc(filepath: str, fallback_title: str) -> str:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return f"# {fallback_title}\n\nPlease visit https://papervisor.co.uk/privacy for current details."


@router.get("/privacy-notice")
def get_privacy_notice():
    """
    UK GDPR Article 12, 13 & 14 Transparency Endpoint.
    Returns the full canonical UK GDPR Privacy Notice with Data Controller disclosures.
    """
    content = _read_doc(PRIVACY_NOTICE_PATH, "UK GDPR Privacy Notice")
    return {
        "title": "UK GDPR & Data Protection Act 2018 Privacy Notice",
        "version": "1.0",
        "effective_date": "2026-10-06",
        "jurisdiction": "United Kingdom",
        "controller": "AI Paper Generator Platform (papervisor.co.uk)",
        "contact_email": "privacy@papervisor.co.uk",
        "content_markdown": content,
    }


@router.get("/cookie-policy")
def get_cookie_policy():
    """
    PECR Regulation 6 & Article 5(3) ePrivacy Endpoint.
    Returns the full canonical Cookie and Device Storage Policy.
    """
    content = _read_doc(COOKIE_POLICY_PATH, "PECR Cookie & Storage Policy")
    return {
        "title": "PECR Cookie & Terminal Storage Policy",
        "version": "1.0",
        "effective_date": "2026-10-06",
        "jurisdiction": "United Kingdom",
        "cookies_used_by_backend": False,
        "auth_method": "Stateless Bearer JWT (Strictly Necessary)",
        "content_markdown": content,
    }
