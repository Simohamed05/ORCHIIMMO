"""
python manage.py scrape_live
  --sources mubawab,sarouty,avito  (défaut : tous)
  --pages   5                       (défaut : 5 par source)
  --city    Casablanca              (optionnel)

Scrape les sites en temps réel et sauvegarde en DB.
Compatible avec cron / Windows Task Scheduler.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Scrape Mubawab · Sarouty · Avito en temps réel et importe en DB'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sources', default='mubawab,sarouty,avito',
            help='Sources séparées par virgule (défaut: toutes)'
        )
        parser.add_argument(
            '--pages', type=int, default=5,
            help='Nombre de pages par source (défaut: 5)'
        )
        parser.add_argument(
            '--city', default='',
            help='Filtrer par ville (optionnel)'
        )

    def handle(self, *args, **options):
        from properties.scraper import scrape_all

        sources  = [s.strip() for s in options['sources'].split(',') if s.strip()]
        pages    = min(options['pages'], 20)
        city     = options['city']

        self.stdout.write(
            self.style.HTTP_INFO(
                f'\n[{timezone.now().strftime("%Y-%m-%d %H:%M")}] '
                f'Scraping : {", ".join(sources)} — {pages} pages/source'
                + (f' — ville: {city}' if city else '')
            )
        )

        total_new = 0
        total_dup = 0
        errors    = 0

        try:
            for listing in scrape_all(sources=sources, max_pages=pages,
                                      city_filter=city):
                if 'error' in listing:
                    errors += 1
                    self.stderr.write(
                        f'  [ERR] {listing["source"]}: {listing["error"]}'
                    )
                elif listing.get('is_new'):
                    total_new += 1
                    price_str = f'{listing["price_mad"]:,.0f} DH' if listing.get('price_mad') else '—'
                    self.stdout.write(
                        f'  [+] {listing["source"]:<10} '
                        f'{listing["city"]:<15} '
                        f'{price_str:<18} '
                        f'{listing.get("area_m2") or "—"} m²'
                    )
                else:
                    total_dup += 1

        except KeyboardInterrupt:
            self.stdout.write('\nInterrompu par l\'utilisateur.')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nTerminé — {total_new} nouvelles annonces · '
                f'{total_dup} doublons ignorés · {errors} erreurs'
            )
        )
