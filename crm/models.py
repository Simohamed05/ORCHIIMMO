from urllib.parse import quote

from django.conf import settings
from django.db import models

from properties.models import Property


class Client(models.Model):
    name  = models.CharField(max_length=200, verbose_name='Nom')
    phone = models.CharField(max_length=50, verbose_name='Téléphone')
    email = models.EmailField(blank=True, verbose_name='Email')

    # Critères de recherche — servent au matching automatique des biens
    city          = models.CharField(max_length=100, blank=True, verbose_name='Ville recherchée')
    property_type = models.CharField(max_length=50, blank=True,
                                     choices=Property.TYPE_CHOICES,
                                     verbose_name='Type recherché')
    price_min     = models.FloatField(null=True, blank=True, verbose_name='Budget min (DH)')
    price_max     = models.FloatField(null=True, blank=True, verbose_name='Budget max (DH)')
    bedrooms_min  = models.IntegerField(null=True, blank=True, verbose_name='Chambres min')

    notes      = models.TextField(blank=True, verbose_name='Notes')
    agent      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='clients')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'

    def __str__(self):
        return f'{self.name} ({self.phone})'

    def matching_properties(self, limit: int = 30):
        """Biens du catalogue qui correspondent aux critères de recherche du client."""
        qs = Property.objects.all()
        if self.city:
            qs = qs.filter(city__iexact=self.city)
        if self.property_type:
            qs = qs.filter(property_type=self.property_type)
        if self.price_min:
            qs = qs.filter(price_mad__gte=self.price_min)
        if self.price_max:
            qs = qs.filter(price_mad__lte=self.price_max)
        if self.bedrooms_min:
            qs = qs.filter(bedrooms__gte=self.bedrooms_min)
        return qs.order_by('price_mad')[:limit]

    def whatsapp_url(self, message: str = '') -> str:
        phone = self.phone.strip().replace(' ', '').replace('-', '')
        if phone.startswith('0'):
            phone = '212' + phone[1:]
        phone = phone.lstrip('+')
        url = f'https://wa.me/{phone}'
        if message:
            url += f'?text={quote(message)}'
        return url


class Visit(models.Model):
    STATUS_CHOICES = [
        ('planifiee', 'Planifiée'),
        ('faite',     'Faite'),
        ('annulee',   'Annulée'),
    ]

    client           = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='visits')
    target_property  = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='visits')
    scheduled_at     = models.DateTimeField(verbose_name='Date de visite')
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planifiee')
    notes            = models.TextField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_at']
        verbose_name = 'Visite'
        verbose_name_plural = 'Visites'

    def __str__(self):
        return f'{self.client.name} — {self.target_property} — {self.scheduled_at:%d/%m/%Y}'
