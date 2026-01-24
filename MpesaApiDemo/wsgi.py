"""
WSGI config for MpesaApiDemo project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

try:
    from .env import load_dotenv

    load_dotenv()
except Exception:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MpesaApiDemo.settings')

application = get_wsgi_application()
