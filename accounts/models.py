from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from core.models import CompanyOwnedMixin, CreatedByMixin, TimeStampedMixin
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin, TimeStampedMixin):
    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
        help_text="Null for system-scope users.",
    )
    name = models.CharField(max_length=255)
    phone_number = models.CharField(
        max_length=14,
        unique=True,
        help_text="BD phone, normalized to +8801XXXXXXXXX.",
    )
    email = models.EmailField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "company"],
                name="uq_user_name_company",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone_number})"


class UserSite(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="site_assignments",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="user_assignments",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "site"],
                name="uq_usersite_user_site",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.site_id}"
