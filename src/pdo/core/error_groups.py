from __future__ import annotations

__doc__ = """Stable error categories and guidance for batch recovery."""

from typing import Any

ERROR_GROUPS: dict[str, tuple[str, bool, str]] = {
    "timeout": ("Timeout", True, "Check the connection and retry."),
    "rate_limit": (
        "API rate limit reached",
        True,
        "Retry with a delay and reduced request rate.",
    ),
    "connection": ("Connection error", True, "Start the server or check the connection."),
    "missing_data": (
        "Source data missing",
        False,
        "Export source data, complete it, and import it again.",
    ),
    "authentication": ("Credentials rejected", True, "Correct the credentials in Settings."),
    "corrected": ("Source data corrected", True, "Retry the completed products."),
    "other": ("Other errors", True, "Check the error list and retry if needed."),
}


def classify_error(error: Any) -> str:
    """Map provider exceptions or legacy messages to a stable recovery group."""
    text = f"{type(error).__name__} {error}".lower()
    status = getattr(error, "status_code", None)
    if status == 429 or any(
        word in text for word in ("429", "rate limit", "quota", "resource_exhausted")
    ):
        return "rate_limit"
    if status in (401, 403) or any(
        word in text for word in ("401", "403", "unauthorized", "api key", "authentication")
    ):
        return "authentication"
    if any(word in text for word in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(word in text for word in ("connection", "connecterror", "unreachable", "refused")):
        return "connection"
    return "other"
