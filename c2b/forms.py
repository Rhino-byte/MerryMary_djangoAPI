from __future__ import annotations

from django import forms

from .models import C2BValidationRule, Shortcode


class ShortcodeForm(forms.ModelForm):
    consumer_secret = forms.CharField(widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = Shortcode
        fields = [
            "name",
            "shortcode",
            "type",
            "consumer_key",
            "consumer_secret",
            "response_type",
            "is_active",
        ]


class ValidationRuleForm(forms.ModelForm):
    class Meta:
        model = C2BValidationRule
        fields = ["min_amount", "max_amount", "require_billref", "billref_regex"]


class TransactionFilterForm(forms.Form):
    date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    shortcode_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

