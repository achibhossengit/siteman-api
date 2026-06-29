from django.contrib import admin

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "created_at", "deleted_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
