from django.urls import path
from . import views

app_name = 'predictions'
urlpatterns = [
    path('',               views.predict_form,        name='form'),
    path('result/<int:pk>/', views.predict_result,    name='result'),
    path('history/',       views.predict_history,     name='history'),
    path('api/districts/', views.get_districts_ajax,  name='districts_ajax'),
]
