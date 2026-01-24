from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Shortcode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("shortcode", models.CharField(max_length=20)),
                ("type", models.CharField(choices=[("TILL", "Till (Buy Goods)"), ("PAYBILL", "Paybill")], max_length=10)),
                ("consumer_key", models.CharField(max_length=200)),
                ("consumer_secret", models.CharField(max_length=200)),
                ("response_type", models.CharField(choices=[("Completed", "Completed"), ("Cancelled", "Cancelled")], default="Completed", max_length=20)),
                ("webhook_token", models.CharField(editable=False, max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["shortcode"], name="c2b_shortco_shortcode_2e1d44_idx"),
                    models.Index(fields=["is_active"], name="c2b_shortco_is_activ_9cd7f2_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="C2BIncomingEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("VALIDATION", "Validation"), ("CONFIRMATION", "Confirmation")], max_length=20)),
                ("idempotency_key", models.CharField(db_index=True, max_length=128)),
                ("payload", models.JSONField()),
                ("headers", models.JSONField(blank=True, null=True)),
                ("source_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("shortcode", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="c2b.shortcode")),
            ],
        ),
        migrations.CreateModel(
            name="C2BTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("trans_id", models.CharField(blank=True, max_length=64, null=True)),
                ("trans_time", models.DateTimeField(blank=True, null=True)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("msisdn", models.CharField(blank=True, max_length=20, null=True)),
                ("bill_ref_number", models.CharField(blank=True, max_length=80, null=True)),
                ("first_name", models.CharField(blank=True, max_length=80, null=True)),
                ("middle_name", models.CharField(blank=True, max_length=80, null=True)),
                ("last_name", models.CharField(blank=True, max_length=80, null=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("CONFIRMED", "Confirmed"), ("REJECTED", "Rejected")], default="PENDING", max_length=20)),
                ("raw_last_payload", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("shortcode", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transactions", to="c2b.shortcode")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["shortcode", "trans_time"], name="c2b_c2btra_shortco_5a6a0e_idx"),
                    models.Index(fields=["status"], name="c2b_c2btra_status_4cdb03_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("shortcode", "trans_id"), name="uniq_shortcode_trans_id"),
                ],
            },
        ),
        migrations.CreateModel(
            name="C2BValidationRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("min_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[MinValueValidator(0)])),
                ("max_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("require_billref", models.BooleanField(default=False)),
                ("billref_regex", models.CharField(blank=True, max_length=200, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("shortcode", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="validation_rule", to="c2b.shortcode")),
            ],
        ),
    ]

