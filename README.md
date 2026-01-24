# Mpesa-Daraja-Api-Python-Django

This repo now includes a **C2B dashboard** (Django templates UI) that lets you:
- Add/manage multiple **tills/paybills (shortcodes)**
- Configure **Validation** rules per shortcode
- Register **ValidationURL + ConfirmationURL** with Daraja
- Receive callbacks and view **daily transactions**
- Store data in **Neon Postgres** via `DATABASE_URL` (or use local SQLite by default)

## Setup (Windows)

Create/activate a venv, then install dependencies:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

Run migrations and create an admin user:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open:
- Dashboard: `http://127.0.0.1:8000/`
- Admin: `http://127.0.0.1:8000/admin/`

## Neon Postgres

Set `DATABASE_URL` to your Neon connection string:

- **PowerShell**:

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

Then run:

```bash
python manage.py migrate
```

## Daraja sandbox testing notes

Daraja must reach your callback URLs over the public internet. For local dev use a tunnel (ngrok/cloudflared) and ensure the dashboard generates public webhook URLs.

In the UI:
- Add a shortcode
- Open it and click **Register URLs**
- Use **Sandbox simulate** to send a test C2B payment
- View results in **Transactions**

## Webhook endpoints

Per shortcode, the dashboard generates token-protected endpoints:
- `/webhooks/c2b/<shortcode_id>/<token>/validation/`
- `/webhooks/c2b/<shortcode_id>/<token>/confirmation/`

## Production hardening (recommended env vars)

- **Django**
  - `DJANGO_SECRET_KEY`: required in production
  - `DJANGO_DEBUG`: set to `0` in production
  - `DJANGO_ALLOWED_HOSTS`: comma-separated hosts (e.g. `example.com,www.example.com`)
  - `DJANGO_TRUST_PROXY_HEADERS`: set to `1` if behind a proxy that sets `X-Forwarded-For`
  - `DJANGO_SECURE_HSTS_SECONDS`: optional (e.g. `31536000`) when fully on HTTPS

- **Daraja**
  - `DARAJA_BASE_URL`: defaults to sandbox

## Deploy on Render (recommended)

Create a **Web Service** from this repo.

- **Build Command**:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
```

- **Start Command**:

```bash
gunicorn MpesaApiDemo.wsgi:application
```

Set these **Environment Variables** in Render:
- `DJANGO_SECRET_KEY`: generate a strong random value
- `DJANGO_DEBUG=0`
- `DJANGO_ALLOWED_HOSTS=<your-render-service-domain>` (comma-separated if multiple)
- `DJANGO_TRUST_PROXY_HEADERS=1`
- `DJANGO_SECURE_SSL_REDIRECT=1`
- `DATABASE_URL=<your Neon connection string>`
- `DARAJA_BASE_URL=https://sandbox.safaricom.co.ke/` (or production base URL when going live)
