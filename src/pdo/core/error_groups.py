from __future__ import annotations

__doc__ = """Stable error categories and guidance for batch recovery."""

from typing import Any

ERROR_GROUPS: dict[str, tuple[str, bool, str]] = {
    "timeout": ("Zeitüberschreitung", True, "Verbindung prüfen und erneut verarbeiten."),
    "rate_limit": (
        "API-Limit erreicht",
        True,
        "Mit Wartezeit und reduzierter Anfragerate wiederholen.",
    ),
    "connection": ("Verbindungsfehler", True, "Server starten bzw. Verbindung prüfen."),
    "missing_data": ("Quelldaten fehlen", False, "Quelldaten exportieren, ergänzen und einlesen."),
    "authentication": ("Zugangsdaten abgelehnt", True, "Zugang in den Einstellungen korrigieren."),
    "corrected": ("Quelldaten korrigiert", True, "Die ergänzten Produkte erneut verarbeiten."),
    "other": ("Weitere Fehler", True, "Fehlerliste prüfen und bei Bedarf erneut verarbeiten."),
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
