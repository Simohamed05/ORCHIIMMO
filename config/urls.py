from django.contrib import admin
from django.urls import path, include, reverse_lazy
from django.shortcuts import render
from django.contrib.auth import views as auth_views
from .chatbot_proxy import chatbot_proxy

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
    path('chatbot/',     chatbot_proxy,                                  name='chatbot_proxy'),

    # ─── Password Reset (Django built-in) ───────────────────────────────────
    path('accounts/password-reset/',
         auth_views.PasswordResetView.as_view(
             template_name='accounts/password_reset.html',
             email_template_name='accounts/emails/password_reset_email.html',
             subject_template_name='accounts/emails/password_reset_subject.txt',
             success_url=reverse_lazy('password_reset_done'),
         ),
         name='password_reset'),

    path('accounts/password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='accounts/password_reset_done.html',
         ),
         name='password_reset_done'),

    path('accounts/password-reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html',
             success_url=reverse_lazy('password_reset_complete'),
         ),
         name='password_reset_confirm'),

    path('accounts/password-reset/complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='accounts/password_reset_complete.html',
         ),
         name='password_reset_complete'),
]
