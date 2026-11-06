from __future__ import annotations

from decouple import config

from .base import *  # noqa: F403

SECRET_KEY = "explora-plus-test-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="db"),
        "PORT": config("DB_PORT", default="5432"),
        "TEST": {
            "NAME": f"test_{config('DB_NAME', default='explora_plus')}",
        },
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CORS_ALLOW_ALL_ORIGINS = True

# Sem rede nos testes: a cidade dos lugares nao e geocodificada.
PLACE_CITY_LOOKUP_ENABLED = False
