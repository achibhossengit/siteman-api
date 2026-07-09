from django.contrib import admin

from .models import Payment, Subscription


# class PlanVariantInline(admin.TabularInline):
#     model = PlanVariant
#     extra = 0
#     fields = ("duration", "price", "discount_price", "is_active")


# @admin.register(Plan)
# class PlanAdmin(admin.ModelAdmin):
#     list_display = (
#         "name",
#         "open_site_limit",
#         "active_user_limit",
#         "active_labour_limit",
#         "created_at",
#     )
#     readonly_fields = ("created_at", "updated_at", "created_by")
#     inlines = [PlanVariantInline]


# @admin.register(CustomPlan)
# class CustomPlanAdmin(admin.ModelAdmin):
#     list_display = (
#         "company",
#         "duration",
#         "price",
#         "is_active",
#         "created_at",
#     )
#     list_filter = ("is_active", "company")
#     search_fields = ("company__name",)
#     readonly_fields = ("created_at", "updated_at", "created_by")

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "company",
        "status",
        "method",
        # "variant",
        # "custom_plan",
        "amount",
    )
    list_filter = ("status", "method", "company__name")
    search_fields = ("company__name", "transaction_id")
    readonly_fields = ("paid_at", "created_by", "created_at", "updated_at")
