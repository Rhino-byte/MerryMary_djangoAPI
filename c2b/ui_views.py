from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, time, timedelta
import logging
import secrets
import re
import string
from typing import Any
from urllib.parse import urljoin

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db.models import Q, Sum
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import ShortcodeForm, ValidationRuleForm
from .models import C2BTransaction, C2BValidationRule, Shortcode
from .services.daraja import DarajaError, register_c2b_urls, simulate_c2b

logger = logging.getLogger(__name__)


def _parse_time_param(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value)  # accepts "HH:MM" or "HH:MM:SS"
    except Exception:
        return None


def _parse_datetime_local_param(value: str | None) -> datetime | None:
    """
    Parse HTML <input type="datetime-local"> value into an aware datetime in current timezone.
    Expected formats:
    - YYYY-MM-DDTHH:MM
    - YYYY-MM-DDTHH:MM:SS
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    tz = timezone.get_current_timezone()
    if timezone.is_aware(dt):
        return dt.astimezone(tz)
    return timezone.make_aware(dt, tz)


def _sanitize_reference(value: str, *, max_len: int = 12) -> str:
    """
    Daraja can reject invalid references with errors like:
    "The element AccountReference is invalid."

    Keep references conservative:
    - uppercase
    - alphanumeric only
    - short length (default 12, matches common Daraja constraints)
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value or "").upper()
    return cleaned[:max_len]


def _random_reference_from_template(template: str, *, max_len: int = 12) -> str:
    """
    Generate a random reference while preserving letter/digit positions.

    Example template:
    - UB14X5KYAA -> (random) QZ83M7TRPD
      (letters stay letters, digits stay digits)
    """
    tmpl = _sanitize_reference(template, max_len=max_len) or "UB14X5KYAA"
    letters = string.ascii_uppercase
    digits = string.digits
    out: list[str] = []
    for ch in tmpl:
        if ch.isdigit():
            out.append(secrets.choice(digits))
        else:
            out.append(secrets.choice(letters))
    return "".join(out)


def _webhook_urls(request: HttpRequest, shortcode: Shortcode) -> dict[str, str]:
    validation_path = reverse(
        "c2b:c2b_validation", kwargs={"shortcode_id": shortcode.id, "token": shortcode.webhook_token}
    )
    confirmation_path = reverse(
        "c2b:c2b_confirmation",
        kwargs={"shortcode_id": shortcode.id, "token": shortcode.webhook_token},
    )

    public_base_url = getattr(settings, "PUBLIC_BASE_URL", None)
    if public_base_url:
        # Allow generating HTTPS public callback URLs even when browsing locally.
        base = str(public_base_url).rstrip("/") + "/"
        return {
            "validation_url": urljoin(base, validation_path.lstrip("/")),
            "confirmation_url": urljoin(base, confirmation_path.lstrip("/")),
        }

    return {
        "validation_url": request.build_absolute_uri(validation_path),
        "confirmation_url": request.build_absolute_uri(confirmation_path),
    }


@require_GET
def home(request: HttpRequest):
    # Make "/" behave nicely in production:
    # - If logged in: go to dashboard
    # - If not logged in: go to login page
    if request.user.is_authenticated:
        return redirect("c2b:shortcode_list")
    return redirect_to_login(next="/shortcodes/", login_url=settings.LOGIN_URL)


@login_required
@require_GET
def shortcode_list(request: HttpRequest):
    shortcodes = Shortcode.objects.order_by("-created_at")
    return render(request, "c2b/shortcode_list.html", {"shortcodes": shortcodes})


@login_required
@require_http_methods(["GET", "POST"])
def shortcode_create(request: HttpRequest):
    if request.method == "POST":
        form = ShortcodeForm(request.POST)
        if form.is_valid():
            sc = form.save()
            messages.success(request, "Shortcode saved.")
            return redirect("c2b:shortcode_detail", shortcode_id=sc.id)
    else:
        form = ShortcodeForm()
    return render(request, "c2b/shortcode_form.html", {"form": form, "title": "Add shortcode"})


