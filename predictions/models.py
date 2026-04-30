from django.db import models
from django.contrib.auth.models import User

TYPE_CHOICES = [
    ('apartment', 'Appartement'),
    ('villa',     'Villa / Maison'),
    ('riad',      'Riad'),
    ('land',      'Terrain'),
    ('office',    'Bureau / Local'),
]

class Prediction(models.Model):
    user                = models.ForeignKey(User, on_delete=models.CASCADE,
                                            related_name='predictions')
    # --- Inputs ---
    city                = models.CharField(max_length=100, verbose_name='Ville')
    district            = models.CharField(max_length=100, blank=True,
                                           verbose_name='Quartier')
    property_type       = models.CharField(max_length=50, choices=TYPE_CHOICES,
                                           default='apartment',
                                           verbose_name='Type de bien')
    area_m2             = models.FloatField(verbose_name='Surface (m²)')
    bedrooms            = models.IntegerField(default=2, verbose_name='Chambres')
    bathrooms           = models.IntegerField(default=1, verbose_name='Salles de bain')

    # --- Résultats en MAD ---
    predicted_price_mad = models.FloatField(verbose_name='Prix estimé (MAD)')
    confidence_low_mad  = models.FloatField(verbose_name='Borne basse (MAD)')
    confidence_high_mad = models.FloatField(verbose_name='Borne haute (MAD)')
    price_per_m2_mad    = models.FloatField(verbose_name='Prix/m² (MAD)')

    # --- Méta ---
    model_version       = models.CharField(max_length=30, default='v1.0')
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering     = ['-created_at']
        verbose_name = 'Prédiction'

    def __str__(self):
        return (f'{self.user.username} — {self.city} {self.area_m2}m² '
                f'→ {self.predicted_price_mad:,.0f} DH')

    def prix_formate(self):
        """Prix formaté avec séparateurs de milliers."""
        return f"{self.predicted_price_mad:,.0f} DH"

    def intervalle_formate(self):
        return (f"{self.confidence_low_mad:,.0f} DH"
                f" — {self.confidence_high_mad:,.0f} DH")

    def incertitude_pct(self):
        """Pourcentage d'incertitude."""
        if self.predicted_price_mad > 0:
            ecart = self.confidence_high_mad - self.confidence_low_mad
            return round((ecart / self.predicted_price_mad) * 100, 1)
        return 0
