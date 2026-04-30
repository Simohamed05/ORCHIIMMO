from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile

class ProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profil'

class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ['username','email','first_name','last_name','is_active','date_joined']

admin.site.unregister(User)
admin.site.register(User, UserAdmin)
