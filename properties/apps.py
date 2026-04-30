"""
properties/apps.py
Lance automatiquement un thread de scraping périodique au démarrage Django.
Intervalle : toutes les SCRAPE_INTERVAL_HOURS heures (réglable dans settings.py).
"""
import threading
import logging
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# ── Paramètres ────────────────────────────────────────────────────────────────
SCRAPE_INTERVAL_HOURS = 6      # scraping auto toutes les 6 heures
SCRAPE_PAGES          = 5      # pages par source à chaque cycle
SCRAPE_SOURCES        = ['mubawab', 'sarouty', 'avito']
INITIAL_DELAY_SECONDS = 30     # attendre 30s après le démarrage du serveur


class PropertiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'properties'
    label = 'properties'

    # ── Empêcher le double démarrage en mode dev (--reload) ──────────────────
    _scheduler_started = False

    def ready(self):
        """Appelé une fois après que Django a chargé tous les modèles."""
        import os
        # Eviter le double démarrage avec `runserver --reload` (RUN_MAIN=true)
        if os.environ.get('RUN_MAIN') != 'true':
            return
        if PropertiesConfig._scheduler_started:
            return

        PropertiesConfig._scheduler_started = True
        t = threading.Thread(target=self._scraping_loop, daemon=True)
        t.start()
        logger.info(
            f'[AutoScraper] Thread démarré — '
            f'1er cycle dans {INITIAL_DELAY_SECONDS}s, '
            f'puis toutes les {SCRAPE_INTERVAL_HOURS}h'
        )

    @staticmethod
    def _scraping_loop():
        """Tourne en background : attend INITIAL_DELAY puis scrappe périodiquement."""
        # Attente initiale pour laisser Django/DB se stabiliser
        time.sleep(INITIAL_DELAY_SECONDS)

        interval = SCRAPE_INTERVAL_HOURS * 3600

        while True:
            PropertiesConfig._run_scrape()
            logger.info(
                f'[AutoScraper] Prochain cycle dans {SCRAPE_INTERVAL_HOURS}h'
            )
            time.sleep(interval)

    @staticmethod
    def _run_scrape():
        """Lance un cycle de scraping complet avec paramètres depuis settings."""
        from django.conf import settings
        from properties.scraper import scrape_all

        sources  = getattr(settings, 'SCRAPE_SOURCES',  SCRAPE_SOURCES)
        pages    = getattr(settings, 'SCRAPE_PAGES_PER_SOURCE', SCRAPE_PAGES)
        enabled  = getattr(settings, 'SCRAPE_AUTO_ENABLED', True)

        if not enabled:
            logger.info('[AutoScraper] Désactivé via SCRAPE_AUTO_ENABLED=False')
            return

        try:
            logger.info(
                f'[AutoScraper] Scraping automatique — '
                f'{", ".join(sources)} — {pages} pages/source'
            )
            new_count = 0
            for listing in scrape_all(sources=sources, max_pages=pages):
                if listing.get('is_new'):
                    new_count += 1

            logger.info(
                f'[AutoScraper] Cycle terminé — {new_count} nouvelles annonces'
            )
        except Exception as e:
            logger.error(f'[AutoScraper] Erreur : {e}')
