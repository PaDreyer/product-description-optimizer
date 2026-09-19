from __future__ import annotations

__doc__ = """Bounded model discovery for configured OpenAI-compatible servers."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pdo.exceptions import ConfigError


def discover_openai_models(api_key: str) -> list[str]:
    """Fetch likely text-generation model IDs from the official OpenAI API.

    The models endpoint does not advertise Responses compatibility. Exclude
    known specialized families; advanced users can still enter a model ID.

    Args:
        api_key: Credential for the OpenAI account whose models should be listed.

    Returns:
        Sorted, unique text-model candidates accessible to the account.

    Raises:
        ConfigError: If credentials, SDK, network access, or text models are missing.
    """
    from pdo.core.provider_defaults import OPENAI_ADDRESS

    if not api_key.strip():
        raise ConfigError("Bitte einen OpenAI API-Schlüssel hinterlegen.")
    try:
        from openai import APIError, OpenAI
    except ImportError as exc:
        raise ConfigError("OpenAI SDK fehlt: pip install 'pdo[openai]'") from exc
    try:
        with OpenAI(
            api_key=api_key.strip(), base_url=OPENAI_ADDRESS, timeout=10, max_retries=0
        ) as client:
            models = client.models.list().data
    except APIError as exc:
        status = getattr(exc, "status_code", None)
        detail = f"HTTP {status}" if status else "Verbindungsfehler"
        raise ConfigError(
            f"OpenAI Modellerkennung: {detail}. Prüfe API-Schlüssel und API-Zugriff."
        ) from exc
    excluded = (
        "audio",
        "realtime",
        "transcribe",
        "tts",
        "image",
        "search",
        "deep-research",
        "codex",
    )
    candidates = sorted(
        {
            model.id
            for model in models
            if model.id.startswith(
                ("gpt-4.1", "gpt-4o", "gpt-5", "gpt-6", "o1", "o3", "o4", "ft:gpt-")
            )
            and not any(part in model.id for part in excluded)
        }
    )
    if not candidates:
        raise ConfigError("OpenAI liefert keine passenden Textmodelle für diesen API-Schlüssel.")
    return candidates[:500]


def discover_models(address: str) -> list[str]:
    """List available model IDs with bounded network time and response size.

    Args:
        address: Explicitly configured server URL including the API prefix.

    Returns:
        Unique model IDs in server order.

    Raises:
        ConfigError: For invalid URLs, missing models, or unreachable servers.
    """
    url = urlsplit(address)
    if url.scheme not in {"http", "https"} or not url.hostname or url.query or url.fragment:
        raise ConfigError("Bitte eine gültige HTTP(S)-Serveradresse angeben.")
    if url.username or url.password:
        raise ConfigError("Zugangsdaten gehören nicht in die Serveradresse.")
    try:
        request = Request(address.rstrip("/") + "/models", headers={"Accept": "application/json"})
        with urlopen(request, timeout=3) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Modellantwort ist zu groß.")
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Der Server liefert keine gültige Modellliste.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Der Server liefert keine gültige Modellliste.")
        models = list(
            dict.fromkeys(
                row["id"]
                for row in payload["data"]
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"].strip()
            )
        )
        if not models:
            raise ValueError("Kein Modell verfügbar. Lade zuerst ein Modell auf dem Server.")
        return models[:500]
    except HTTPError as exc:
        raise ConfigError(
            f"Modellerkennung: Der Server lehnt die Anfrage ab (HTTP {exc.code}). "
            "Prüfe die API-Adresse und die Zugriffseinstellungen des Servers."
        ) from exc
    except (URLError, OSError) as exc:
        raise ConfigError(
            "Modellerkennung: Server nicht erreichbar. Prüfe die Adresse und ob der Server läuft."
        ) from exc
    except ValueError as exc:
        raise ConfigError(f"Modellerkennung fehlgeschlagen: {exc}") from exc
