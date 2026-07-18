from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.core.exceptions import ValidationError
from core.models import CompanyOwnedMixin, CreatedByMixin, TimeStampedMixin
from core.phone import normalize_bd_phone
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

    def has_site_access(self, site_id: int) -> bool:
        return self.sites.filter(site_id=site_id).exists()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "company"],
                name="uq_user_name_company",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone_number})"

    def clean(self):
        super().clean()

        try:
            self.phone_number = normalize_bd_phone(self.phone_number)
        except ValidationError as exc:
            raise ValidationError({
                "phone_number": exc.messages,
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        

class UserSite(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sites",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="users",
    )

    @classmethod
    def exists(cls, user_id: int, site_id: int) -> bool:
        return cls.objects.filter(user_id=user_id, site_id=site_id).exists()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "site"],
                name="uq_usersite_user_site",
            ),
        ]

    def __str__(self):
        return f"User:{self.user_id} - Site:{self.site_id}"

    def clean(self):
        if self.user.company_id != self.site.company_id:
            raise ValidationError({
                'user': "User and site must be in the same company.",
                'site': "User and site must be in the same company."
            })
        super().clean()