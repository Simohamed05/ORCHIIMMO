"""
Commande Django : importe orchiimmo_master_enriched_FR.csv dans la base.
Filtre automatiquement sur le Maroc (country='MA').
Prix stockés en MAD (colonne price_local).

Usage :
  python manage.py import_csv
  python manage.py import_csv --limit 1000
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from properties.models import Property
import pandas as pd


class Command(BaseCommand):
    help = 'Importe les biens marocains depuis le CSV BI'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0,
                            help='Limiter le nombre de lignes importées')

    def handle(self, *args, **options):
        csv_path = settings.BI_CSV_PATH
        self.stdout.write(f'Lecture de : {csv_path}')

        try:
            df = pd.read_csv(csv_path, sep=';', decimal=',')
        except FileNotFoundError:
            self.stderr.write(f'Fichier introuvable : {csv_path}')
            return

        # ─── Filtre Maroc uniquement ──────────────────────────────────────
        df = df[df['country'] == 'MA'].copy()
        self.stdout.write(f'Annonces Maroc : {len(df)}')

        # Limiter si demandé
        if options['limit'] > 0:
            df = df.head(options['limit'])

        # ─── Nettoyage colonnes ───────────────────────────────────────────
        def safe_float(val):
            try:
                f = float(val)
                return f if not pd.isna(f) else None
            except Exception:
                return None

        def safe_int(val):
            try:
                i = int(float(val))
                return i if i >= 0 else None
            except Exception:
                return None

        # ─── Import par batch ─────────────────────────────────────────────
        Property.objects.all().delete()
        self.stdout.write('Table vidée. Import en cours…')

        objs  = []
        errors = 0
        for _, row in df.iterrows():
            try:
                price_mad = safe_float(row.get('price_local'))
                if price_mad is None or price_mad <= 0:
                    # Fallback: convertir EUR → MAD
                    price_eur = safe_float(row.get('price_eur'))
                    if price_eur:
                        price_mad = price_eur * settings.EUR_TO_MAD
                    else:
                        continue  # pas de prix → ignorer

                area   = safe_float(row.get('area_m2'))
                ppm2   = (price_mad / area) if area and area > 0 else None

                objs.append(Property(
                    source        = str(row.get('source', 'autre'))[:50],
                    city          = str(row.get('city', ''))[:100],
                    district      = str(row.get('district', '') or '')[:100],
                    property_type = str(row.get('property_type', 'other'))[:50],
                    title         = str(row.get('title', '') or '')[:300],
                    price_mad         = round(price_mad),
                    price_per_m2_mad  = round(ppm2) if ppm2 else None,
                    area_m2       = area,
                    bedrooms      = safe_int(row.get('bedrooms')),
                    bathrooms     = safe_int(row.get('bathrooms')),
                    latitude      = safe_float(row.get('latitude')),
                    longitude     = safe_float(row.get('longitude')),
                    is_opportunity    = bool(row.get('is_opportunity', False)),
                    opportunity_score = safe_float(row.get('opportunity_score')),
                    price_category    = str(row.get('price_category', '') or '')[:30],
                    url           = str(row.get('url', '') or '')[:500],
                ))
            except Exception as e:
                errors += 1

        Property.objects.bulk_create(objs, batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f'Import terminé : {len(objs)} biens créés'
                + (f', {errors} erreurs ignorées' if errors else '')
            )
        )
