from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from datetime import date
import re
from typing import Any
from urllib.parse import urljoin

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import ShortcodeForm, ValidationRuleForm
from .models import C2BTransaction, C2BValidationRule, Shortcode
from .services.daraja import DarajaError, register_c2b_urls, simulate_c2b


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


@login_required
@require_GET
def home(request: HttpRequest):
    return redirect("c2b:shortcode_list")


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
        # Daraja sandbox can be inconsistent when repeatedly simulating identical payloads.
        # Force uniqueness for PayBill simulations by appending a short time-based suffix.
        max_len = 12
        suffix = timezone.now().strftime("%H%M%S%f")[-8:]  # 8 digits
        base = _sanitize_reference(bill_ref_input, max_len=max_len) or "TEST"
        keep = max(0, max_len - len(suffix))
        bill_ref = (base[:keep] + suffix)[:max_len]

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
        messages.success(request, f"Simulate OK: {result}")
    except DarajaError as e:
        messages.error(request, str(e))
    return redirect("c2b:shortcode_detail", shortcode_id=sc.id)


@login_required
@require_GET
def transactions(request: HttpRequest):
    selected_date: date | None = None
    if request.GET.get("date"):
        try:
            selected_date = date.fromisoformat(request.GET["date"])
        except Exception:
            selected_date = None
    if not selected_date:
        selected_date = timezone.localdate()

    shortcode_id = request.GET.get("shortcode")
    qs = C2BTransaction.objects.select_related("shortcode").order_by("-created_at")

    if shortcode_id:
        qs = qs.filter(shortcode_id=shortcode_id)

    # Daily view:
    # - Prefer trans_time when available
    # - Fall back to created_at date when trans_time is null
    qs = qs.filter(
        Q(trans_time__date=selected_date) | Q(trans_time__isnull=True, created_at__date=selected_date)
    )

    shortcodes = Shortcode.objects.order_by("name")
    return render(
        request,
        "c2b/transactions.html",
        {
            "transactions": qs[:500],
            "shortcodes": shortcodes,
            "selected_date": selected_date,
            "selected_shortcode_id": int(shortcode_id) if shortcode_id else None,
        },
    )


@login_required
@require_GET
def transactions_export_csv(request: HttpRequest):
    selected_date = timezone.localdate()
    if request.GET.get("date"):
        try:
            selected_date = date.fromisoformat(request.GET["date"])
        except Exception:
            pass

    shortcode_id = request.GET.get("shortcode")
    qs = C2BTransaction.objects.select_related("shortcode").order_by("-created_at")
    if shortcode_id:
        qs = qs.filter(shortcode_id=shortcode_id)
    qs = qs.filter(
        Q(trans_time__date=selected_date) | Q(trans_time__isnull=True, created_at__date=selected_date)
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="transactions_{selected_date.isoformat()}.csv"'

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

