from django.db import models

class Property(models.Model):
    SOURCE_CHOICES = [
        ('mubawab',   'Mubawab'), ('sarouty', 'Sarouty'),
        ('avito',     'Avito'),   ('sekna',   'Sekna'),
        ('mondinion', 'Mondinion'), ('autre', 'Autre'),
    ]
    TYPE_CHOICES = [
        ('apartment', 'Appartement'), ('villa', 'Villa / Maison'),
        ('riad',  'Riad'),  ('hotel', 'Hôtel'),
        ('land',  'Terrain'), ('office', 'Bureau'),
        ('other', 'Autre'),
    ]

    # Identification
    source        = models.CharField(max_length=50, choices=SOURCE_CHOICES,
                                     db_index=True)
    city          = models.CharField(max_length=100, db_index=True,
                                     verbose_name='Ville')
    district      = models.CharField(max_length=100, blank=True,
                                     verbose_name='Quartier')
    property_type = models.CharField(max_length=50, choices=TYPE_CHOICES,
                                     db_index=True, verbose_name='Type')
    title         = models.CharField(max_length=300, blank=True,
                                     verbose_name='Titre')

    # Prix en MAD
    price_mad     = models.FloatField(db_index=True,
                                      verbose_name='Prix (MAD)')
    price_per_m2_mad = models.FloatField(null=True, blank=True,
                                         verbose_name='Prix/m² (MAD)')

    # Caractéristiques
    area_m2       = models.FloatField(null=True, blank=True,
                                      verbose_name='Surface (m²)')
    bedrooms      = models.IntegerField(null=True, blank=True,
                                        verbose_name='Chambres')
    bathrooms     = models.IntegerField(null=True, blank=True,
                                        verbose_name='SDB')

    # Géolocalisation
    latitude      = models.FloatField(null=True, blank=True)
    longitude     = models.FloatField(null=True, blank=True)

    # Analyse
    is_opportunity    = models.BooleanField(default=False,
                                            verbose_name='Opportunité')
    opportunity_score = models.FloatField(null=True, blank=True,
                                          verbose_name='Score opportunité')
    price_category    = models.CharField(max_length=30, blank=True,
                                         verbose_name='Catégorie prix')

    # Méta
    url        = models.URLField(max_length=500, blank=True)
    scraped_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering         = ['city', 'price_mad']
        verbose_name     = 'Bien immobilier'
        verbose_name_plural = 'Biens immobiliers'

    def __str__(self):
        return f'{self.city} — {self.price_mad:,.0f} DH ({self.property_type})'

    def prix_formate(self):
        return f'{self.price_mad:,.0f} DH'

    def has_geo(self):
        return bool(self.latitude and self.longitude)
