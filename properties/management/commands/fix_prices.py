"""
python manage.py fix_prices

Détecte et corrige les annonces dont le prix est stocké en EUR au lieu de MAD.
Critères :
  - Type = apartment / villa / riad / office / hotel
  - Surface < 500 m²
  - Prix/m² < 4 000 DH/m² (impossible en ville marocaine → c'est de l'EUR)

  OU

  - Prix < 200 000 DH sans surface connue (trop bas pour être du MAD)

Correction : price_mad × 10.80  |  price_per_m2_mad × 10.80
"""
from django.core.management.base import BaseCommand
from django.db import transaction

EUR_TO_MAD = 10.80
URBAN_TYPES = ('apartment', 'villa', 'riad', 'hotel', 'office')


class Command(BaseCommand):
    help = 'Corrige les prix en EUR stockés comme MAD'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Afficher les corrections sans les appliquer'
        )

    def handle(self, *args, **options):
        from properties.models import Property

        dry = options['dry_run']
        if dry:
            self.stdout.write(self.style.WARNING('MODE DRY-RUN — aucune modification'))

        # ── Critère 1 : ppm2 < 2500 DH/m2 + surface < 500m2 + type urbain ──────
        # (en dessous de 2500 DH/m2 = ~230 EUR/m2 → impossible en ville marocaine)
        q1 = Property.objects.filter(
            property_type__in=URBAN_TYPES,
            area_m2__gt=0,
            area_m2__lt=500,
            price_per_m2_mad__isnull=False,
            price_per_m2_mad__lt=2_500,
        )

        # ── Critère 2 : prix < 100k DH + type urbain (ultra-bas, sûrement EUR) ─
        q2 = Property.objects.filter(
            property_type__in=URBAN_TYPES,
            price_mad__lt=100_000,
        )

        suspects = (q1 | q2).distinct()
        total    = suspects.count()
        self.stdout.write(f'\n{total} annonces suspectes (prix EUR stocké en DH)')

        fixed = 0
        with transaction.atomic():
            for p in suspects:
                old_price = p.price_mad
                new_price = round(old_price * EUR_TO_MAD)

                old_ppm2 = p.price_per_m2_mad
                new_ppm2 = round(old_ppm2 * EUR_TO_MAD) if old_ppm2 else (
                    round(new_price / p.area_m2) if p.area_m2 else None
                )

                self.stdout.write(
                    f'  [{p.pk}] {p.city} | {p.property_type} | '
                    f'{old_price:,.0f} DH → {new_price:,.0f} DH'
                    f'{f" ({old_ppm2:.0f}→{new_ppm2:.0f} DH/m²)" if old_ppm2 else ""}'
                )

                if not dry:
                    p.price_mad        = new_price
                    p.price_per_m2_mad = new_ppm2
                    p.save(update_fields=['price_mad', 'price_per_m2_mad'])
                    fixed += 1

        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDRY-RUN : {total} corrections simulées — relancez sans --dry-run pour appliquer'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✓ {fixed} prix corrigés (× {EUR_TO_MAD})'
                )
            )

        # ── Normaliser les noms de source (mubawab → Mubawab) ─────────────────
        if not dry:
            from django.db.models import Count
            src_map = {'mubawab': 'Mubawab', 'avito': 'Avito',
                       'sarouty': 'Sarouty', 'sekna': 'Sekna'}
            for old, new in src_map.items():
                n = Property.objects.filter(source=old).update(source=new)
                if n:
                    self.stdout.write(f'  Source normalisée : {old} → {new} ({n})')

            self.stdout.write(self.style.SUCCESS('Sources normalisées.'))
