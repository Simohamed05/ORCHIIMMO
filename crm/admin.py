from django.contrib import admin

from .models import Client, Visit


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display  = ('name', 'phone', 'city', 'property_type', 'price_min', 'price_max', 'agent', 'created_at')
    list_filter   = ('city', 'property_type')
    search_fields = ('name', 'phone', 'email')


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display  = ('client', 'target_property', 'scheduled_at', 'status')
    list_filter   = ('status',)
    search_fields = ('client__name',)
