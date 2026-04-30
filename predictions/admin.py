from django.contrib import admin
from .models import Prediction

@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display  = ['user','city','area_m2','property_type',
                     'predicted_price_mad','created_at']
    list_filter   = ['city','property_type','created_at']
    search_fields = ['user__username','city','district']
    readonly_fields = ['created_at','model_version']
    ordering      = ['-created_at']
