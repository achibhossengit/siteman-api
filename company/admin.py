from django.contrib import admin

from subscription.models import Subscription, Payment
from .models import Company, CompanyConfig


class CompanyConfigInline(admin.StackedInline):
    model = CompanyConfig
    can_delete = False
    extra = 0
    readonly_fields = ("updated_at",)


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0
    show_change_link = True
    can_delete = False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    show_change_link = True
    can_delete = True


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display_links = ("name",)
    list_display = ("id", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("deleted_at", "created_at", "updated_at")

    def get_inlines(self, request, obj=None):
        if obj:
            return [CompanyConfigInline, SubscriptionInline, PaymentInline]
        return []
