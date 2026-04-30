from django.urls import path
from . import views

app_name = 'properties'
urlpatterns = [
    path('',              views.property_list,   name='list'),
    path('<int:pk>/',     views.property_detail, name='detail'),
    path('scrape/stream/',views.scrape_stream,   name='scrape_stream'),
    path('scrape/stats/', views.scrape_stats,    name='scrape_stats'),
]
