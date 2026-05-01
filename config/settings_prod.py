"""
config/settings_prod.py
Settings de production pour Railway/Render
Hérite de settings.py et surcharge les valeurs sensibles via variables d'environnement
"""
from .settings import *
import dj_database_url
from decouple import config

# ─── Sécurité ─────────────────────────────────────────────────────────────────
DEBUG        = False
SECRET_KEY   = config('SECRET_KEY')   # obligatoire en prod
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

# CSRF — ajouter le domaine Railway/Render
CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='https://*.railway.app,https://*.up.railway.app,https://*.onrender.com'
).split(',')

# ─── Base de données ──────────────────────────────────────────────────────────
# Railway/Render injectent DATABASE_URL automatiquement (PostgreSQL)
# Fallback sur SQLite si pas de DATABASE_URL
_DB_URL = config('DATABASE_URL', default=None)
if _DB_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=_DB_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
# Sinon garde le SQLite de settings.py

# ─── Fichiers statiques (WhiteNoise) ─────────────────────────────────────────
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ─── Sécurité HTTPS ───────────────────────────────────────────────────────────
# Render / Railway gèrent SSL en amont (reverse proxy)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# SECURE_SSL_REDIRECT contrôlé par variable d'env (False sur Render, True ailleurs)
SECURE_SSL_REDIRECT   = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE    = True

# ─── Scraping auto (Render free dort, mais fonctionne quand actif) ────────────
SCRAPE_AUTO_ENABLED = config('SCRAPE_AUTO_ENABLED', default=False, cast=bool)

# ─── Logs production ─────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[%(levelname)s] %(name)s: %(message)s'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'properties': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

# ─── Fix IPv6 Render : forcer IPv4 pour le SMTP ──────────────────────────────
# Render free tier n'a pas de routage IPv6 → smtp.gmail.com résout en IPv6 en premier
# → OSError: [Errno 101] Network is unreachable
# Solution : monkey-patch socket.getaddrinfo pour forcer AF_INET (IPv4)
import socket as _socket
if not getattr(_socket, '_orchi_ipv4_patch', False):
    _orig_gai = _socket.getaddrinfo
    def _ipv4_only_gai(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_gai(host, port, _socket.AF_INET, type, proto, flags)
    _socket.getaddrinfo = _ipv4_only_gai
    _socket._orchi_ipv4_patch = True

# ─── Email production ────────────────────────────────────────────────────────
# Gmail SMTP est bloqué depuis les IPs cloud AWS/Render → utiliser Brevo SMTP
# Brevo (ex-Sendinblue) : smtp-relay.brevo.com:587 — fonctionne depuis Render
# Variables : BREVO_SMTP_USER (email Brevo) + BREVO_SMTP_KEY (clé API SMTP)
# Fallback : Gmail si BREVO non configuré
# Fallback final : console (logs)
_brevo_user = config('BREVO_SMTP_USER', default='')
_brevo_key  = config('BREVO_SMTP_KEY', default='')
_email_user = config('EMAIL_HOST_USER', default='')

if _brevo_user and _brevo_key:
    # ── Brevo SMTP (recommandé pour Render) ───────────────────────────────────
    EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST          = 'smtp-relay.brevo.com'
    EMAIL_PORT          = 587
    EMAIL_USE_TLS       = True
    EMAIL_USE_SSL       = False
    EMAIL_HOST_USER     = _brevo_user
    EMAIL_HOST_PASSWORD = _brevo_key
    DEFAULT_FROM_EMAIL  = f'Orchiimmo <{_brevo_user}>'
    EMAIL_TIMEOUT       = 20
elif _email_user:
    # ── Gmail SMTP (fallback — peut être bloqué sur Render) ───────────────────
    EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST          = 'smtp.gmail.com'
    EMAIL_PORT          = 465
    EMAIL_USE_TLS       = False
    EMAIL_USE_SSL       = True
    EMAIL_HOST_USER     = _email_user
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    DEFAULT_FROM_EMAIL  = f'Orchiimmo <{_email_user}>'
    EMAIL_TIMEOUT       = 20
else:
    EMAIL_BACKEND      = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = 'Orchiimmo <noreply@orchiimmo.ma>'
