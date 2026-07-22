from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "company",
        "site",
        "actor",
        "action_flag",
        "content_type",
        "object_id",
        "created_at",
    )
    list_filter = ("action_flag", "company", "content_type")
    search_fields = ("object_id", "actor__name", "actor__phone_number")
    readonly_fields = (
        "company",
        "site",
        "actor",
        "content_type",
        "object_id",
        "action_flag",
        "changes",
        "created_at",
    )
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
