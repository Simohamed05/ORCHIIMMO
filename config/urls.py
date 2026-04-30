from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render

# Données statiques Maroc pour la home page
TOP_VILLES = [
    {'ville': 'Casablanca',  'annonces': 2134},
    {'ville': 'Marrakech',   'annonces': 1456},
    {'ville': 'Rabat',       'annonces':  987},
    {'ville': 'Tanger',      'annonces':  743},
    {'ville': 'Agadir',      'annonces':  612},
    {'ville': 'Fes',         'annonces':  401},
]

def home_view(request):
    return render(request, 'home.html', {'top_villes': TOP_VILLES})


urlpatterns = [
    path('admin/',       admin.site.urls),
    path('',             home_view,                                 name='home'),
    path('accounts/',    include('accounts.urls',    namespace='accounts')),
    path('predict/',     include('predictions.urls', namespace='predictions')),
    path('properties/',  include('properties.urls',  namespace='properties')),
    path('dashboards/',  include('dashboards.urls',  namespace='dashboards')),
]
