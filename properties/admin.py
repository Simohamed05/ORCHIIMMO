from django.contrib import admin
from .models import Property


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display  = ('city', 'district', 'property_type', 'prix_formate',
                     'area_m2', 'bedrooms', 'is_opportunity', 'source')
    list_filter   = ('property_type', 'city', 'is_opportunity', 'source')
    search_fields = ('city', 'district', 'title')
    ordering      = ('city', 'price_mad')
    readonly_fields = ('price_per_m2_mad',)

    def prix_formate(self, obj):
        return obj.prix_formate()
    prix_formate.short_description = 'Prix (MAD)'
