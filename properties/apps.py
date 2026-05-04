"""
properties/apps.py
Lance automatiquement un thread de scraping périodique au démarrage Django.
FIX : fonctionne en prod (gunicorn) + auto-scrape si DB vide au redémarrage.
"""
import threading
import logging
import time
import sys
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)

SCRAPE_INTERVAL_HOURS = 6
SCRAPE_PAGES          = 3
SCRAPE_SOURCES        = [
    'mubawab', 'avito', 'sarouty',
    'sekna', 'selectimmo', 'logiqueimmo',
    'marocannonce', 'maisonmaroc', 'keurimmo', 'immobilier',
]
INITIAL_DELAY_SECONDS = 45


class PropertiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'properties'
    label = 'properties'

    _scheduler_started = False

    def ready(self):
        """Appelé une fois après que Django a chargé tous les modèles."""
        # Ne pas lancer pendant les commandes manage.py
        if any(cmd in sys.argv for cmd in [
            'migrate', 'makemigrations', 'collectstatic',
            'shell', 'createsuperuser', 'import_csv', 'scrape_live',
            'test', 'check', '--help',
        ]):
            return

        # En dev (runserver) : RUN_MAIN=true dans le sous-processus de reload
        # En prod (gunicorn) : RUN_MAIN n'est pas défini
        # On saute seulement le processus PARENT de dev (RUN_MAIN absent + runserver)
        run_main = os.environ.get('RUN_MAIN')
        if run_main == 'false':
            return  # processus parent du dev → skip

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
        """Tourne en background : scrape au démarrage si DB vide, puis périodiquement."""
        time.sleep(INITIAL_DELAY_SECONDS)

        interval = SCRAPE_INTERVAL_HOURS * 3600

        while True:
            try:
                from django.conf import settings
                from properties.models import Property

                db_count = Property.objects.count()
                auto_enabled = getattr(settings, 'SCRAPE_AUTO_ENABLED', False)

                # Auto-scrape si DB vide (après redémarrage ou reset PostgreSQL)
                if db_count == 0:
                    logger.info('[AutoScraper] DB vide détectée — lancement du scraping initial…')
                    PropertiesConfig._run_scrape()
                elif auto_enabled:
                    logger.info(f'[AutoScraper] Cycle automatique ({db_count} biens en DB)')
                    PropertiesConfig._run_scrape()
                else:
                    logger.info(
                        f'[AutoScraper] DB OK ({db_count} biens) — '
                        f'scraping auto désactivé (SCRAPE_AUTO_ENABLED=False)'
                    )
            except Exception as e:
                logger.error(f'[AutoScraper] Erreur dans la boucle : {e}')

            logger.info(f'[AutoScraper] Prochain cycle dans {SCRAPE_INTERVAL_HOURS}h')
            time.sleep(interval)

    @staticmethod
    def _run_scrape():
        """Lance un cycle de scraping."""
        from properties.scraper import scrape_all

        sources = SCRAPE_SOURCES
        pages   = SCRAPE_PAGES

        try:
            logger.info(
                f'[AutoScraper] Scraping — '
                f'{", ".join(sources)} — {pages} pages/source'
            )
            new_count = 0
            for listing in scrape_all(sources=sources, max_pages=pages):
                if listing.get('is_new'):
                    new_count += 1

            logger.info(f'[AutoScraper] Terminé — {new_count} nouvelles annonces')
        except Exception as e:
            logger.error(f'[AutoScraper] Erreur scraping : {e}')
