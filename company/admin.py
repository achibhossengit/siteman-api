from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from accounts.models import User
from accounts.views import COMPANY_ADMIN_GROUP
from core.phone import normalize_bd_phone
from subscription.models import Subscription, Payment
from .models import Company, CompanyConfig


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
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.readonly_fields

    def get_inlines(self, request, obj=None):
        if obj:
            return [CompanyConfigInline, SubscriptionInline, PaymentInline]
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
