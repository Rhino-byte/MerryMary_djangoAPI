from django.urls import path

from . import ui_views, views


app_name = "c2b"


urlpatterns = [
    path("", ui_views.home, name="home"),
    path("shortcodes/", ui_views.shortcode_list, name="shortcode_list"),
    path("shortcodes/new/", ui_views.shortcode_create, name="shortcode_create"),
    path("shortcodes/<int:shortcode_id>/", ui_views.shortcode_detail, name="shortcode_detail"),
    path("shortcodes/<int:shortcode_id>/edit/", ui_views.shortcode_edit, name="shortcode_edit"),
    path(
        "shortcodes/<int:shortcode_id>/register-urls/",
        ui_views.shortcode_register_urls,
        name="shortcode_register_urls",
    ),
    path(
        "shortcodes/<int:shortcode_id>/simulate/",
        ui_views.shortcode_simulate,
        name="shortcode_simulate",
    ),
    path("transactions/", ui_views.transactions, name="transactions"),
    path("transactions/export.csv", ui_views.transactions_export_csv, name="transactions_export_csv"),
    path(
        "webhooks/c2b/<int:shortcode_id>/<str:token>/validation/",
        views.c2b_validation,
        name="c2b_validation",
    ),
    path(
        "webhooks/c2b/<int:shortcode_id>/<str:token>/confirmation/",
        views.c2b_confirmation,
        name="c2b_confirmation",
    ),
]

