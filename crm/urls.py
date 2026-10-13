from django.urls import path

from . import views

app_name = 'crm'
urlpatterns = [
    path('',                        views.client_list,         name='client_list'),
    path('<int:pk>/',               views.client_detail,       name='client_detail'),
    path('<int:pk>/supprimer/',     views.client_delete,       name='client_delete'),
    path('<int:pk>/visite/',        views.visit_create,        name='visit_create'),
    path('visite/<int:pk>/statut/', views.visit_update_status, name='visit_update_status'),
]
