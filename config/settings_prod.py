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

# ─── Email production ────────────────────────────────────────────────────────
# Render free tier bloque les connexions SMTP sortantes (ports 465 et 587).
# Solution : utiliser l'API REST Brevo (HTTPS port 443 — jamais bloqué).
# Variable requise : BREVO_API_KEY (clé API Brevo, commence par xkeysib-)
# Fallback console si clé non configurée.
_brevo_api_key = config('BREVO_API_KEY', default='')

if _brevo_api_key:
    # ── Brevo REST API (HTTPS — contourne le blocage SMTP de Render) ─────────
    EMAIL_BACKEND      = 'config.brevo_backend.BrevoAPIBackend'
    BREVO_API_KEY      = _brevo_api_key
    DEFAULT_FROM_EMAIL = 'Orchiimmo <contact@orchiimmo.ma>'
else:
    # ── Fallback console (visible dans les logs Render) ───────────────────────
    EMAIL_BACKEND      = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = 'Orchiimmo <noreply@orchiimmo.ma>'
