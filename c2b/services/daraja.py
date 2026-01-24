from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.cache import cache


class DarajaError(RuntimeError):
    pass


@dataclass(frozen=True)
class DarajaToken:
    access_token: str
    expires_in: int
    obtained_at: float

    @property
    def expires_at(self) -> float:
        return self.obtained_at + max(0, self.expires_in - 30)  # 30s safety window

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


def _base_url() -> str:
    return getattr(settings, "DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke/").rstrip("/") + "/"


def _cache_key(prefix: str, consumer_key: str) -> str:
    # consumer_secret is never included in cache keys/logs.
    safe = base64.urlsafe_b64encode(consumer_key.encode("utf-8")).decode("ascii").rstrip("=")
    return f"daraja:{prefix}:{safe}"


def get_access_token(*, consumer_key: str, consumer_secret: str) -> str:
    """
    Fetch and cache Daraja OAuth token per consumer_key.
    Uses Django's cache backend (defaults to local memory in dev).
    """
    key = _cache_key("token", consumer_key)
    cached: dict[str, Any] | None = cache.get(key)
    if cached:
        token = DarajaToken(**cached)
        if token.is_valid():
            return token.access_token

    url = urljoin(_base_url(), "oauth/v1/generate?grant_type=client_credentials")
    try:
        resp = requests.get(url, auth=(consumer_key, consumer_secret), timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DarajaError(f"OAuth request failed: {e}") from e

    data = resp.json()
    access_token = data.get("access_token")
    expires_in_raw = data.get("expires_in", 3599)
    try:
        expires_in = int(expires_in_raw)
    except Exception:
        expires_in = 3599

    if not access_token:
        raise DarajaError("OAuth response missing access_token")

    token = DarajaToken(access_token=access_token, expires_in=expires_in, obtained_at=time.time())
    cache.set(key, token.__dict__, timeout=expires_in)
    return access_token


def register_c2b_urls(
    *,
    consumer_key: str,
    consumer_secret: str,
    shortcode: str,
    response_type: str,
    validation_url: str,
    confirmation_url: str,
) -> dict[str, Any]:
    """
    Daraja C2B RegisterURL API.
    """
    # Daraja requires publicly reachable HTTPS endpoints (especially in production and typically in sandbox too).
    for label, url in (("ValidationURL", validation_url), ("ConfirmationURL", confirmation_url)):
        if not url.lower().startswith("https://"):
            raise DarajaError(f"{label} must be https:// (got {url!r}). Use a tunnel (ngrok/cloudflared) and register the public URL.")
        if "localhost" in url.lower() or "127.0.0.1" in url:
            raise DarajaError(f"{label} cannot be localhost/127.0.0.1 (got {url!r}). Daraja can't reach your local machine without a tunnel.")

    token = get_access_token(consumer_key=consumer_key, consumer_secret=consumer_secret)
    url = urljoin(_base_url(), "mpesa/c2b/v1/registerurl")
    payload = {
        "ShortCode": shortcode,
        "ResponseType": response_type,  # Completed | Cancelled
        "ConfirmationURL": confirmation_url,
        "ValidationURL": validation_url,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        body = ""
        try:
            body = resp.text  # type: ignore[name-defined]
        except Exception:
            body = ""
        raise DarajaError(f"RegisterURL failed ({getattr(resp, 'status_code', 'unknown')}): {body or str(e)}") from e
    except requests.RequestException as e:
        raise DarajaError(f"RegisterURL failed: {e}") from e


def simulate_c2b(
    *,
    consumer_key: str,
    consumer_secret: str,
    shortcode: str,
    amount: int | float,
    msisdn: str,
    bill_ref_number: str,
    command_id: str = "CustomerPayBillOnline",
) -> dict[str, Any]:
    """
    Daraja sandbox C2B Simulate API.
    Note: this endpoint is sandbox-only.
    """
    token = get_access_token(consumer_key=consumer_key, consumer_secret=consumer_secret)
    url = urljoin(_base_url(), "mpesa/c2b/v1/simulate")
    payload = {
        "ShortCode": shortcode,
        "CommandID": command_id,
        "Amount": amount,
        "Msisdn": msisdn,
        "BillRefNumber": bill_ref_number,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        body = ""
        try:
            body = resp.text  # type: ignore[name-defined]
        except Exception:
            body = ""
        raise DarajaError(f"Simulate failed ({getattr(resp, 'status_code', 'unknown')}): {body or str(e)}") from e
    except requests.RequestException as e:
        raise DarajaError(f"Simulate failed: {e}") from e

