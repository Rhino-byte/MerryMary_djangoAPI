from __future__ import annotations

import hashlib
import json
import secrets

from django.core.validators import MinValueValidator
from django.db import models


def _generate_webhook_token() -> str:
    # 64 hex chars, URL-safe without encoding.
    return secrets.token_hex(32)


class Shortcode(models.Model):
    class ShortcodeType(models.TextChoices):
        TILL = "TILL", "Till (Buy Goods)"
        PAYBILL = "PAYBILL", "Paybill"

    class ResponseType(models.TextChoices):
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    name = models.CharField(max_length=120)
    shortcode = models.CharField(max_length=20)
    type = models.CharField(max_length=10, choices=ShortcodeType.choices)

    # Daraja app credentials (sandbox/production depending on base_url)
    consumer_key = models.CharField(max_length=200)
    consumer_secret = models.CharField(max_length=200)

    response_type = models.CharField(
        max_length=20, choices=ResponseType.choices, default=ResponseType.COMPLETED
    )

    webhook_token = models.CharField(max_length=64, default=_generate_webhook_token, editable=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["shortcode"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.shortcode})"


class C2BValidationRule(models.Model):
    shortcode = models.OneToOneField(
        Shortcode, on_delete=models.CASCADE, related_name="validation_rule"
    )

    min_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    require_billref = models.BooleanField(default=False)
    billref_regex = models.CharField(max_length=200, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Validation rules for {self.shortcode.shortcode}"


class C2BIncomingEvent(models.Model):
    class EventType(models.TextChoices):
        VALIDATION = "VALIDATION", "Validation"
        CONFIRMATION = "CONFIRMATION", "Confirmation"

    shortcode = models.ForeignKey(Shortcode, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)

    idempotency_key = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField()
    headers = models.JSONField(null=True, blank=True)

    source_ip = models.GenericIPAddressField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def make_idempotency_key(payload: dict) -> str:
        trans_id = payload.get("TransID") or payload.get("TransactionID") or payload.get("TransId")
        if trans_id:
            return str(trans_id)
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def __str__(self) -> str:
        return f"{self.event_type} {self.shortcode.shortcode} {self.received_at:%Y-%m-%d %H:%M:%S}"


class C2BTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        REJECTED = "REJECTED", "Rejected"

    shortcode = models.ForeignKey(
        Shortcode, on_delete=models.CASCADE, related_name="transactions"
    )

    trans_id = models.CharField(max_length=64, null=True, blank=True)
    trans_time = models.DateTimeField(null=True, blank=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    msisdn = models.CharField(max_length=20, null=True, blank=True)
    bill_ref_number = models.CharField(max_length=80, null=True, blank=True)

    first_name = models.CharField(max_length=80, null=True, blank=True)
    middle_name = models.CharField(max_length=80, null=True, blank=True)
    last_name = models.CharField(max_length=80, null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    raw_last_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shortcode", "trans_id"],
                name="uniq_shortcode_trans_id",
            )
        ]
        indexes = [
            models.Index(fields=["shortcode", "trans_time"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.shortcode.shortcode} {self.trans_id or '(no-id)'} {self.status}"

