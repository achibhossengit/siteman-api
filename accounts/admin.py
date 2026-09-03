from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.models import Group
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from rest_framework_simplejwt.token_blacklist.admin import (
    OutstandingTokenAdmin as BaseOutstandingTokenAdmin,
)
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from sites.models import Site

from .models import GroupProfile, User, UserSite


class ActiveOutstandingTokenFilter(admin.SimpleListFilter):
    """Active = not blacklisted and not past expires_at."""

    title = "active"
    parameter_name = "active"

    def lookups(self, request, model_admin):
        return (
            ("1", "Yes"),
            ("0", "No"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        active_q = {
            "blacklistedtoken__isnull": True,
            "expires_at__gt": now,
        }
        if self.value() == "1":
            return queryset.filter(**active_q)
        if self.value() == "0":
            return queryset.exclude(**active_q)
        return queryset


class ExpiredOutstandingTokenFilter(admin.SimpleListFilter):
    """Expired = expires_at is in the past (blacklist status ignored)."""

    title = "expired"
    parameter_name = "expired"

    def lookups(self, request, model_admin):
        return (
            ("1", "Yes"),
            ("0", "No"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == "1":
            return queryset.filter(expires_at__lte=now)
        if self.value() == "0":
            return queryset.filter(expires_at__gt=now)
        return queryset


class OutstandingTokenAdmin(BaseOutstandingTokenAdmin):
    list_display = (
        "jti",
        "user_link",
        "created_at",
        "expires_at",
        "is_active",
    )
    list_filter = (
        ActiveOutstandingTokenFilter,
        ExpiredOutstandingTokenFilter,
        "user",
    )
    search_fields = (
        "jti",
        "user__id",
        "user__phone_number",
        "user__name",
    )
    ordering = ("-created_at",)
    actions = ("blacklist_selected_tokens", "delete_selected_tokens")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("user")
        return qs.annotate(
            _is_blacklisted=Exists(
                BlacklistedToken.objects.filter(token_id=OuterRef("pk"))
            )
        )

    def has_change_permission(self, request, obj=None):
        # Changelist POST is required for bulk actions; detail stays read-only.
        if obj is None:
            return admin.ModelAdmin.has_change_permission(self, request, obj)
        return request.method in ("GET", "HEAD") and admin.ModelAdmin.has_change_permission(
            self, request, obj
        )

    @admin.action(description="Blacklist selected tokens")
    def blacklist_selected_tokens(self, request, queryset):
        created = 0
        already = 0
        for token in queryset:
            _, was_created = BlacklistedToken.objects.get_or_create(token=token)
            if was_created:
                created += 1
            else:
                already += 1
        if created:
            self.message_user(
                request,
                f"Blacklisted {created} token(s).",
                messages.SUCCESS,
            )
        if already:
            self.message_user(
                request,
                f"{already} selected token(s) were already blacklisted.",
                messages.WARNING,
            )

    @admin.action(description="Delete selected outstanding tokens")
    def delete_selected_tokens(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f"Deleted {count} outstanding token(s). "
            "Related blacklist rows were removed by cascade.",
            messages.SUCCESS,
        )

    @admin.display(description="user", ordering="user")
    def user_link(self, obj):
        user = obj.user
        if user is None:
            return "—"
        url = reverse("admin:accounts_user_change", args=[user.pk])
        return format_html('<a href="{}">{}</a>', url, user)

    @admin.display(boolean=True, description="active")
    def is_active(self, obj):
        if obj.expires_at <= timezone.now():
            return False
        return not bool(getattr(obj, "_is_blacklisted", False))

    @admin.display(boolean=True, description="expired")
    def is_expired(self, obj):
        return obj.expires_at <= timezone.now()


# Replace SimpleJWT's read-only admin with filters for ops monitoring.
if admin.site.is_registered(OutstandingToken):
    admin.site.unregister(OutstandingToken)
admin.site.register(OutstandingToken, OutstandingTokenAdmin)


class GroupProfileInline(admin.StackedInline):
    """Group type on add, change, and detail."""

    model = GroupProfile
    fk_name = "group"
    extra = 0
    min_num = 1
    max_num = 1
    can_delete = False
    fields = ("type",)


class GroupAdmin(BaseGroupAdmin):
    inlines = [GroupProfileInline]
    list_display = ("name", "profile_type")
    list_filter = ("profile__type",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile")

    @admin.display(description="type", ordering="profile__type")
    def profile_type(self, obj):
        try:
            return obj.profile.get_type_display()
        except GroupProfile.DoesNotExist:
            return "—"


if admin.site.is_registered(Group):
    admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)


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
        "is_companyadmin",
        "is_staff",
    )
    list_filter = ("is_active", "is_companyadmin", "is_staff", "is_superuser", "company")
    search_fields = ("phone_number", "name", "email")
    ordering = ("name",)
    readonly_fields = ("last_login", "created_at", "updated_at")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        ("Profile", {"fields": ("name", "photo", "email", "company")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_companyadmin",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important dates",
            {"fields": ("last_login", "created_at", "updated_at")},
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
                    "is_companyadmin",
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
            obj.save()
        formset.save_m2m()
