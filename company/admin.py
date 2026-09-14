from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.urls import reverse

from accounts.models import GroupProfile, User
from core.admin import COMPANY_LOOKUP
from core.phone import normalize_bd_phone
from .models import Company

TENANT_LINKS = (
    ("Users", "admin:accounts_user_changelist", "accounts.view_user"),
    ("Sites", "admin:sites_site_changelist", "sites.view_site"),
    ("Labours", "admin:labours_labour_changelist", "labours.view_labour"),
    ("Activity logs", "admin:activity_activitylog_changelist", "activity.view_activitylog"),
)


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


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    change_form_template = "admin/company/company/change_form.html"
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

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["tenant_links"] = []
        if object_id:
            query = urlencode({COMPANY_LOOKUP: object_id})
            extra_context["tenant_links"] = [
                {
                    "label": label,
                    "url": f"{reverse(viewname)}?{query}",
                }
                for label, viewname, perm in TENANT_LINKS
                if request.user.has_perm(perm)
            ]
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        # Related tenant rows stay read-only in their own admin, but company
        # delete must cascade (on_delete=CASCADE).
        return deleted_objects, model_count, set(), protected

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
            user.groups.set(GroupProfile.non_platform_groups())