@login_required
@require_http_methods(["GET", "POST"])
def shortcode_edit(request: HttpRequest, shortcode_id: int):
    sc = get_object_or_404(Shortcode, pk=shortcode_id)
    if request.method == "POST":
        form = ShortcodeForm(request.POST, instance=sc)
        if form.is_valid():
            form.save()
            messages.success(request, "Shortcode updated.")
            return redirect("c2b:shortcode_detail", shortcode_id=sc.id)
    else:
        form = ShortcodeForm(instance=sc)
    return render(
        request,
        "c2b/shortcode_form.html",
        {"form": form, "title": f"Edit shortcode {sc.shortcode}"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def shortcode_detail(request: HttpRequest, shortcode_id: int):
    sc = get_object_or_404(Shortcode, pk=shortcode_id)
    urls = _webhook_urls(request, sc)

    rule, _ = C2BValidationRule.objects.get_or_create(shortcode=sc)
    if request.method == "POST":
        rule_form = ValidationRuleForm(request.POST, instance=rule)
        if rule_form.is_valid():
            rule_form.save()
            messages.success(request, "Validation rules saved.")
            return redirect("c2b:shortcode_detail", shortcode_id=sc.id)
    else:
        rule_form = ValidationRuleForm(instance=rule)

    return render(
        request,
        "c2b/shortcode_detail.html",
        {"shortcode": sc, "urls": urls, "rule_form": rule_form},
    )


@login_required
@require_POST
def shortcode_register_urls(request: HttpRequest, shortcode_id: int):
    sc = get_object_or_404(Shortcode, pk=shortcode_id)
    urls = _webhook_urls(request, sc)
    try:
        result = register_c2b_urls(
            consumer_key=sc.consumer_key,
            consumer_secret=sc.consumer_secret,
            shortcode=sc.shortcode,
            response_type=sc.response_type,
            validation_url=urls["validation_url"],
            confirmation_url=urls["confirmation_url"],
        )
        messages.success(request, f"RegisterURL OK: {result}")
    except DarajaError as e:
        messages.error(request, str(e))
    return redirect("c2b:shortcode_detail", shortcode_id=sc.id)


@login_required
@require_POST
def shortcode_simulate(request: HttpRequest, shortcode_id: int):
    sc = get_object_or_404(Shortcode, pk=shortcode_id)
    amount_raw = request.POST.get("amount") or "1"
    msisdn = request.POST.get("msisdn") or "254708374149"

    try:
        # Daraja expects a numeric JSON value (not a string).
        amount: int = int(Decimal(str(amount_raw)))
    except (InvalidOperation, ValueError, TypeError):
        amount = 1

    # Use the correct command for Till vs Paybill.
    command_id = (
        "CustomerBuyGoodsOnline"
        if sc.type == Shortcode.ShortcodeType.TILL
        else "CustomerPayBillOnline"
    )

    bill_ref: str | None
    if command_id == "CustomerBuyGoodsOnline":
        # Per Daraja docs, BuyGoods uses a null BillRefNumber (AccountReference).
        bill_ref = None
    else:
        bill_ref_input = (request.POST.get("bill_ref") or "").strip()
        # Randomize a reference with the same letter/digit pattern as the provided template.
        # If none is provided, default to the system pattern: UB14X5KYAA.
        bill_ref = _random_reference_from_template(bill_ref_input or "UB14X5KYAA", max_len=12)

    try:
        result = simulate_c2b(
            consumer_key=sc.consumer_key,
            consumer_secret=sc.consumer_secret,
            shortcode=sc.shortcode,
            amount=amount,
            msisdn=msisdn,
            bill_ref_number=bill_ref,
            command_id=command_id,
        )
        # Helpful for diagnosing sandbox flakiness: simulate may succeed but callbacks may not arrive.
        logger.info(
            "Daraja simulate OK: shortcode=%s command_id=%s bill_ref=%s response=%s",
            sc.shortcode,
            command_id,
            bill_ref,
            result,
        )
        messages.success(request, f"Simulate OK: {result}")
    except DarajaError as e:
        logger.warning(
            "Daraja simulate FAILED: shortcode=%s command_id=%s bill_ref=%s error=%s",
            sc.shortcode,
            command_id,
            bill_ref,
            str(e),
        )
        messages.error(request, str(e))
    return redirect("c2b:shortcode_detail", shortcode_id=sc.id)


@login_required
@require_GET
def transactions(request: HttpRequest):
    start_dt = _parse_datetime_local_param((request.GET.get("start") or "").strip())
    end_dt = _parse_datetime_local_param((request.GET.get("end") or "").strip())
    if start_dt and end_dt and end_dt < start_dt:
        # Be forgiving if user swaps them.
        start_dt, end_dt = end_dt, start_dt

    refresh_seconds: int = 0
    try:
        refresh_seconds = int((request.GET.get("refresh") or "0").strip() or "0")
    except Exception:
        refresh_seconds = 0
    if refresh_seconds < 0:
        refresh_seconds = 0
    if refresh_seconds > 3600:
        refresh_seconds = 3600

    shortcode_id = request.GET.get("shortcode")
    qs = C2BTransaction.objects.select_related("shortcode").order_by("-created_at")

    if shortcode_id:
        qs = qs.filter(shortcode_id=shortcode_id)

    # If no range provided, default to today's window.
    if not start_dt and not end_dt:
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        day_start = timezone.make_aware(datetime.combine(selected_date, time(0, 0, 0)), tz)
        # Inclusive end for UI friendliness.
        day_end = day_start + timedelta(hours=23, minutes=59, seconds=59)
        start_dt = day_start
        end_dt = day_end

    # Filter window:
    # - Prefer trans_time when available
    # - Fall back to created_at when trans_time is null
    if start_dt and end_dt:
        qs = qs.filter(
            Q(trans_time__gte=start_dt, trans_time__lte=end_dt)
            | Q(trans_time__isnull=True, created_at__gte=start_dt, created_at__lte=end_dt)
        )
    elif start_dt:
        qs = qs.filter(
            Q(trans_time__gte=start_dt) | Q(trans_time__isnull=True, created_at__gte=start_dt)
        )
    elif end_dt:
        qs = qs.filter(Q(trans_time__lte=end_dt) | Q(trans_time__isnull=True, created_at__lte=end_dt))

    # Sum amount across the full filtered result set (not just the displayed slice).
    total_amount = qs.aggregate(total=Sum("amount")).get("total") or Decimal("0")

    shortcodes = Shortcode.objects.order_by("name")
    return render(
        request,
        "c2b/transactions.html",
        {
            "transactions": qs[:500],
            "shortcodes": shortcodes,
            "selected_shortcode_id": int(shortcode_id) if shortcode_id else None,
            "selected_start": start_dt.strftime("%Y-%m-%dT%H:%M") if start_dt else "",
            "selected_end": end_dt.strftime("%Y-%m-%dT%H:%M") if end_dt else "",
            "refresh_seconds": refresh_seconds,
            "total_amount": total_amount,
        },
    )


@login_required
@require_GET
def transactions_export_csv(request: HttpRequest):
    start_dt = _parse_datetime_local_param((request.GET.get("start") or "").strip())
    end_dt = _parse_datetime_local_param((request.GET.get("end") or "").strip())
    if start_dt and end_dt and end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt

    shortcode_id = request.GET.get("shortcode")
    qs = C2BTransaction.objects.select_related("shortcode").order_by("-created_at")
    if shortcode_id:
        qs = qs.filter(shortcode_id=shortcode_id)

    if not start_dt and not end_dt:
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        day_start = timezone.make_aware(datetime.combine(selected_date, time(0, 0, 0)), tz)
        day_end = day_start + timedelta(hours=23, minutes=59, seconds=59)
        start_dt = day_start
        end_dt = day_end

    if start_dt and end_dt:
        qs = qs.filter(
            Q(trans_time__gte=start_dt, trans_time__lte=end_dt)
            | Q(trans_time__isnull=True, created_at__gte=start_dt, created_at__lte=end_dt)
        )
    elif start_dt:
        qs = qs.filter(
            Q(trans_time__gte=start_dt) | Q(trans_time__isnull=True, created_at__gte=start_dt)
        )
    elif end_dt:
        qs = qs.filter(Q(trans_time__lte=end_dt) | Q(trans_time__isnull=True, created_at__lte=end_dt))

    response = HttpResponse(content_type="text/csv")
    filename_date = timezone.localdate().isoformat()
    if start_dt:
        filename_date = start_dt.date().isoformat()
    response["Content-Disposition"] = f'attachment; filename="transactions_{filename_date}.csv"'

    writer = csv.writer(response)
    writer.writerow(["shortcode", "trans_id", "amount", "msisdn", "bill_ref", "trans_time", "status", "created_at"])
    for t in qs.iterator():
        writer.writerow(
            [
                t.shortcode.shortcode,
                t.trans_id,
                t.amount,
                t.msisdn,
                t.bill_ref_number,
                t.trans_time.isoformat() if t.trans_time else "",
                t.status,
                t.created_at.isoformat(),
            ]
        )
    return response

