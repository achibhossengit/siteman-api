from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from django.urls import reverse
from django.utils.html import format_html

from accounts.models import User
from accounts.views import COMPANY_ADMIN_GROUP
from core.phone import normalize_bd_phone
from .models import Company


class CompanyAddForm(forms.ModelForm):
    admin_name = forms.CharField(max_length=255, label="Admin name")
    admin_phone = forms.CharField(
        max_length=20,
        label="Admin phone",
        help_text="BD phone, e.g. 01XXXXXXXXX.",
    )
    password = forms.CharField(label="Password", widget=forms.PasswordInput)

    class Meta:
        model = Company
        fields = ("name",)
        labels = {"name": "Company name"}

    def clean_admin_phone(self):
        try:
            phone = normalize_bd_phone(self.cleaned_data["admin_phone"])
        except DjangoValidationError as exc:
            raise forms.ValidationError(exc.messages)
        if User.objects.filter(phone_number=phone).exists():
            raise forms.ValidationError("This phone number is already registered.")
        return phone

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class CompanyUserInline(admin.TabularInline):
    model = User
    fk_name = "company"
    template = "admin/edit_inline/tabular_plain.html"
    extra = 0
    max_num = 0
    can_delete = False
    fields = ("name_link", "phone_number", "is_active", "is_companyadmin")
    readonly_fields = fields
    ordering = ("name", "id")
    verbose_name = "user"
    verbose_name_plural = "users"

    @admin.display(description="name")
    def name_link(self, obj):
        if not obj.pk:
            return "—"
        url = reverse("admin:accounts_user_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.name)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display_links = ("name",)
    list_display = ("id", "name", "is_active", "paid_until", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("deleted_at", "created_at", "updated_at")

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = CompanyAddForm
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (
                    None,
                    {
                        "fields": (
                            "name",
                            "admin_name",
                            "admin_phone",
                            "password",
                        )
                    },
                ),
            )
        return (
            (
                None,
                {
                    "fields": (
                        "name",
                        "is_active",
                        "labour_transfer_allowed",
                        "deleted_at",
                        "created_at",
                        "updated_at",
                    )
                },
            ),
            (
                "Entitlements",
                {
                    "fields": (
                        "site_limit",
                        "active_user_limit",
                        "active_labour_limit",
                        "paid_until",
                    )
                },
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.readonly_fields

    def get_inlines(self, request, obj=None):
        if obj:
            return [CompanyUserInline]
        return []

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            user = User.objects.create_user(
                phone_number=form.cleaned_data["admin_phone"],
                name=form.cleaned_data["admin_name"],
                password=form.cleaned_data["password"],
                company=obj,
                is_companyadmin=True,
            )
            admin_group, _ = Group.objects.get_or_create(name=COMPANY_ADMIN_GROUP)
            user.groups.add(admin_group)
