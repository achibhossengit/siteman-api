from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from sites.models import Site

from .models import User, UserSite


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(
        label="Password confirmation", widget=forms.PasswordInput
    )

    class Meta:
        model = User
        fields = ("phone_number", "name", "company")

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match.")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField()

    class Meta:
        model = User
        fields = "__all__"


class UserSiteInline(admin.TabularInline):
    """Sites assigned to this user (same company only).

    Existing rows are read-only; only add and delete are allowed.
    """

    model = UserSite
    fk_name = "user"
    extra = 0
    fields = ("site",)
    verbose_name = "assigned site"
    verbose_name_plural = "assigned sites"

    def has_change_permission(self, request, obj=None):
        return False

    def get_formset(self, request, obj=None, **kwargs):
        self.parent_obj = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "site":
            parent = getattr(self, "parent_obj", None)
            if parent is not None and parent.company_id:
                kwargs["queryset"] = Site.objects.filter(
                    company_id=parent.company_id
                ).order_by("name")
            else:
                kwargs["queryset"] = Site.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User
    inlines = [UserSiteInline]

    list_display = (
        "name",
        "phone_number",
        "company",
        "is_active",
        "is_staff",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "company")
    search_fields = ("phone_number", "name", "email")
    ordering = ("name",)
    readonly_fields = ("last_login", "created_at", "updated_at", "deleted_at")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        ("Profile", {"fields": ("name", "email", "company")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important dates",
            {"fields": ("last_login", "created_at", "updated_at", "deleted_at")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "phone_number",
                    "name",
                    "company",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if isinstance(obj, UserSite):
                if not obj.company_id:
                    obj.company = form.instance.company
                if not obj.created_by_id:
                    obj.created_by = request.user
            obj.save()
        formset.save_m2m()
