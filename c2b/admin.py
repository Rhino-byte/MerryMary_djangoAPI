from django.contrib import admin

from .models import C2BIncomingEvent, C2BTransaction, C2BValidationRule, Shortcode


@admin.register(Shortcode)
class ShortcodeAdmin(admin.ModelAdmin):
    list_display = ("name", "shortcode", "type", "is_active", "created_at")
    list_filter = ("type", "is_active")
    search_fields = ("name", "shortcode")
    readonly_fields = ("created_at", "updated_at")


@admin.register(C2BValidationRule)
class C2BValidationRuleAdmin(admin.ModelAdmin):
    list_display = ("shortcode", "min_amount", "max_amount", "require_billref", "updated_at")
    list_filter = ("require_billref",)
    search_fields = ("shortcode__shortcode", "shortcode__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(C2BIncomingEvent)
class C2BIncomingEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "shortcode", "idempotency_key", "received_at")
    list_filter = ("event_type", "shortcode")
    search_fields = ("idempotency_key", "shortcode__shortcode")
    readonly_fields = ("received_at",)


@admin.register(C2BTransaction)
class C2BTransactionAdmin(admin.ModelAdmin):
    list_display = ("shortcode", "trans_id", "amount", "msisdn", "trans_time", "status")
    list_filter = ("status", "shortcode")
    search_fields = ("trans_id", "msisdn", "bill_ref_number", "shortcode__shortcode")
    readonly_fields = ("created_at", "updated_at")

