from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

VILLES_MAROC = [
    'Marrakech','Casablanca','Tanger','Kénitra','Rabat',
    'Agadir','Fes','Meknès','Salé','El Jadida',
    'Tétouan','Mohammedia','Béni Mellal','Nador','Oujda',
]

class UserProfile(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE,
                                      related_name='profile')
    phone      = models.CharField(max_length=20, blank=True,
                                  verbose_name='Téléphone')
    ville      = models.CharField(max_length=100, blank=True,
                                  verbose_name='Ville')
    bio        = models.TextField(blank=True, verbose_name='À propos')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Profil utilisateur'

    def __str__(self):
        return f'Profil de {self.user.username}'

    def nb_predictions(self):
        return self.user.predictions.count()

    def derniere_prediction(self):
        return self.user.predictions.order_by('-created_at').first()

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
