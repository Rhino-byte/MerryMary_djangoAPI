from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import C2BIncomingEvent, C2BTransaction, Shortcode


def _get_client_ip(request: HttpRequest) -> str | None:
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            # First is the original client in standard XFF.
            return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR")


def _safe_json_headers(request: HttpRequest) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    for key, value in request.META.items():
        if key.startswith("HTTP_"):
            headers[key] = value
    return headers


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    # Daraja often uses YYYYMMDDHHMMSS
    if isinstance(value, str) and len(value) == 14 and value.isdigit():
        try:
            dt = datetime.strptime(value, "%Y%m%d%H%M%S")
            return timezone.make_aware(dt, timezone.get_current_timezone())
        except Exception:
            return None
    return None


def _parse_amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # Keep as-is; place-holder for any future normalization.
    return payload


def _get_validation_rule(shortcode: Shortcode):
    try:
        return shortcode.validation_rule
    except Exception:
        return None


def _validate_payload(shortcode: Shortcode, payload: dict[str, Any]) -> tuple[bool, str]:
    """
    Return (accepted, message). Daraja expects:
    - ResultCode: 0 accepted, 1 rejected
    - ResultDesc: message
    """
    rule = _get_validation_rule(shortcode)
    if not rule:
        return True, "Accepted"

    amount = _parse_amount(payload.get("TransAmount"))
    if amount is not None:
        if rule.min_amount is not None and amount < rule.min_amount:
            return False, "Rejected: amount below minimum"
        if rule.max_amount is not None and amount > rule.max_amount:
            return False, "Rejected: amount above maximum"

    bill_ref = payload.get("BillRefNumber")
    if rule.require_billref and not bill_ref:
        return False, "Rejected: BillRefNumber required"

    if rule.billref_regex and bill_ref:
        try:
            if not re.match(rule.billref_regex, str(bill_ref)):
                return False, "Rejected: BillRefNumber format invalid"
        except re.error:
            # If regex invalid, fail open to avoid blocking payments.
            return True, "Accepted"

    return True, "Accepted"


def _upsert_transaction(
    *,
    shortcode: Shortcode,
    payload: dict[str, Any],
    status: str,
) -> C2BTransaction:
    trans_id = payload.get("TransID") or payload.get("TransactionID") or payload.get("TransId")
    trans_time = _parse_datetime(payload.get("TransTime"))
    amount = _parse_amount(payload.get("TransAmount"))
    msisdn = payload.get("MSISDN")
    bill_ref = payload.get("BillRefNumber")

    defaults = {
        "trans_time": trans_time,
        "amount": amount,
        "msisdn": str(msisdn) if msisdn is not None else None,
        "bill_ref_number": str(bill_ref) if bill_ref is not None else None,
        "first_name": payload.get("FirstName"),
        "middle_name": payload.get("MiddleName"),
        "last_name": payload.get("LastName"),
        "status": status,
        "raw_last_payload": payload,
    }

    # If no transaction id, we can't safely dedupe at transaction level.
    if not trans_id:
        return C2BTransaction.objects.create(shortcode=shortcode, **defaults)

    obj, _ = C2BTransaction.objects.update_or_create(
        shortcode=shortcode, trans_id=str(trans_id), defaults=defaults
    )
    return obj


@csrf_exempt
@require_POST
def c2b_validation(request: HttpRequest, shortcode_id: int, token: str):
    shortcode = get_object_or_404(Shortcode, pk=shortcode_id, is_active=True)
    if token != shortcode.webhook_token:
        return JsonResponse({"detail": "Not found"}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload_not_object")
    except Exception:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Rejected: invalid JSON"})

    payload = _normalize_payload(payload)

    idempotency_key = C2BIncomingEvent.make_idempotency_key(payload)
    C2BIncomingEvent.objects.create(
        shortcode=shortcode,
        event_type=C2BIncomingEvent.EventType.VALIDATION,
        idempotency_key=idempotency_key,
        payload=payload,
        headers=_safe_json_headers(request),
        source_ip=_get_client_ip(request),
    )

    accepted, message = _validate_payload(shortcode, payload)
    if accepted:
        _upsert_transaction(shortcode=shortcode, payload=payload, status=C2BTransaction.Status.PENDING)
        return JsonResponse({"ResultCode": 0, "ResultDesc": message})

    _upsert_transaction(shortcode=shortcode, payload=payload, status=C2BTransaction.Status.REJECTED)
    return JsonResponse({"ResultCode": 1, "ResultDesc": message})


@csrf_exempt
@require_POST
def c2b_confirmation(request: HttpRequest, shortcode_id: int, token: str):
    shortcode = get_object_or_404(Shortcode, pk=shortcode_id, is_active=True)
    if token != shortcode.webhook_token:
        return JsonResponse({"detail": "Not found"}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload_not_object")
    except Exception:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Rejected: invalid JSON"})

    payload = _normalize_payload(payload)

    idempotency_key = C2BIncomingEvent.make_idempotency_key(payload)
    C2BIncomingEvent.objects.create(
        shortcode=shortcode,
        event_type=C2BIncomingEvent.EventType.CONFIRMATION,
        idempotency_key=idempotency_key,
        payload=payload,
        headers=_safe_json_headers(request),
        source_ip=_get_client_ip(request),
    )

    _upsert_transaction(shortcode=shortcode, payload=payload, status=C2BTransaction.Status.CONFIRMED)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

