"""
Commande Django : importe ml/data/apparts_maroc_ml.csv dans la base.
Utilisé pour peupler la base depuis les données ML existantes (6432 lignes).
Idempotent : ne s'exécute que si la base contient moins de MIN_EXPECTED
annonces (sinon on considère que l'import a déjà eu lieu — évite de
dupliquer les lignes du CSV sans URL à chaque déploiement). Les annonces
déjà présentes (ex. avec contact scrappé) sont conservées, jamais supprimées.

Usage :
  python manage.py import_ml_csv
"""
import csv
import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from properties.models import Property

TYPE_MAP = {
    0: 'apartment',
    1: 'villa',
    2: 'riad',
    3: 'land',
    4: 'office',
    5: 'hotel',
}


def _source(url):
    url = url.lower()
    for s in ('mubawab', 'avito', 'sarouty', 'agenz', 'marocannonces', 'masaken', 'logicimmo', 'bikhir'):
        if s in url:
            return s
    return 'autre'


def _float(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except Exception:
        return None


def _int(v):
    try:
        return int(float(v))
    except Exception:
        return None


MIN_EXPECTED = 6000


class Command(BaseCommand):
    help = 'Peuple la base depuis ml/data/apparts_maroc_ml.csv (idempotent)'

    def handle(self, *args, **options):
        current_count = Property.objects.count()
        if current_count >= MIN_EXPECTED:
            self.stdout.write(
                f'Base déjà peuplée ({current_count} annonces) — import ignoré.'
            )
            return

        existing_urls = set(
            Property.objects.exclude(url='').values_list('url', flat=True)
        )

        csv_path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', '..', 'ml', 'data', 'apparts_maroc_ml.csv'
        )
        csv_path = os.path.abspath(csv_path)

        if not os.path.exists(csv_path):
            self.stderr.write(f'Fichier introuvable : {csv_path}')
            return

        self.stdout.write(f'Lecture : {csv_path}')

        objs = []
        errors = 0
        now = timezone.now()

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # skip header

            for row in reader:
                try:
                    if len(row) < 23:
                        continue

                    # Colonnes par index (évite les doublons de noms)
                    type_enc  = _int(row[2]) or 0
                    area      = _float(row[3])
                    bedrooms  = _int(row[4])
                    bathrooms = _int(row[5])
                    price     = _float(row[13])
                    city      = row[14].strip().title()
                    district  = row[15].strip().title()
                    lat       = _float(row[20])
                    lng       = _float(row[21])
                    url       = row[22].strip()

                    if not price or price <= 0:
                        continue
                    if not city:
                        continue
                    if url and url in existing_urls:
                        continue

                    prop_type = TYPE_MAP.get(type_enc, 'apartment')
                    ppm2      = round(price / area) if area and area > 0 else None
                    title     = f"{prop_type.capitalize()} {int(area) if area else ''}m² à {city}"

                    objs.append(Property(
                        source           = _source(url),
                        city             = city,
                        district         = district,
                        property_type    = prop_type,
                        title            = title,
                        price_mad        = round(price),
                        price_per_m2_mad = ppm2,
                        area_m2          = area,
                        bedrooms         = bedrooms,
                        bathrooms        = bathrooms,
                        latitude         = lat,
                        longitude        = lng,
                        url              = url,
                        scraped_at       = now,
                    ))
                    if url:
                        existing_urls.add(url)
                except Exception:
                    errors += 1

        Property.objects.bulk_create(objs, batch_size=500)
        self.stdout.write(self.style.SUCCESS(
            f'✓ Import terminé : {len(objs)} annonces importées'
            + (f' ({errors} erreurs ignorées)' if errors else '')
        ))
