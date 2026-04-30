from django.urls import path
from . import views

app_name = 'accounts'
urlpatterns = [
    path('register/',       views.register_view,         name='register'),
    path('login/',          views.login_view,             name='login'),
    path('logout/',         views.logout_view,            name='logout'),
    path('profile/',        views.profile_view,           name='profile'),
    # Email verification
    path('verify/<str:token>/', views.verify_email_view,     name='verify_email'),
    path('verification-sent/',  views.verification_sent_view, name='verification_sent'),
    path('resend-verification/', views.resend_verification_view, name='resend_verification'),
]
