"""
Orchiimmo — Configuration Django
Scope : Maroc uniquement | Prix en MAD
"""
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY   = config('SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG        = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Apps Orchiimmo
    'accounts',
    'predictions',
    'properties.apps.PropertiesConfig',
    'dashboards',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE     = 'Africa/Casablanca'
USE_I18N      = True
USE_TZ        = True

STATIC_URL      = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT     = BASE_DIR / 'staticfiles'
MEDIA_URL       = '/media/'
MEDIA_ROOT      = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth redirects
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/predict/'
LOGOUT_REDIRECT_URL = '/'

# ─── Configuration Orchiimmo ───────────────────────────────────────────────
PAYS_CIBLE   = 'MA'               # Maroc uniquement
DEVISE       = 'MAD'              # Dirham Marocain
DEVISE_SYMB  = 'DH'              # Symbole affiché
EUR_TO_MAD   = 10.80             # Taux de conversion (pour référence)

# Chemin du modèle ML (entraîné from scratch)
ML_MODEL_PATH = BASE_DIR / 'ml' / 'models' / 'best_model.pkl'

# Chemin du dataset ML filtré
ML_DATA_PATH  = BASE_DIR / 'ml' / 'data' / 'apparts_maroc_ml.csv'

# Dataset BI source (pour import properties)
BI_CSV_PATH   = BASE_DIR.parent / 'Phase1_BI' / 'orchiimmo_master_enriched_FR.csv'

# ─── Scraping automatique ─────────────────────────────────────────────────────
SCRAPE_AUTO_ENABLED       = True   # Activer le scraping automatique
SCRAPE_INTERVAL_HOURS     = 6      # Toutes les 6 heures
SCRAPE_PAGES_PER_SOURCE   = 5      # Pages par site à chaque cycle
SCRAPE_INITIAL_DELAY_SEC  = 30     # Attendre 30s après démarrage

# ─── Logging ──────────────────────────────────────────────────────────────────
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
    'loggers': {
        'properties': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'django':     {'handlers': ['console'], 'level': 'WARNING'},
    },
}

# KPIs statiques du marché marocain (mis à jour par ml/train.py)
MAROC_STATS = {
    'total_annonces': 7805,
    'nb_villes':      331,
    'prix_median_mad': 1_350_000,
    'prix_moyen_mad':  2_837_789,
    'top_villes': ['Marrakech', 'Casablanca', 'Tanger', 'Kénitra', 'Rabat',
                   'Agadir', 'Fes', 'Meknès', 'Salé', 'El Jadida'],
}
