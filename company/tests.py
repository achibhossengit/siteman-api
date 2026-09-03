from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from accounts.views import COMPANY_ADMIN_GROUP
from company.models import Company
from core import status_codes
from labours.models import DailyRecord, Labour
from sites.models import Site


class CompanyAdminAddTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            phone_number="+8801700000001",
            name="Staff",
            password="pass-12345",
        )
        self.client.force_login(self.staff)
        self.add_url = reverse("admin:company_company_add")

    def test_add_page_shows_onboarding_fields_only(self):
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Company name")
        self.assertContains(response, "Admin name")
        self.assertContains(response, "Admin phone")
        self.assertContains(response, 'name="password"')
        self.assertNotContains(response, 'id="id_is_active"')
        self.assertNotContains(response, 'id="id_site_limit"')
        self.assertNotContains(response, 'id="id_paid_until"')

    def test_save_creates_company_and_company_admin(self):
        response = self.client.post(
            self.add_url,
            {
                "name": "New Builders",
                "admin_name": "Owner",
                "admin_phone": "01712345678",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, 302)

        company = Company.objects.get(name="New Builders")
        user = User.objects.get(phone_number="+8801712345678")
        self.assertEqual(user.company, company)
        self.assertEqual(user.name, "Owner")
        self.assertTrue(user.is_companyadmin)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password("strong-pass-123"))
        self.assertTrue(user.groups.filter(name=COMPANY_ADMIN_GROUP).exists())

    def test_duplicate_phone_does_not_create_company(self):
        User.objects.create_user(
            phone_number="+8801712345678",
            name="Existing",
            password="pass-12345",
        )
        response = self.client.post(
            self.add_url,
            {
                "name": "Dup Co",
                "admin_name": "Owner",
                "admin_phone": "01712345678",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Company.objects.filter(name="Dup Co").exists())
        self.assertContains(response, "already registered")


class CompanyAdminChangeTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            phone_number="+8801700000001",
            name="Staff",
            password="pass-12345",
        )
        self.client.force_login(self.staff)
        self.company = Company.objects.create(name="Acme Builders")
        self.change_url = reverse(
            "admin:company_company_change", args=[self.company.pk]
        )

    def test_users_are_a_read_only_list_linking_to_detail(self):
        user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Site Incharge",
            password="pass-12345",
            company=self.company,
        )
        detail_url = reverse("admin:accounts_user_change", args=[user.pk])

        response = self.client.get(self.change_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site Incharge")
        self.assertContains(response, f'href="{detail_url}"')
        self.assertContains(response, "+8801712345678")
        self.assertContains(response, 'name="users-MAX_NUM_FORMS" value="0"')
        self.assertNotContains(response, 'id="users-empty"')
        self.assertNotContains(response, 'name="users-0-phone_number"')
        self.assertNotContains(response, 'name="users-0-name"')


class CompanyAPITestCase(APITestCase):
    """Shared fixtures for ``PATCH`` / ``DELETE /company``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
            is_companyadmin=True,
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse("company-detail", kwargs={"version": "v1"})

    def _grant_company_permissions(self, user, codenames=None):
        codenames = codenames or ["change_company", "delete_company"]
        ct = ContentType.objects.get_for_model(Company)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)
        user = User.objects.get(pk=user.pk)
        self.client.force_authenticate(user=user)
        return user


class CompanyAuthPermissionTests(CompanyAPITestCase):
    def test_unauthenticated_patch_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.patch(self.url, {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_delete_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.delete(self.url, {"password": "strong-pass-123"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_change_permission_returns_403(self):
        response = self.client.patch(self.url, {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Achib Builders")

    def test_missing_delete_permission_returns_403(self):
        self._grant_company_permissions(self.user, ["change_company"])
        response = self.client.delete(self.url, {"password": "strong-pass-123"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_unauthenticated_get_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_without_company_returns_404(self):
        self.user.company = None
        self.user.save(update_fields=["company"])
        self._grant_company_permissions(self.user)
        response = self.client.patch(self.url, {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CompanyRetrieveTests(CompanyAPITestCase):
    def test_get_returns_company_config_and_sites(self):
        site = Site.objects.create(name="Padma Bridge", company=self.company)
        other_site = Site.objects.create(name="Jamuna Bridge", company=self.company)
        foreign_company = Company.objects.create(name="Other Co")
        Site.objects.create(name="Foreign Site", company=foreign_company)

        self.company.site_limit = 8
        self.company.active_user_limit = 12
        self.company.active_labour_limit = 40
        self.company.paid_until = timezone.localdate() + timedelta(days=30)
        self.company.labour_transfer_allowed = False
        self.company.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.company.pk)
        self.assertEqual(response.data["name"], "Achib Builders")
        self.assertEqual(response.data["site_limit"], 8)
        self.assertEqual(response.data["active_user_limit"], 12)
        self.assertEqual(response.data["active_labour_limit"], 40)
        self.assertEqual(response.data["paid_until"], self.company.paid_until.isoformat())
        self.assertFalse(response.data["labour_transfer_allowed"])
        rows = {row["id"]: row for row in response.data["sites"]}
        self.assertCountEqual(rows, [site.pk, other_site.pk])
        self.assertEqual(rows[site.pk], {"id": site.pk, "name": "Padma Bridge"})
        self.assertEqual(rows[other_site.pk]["name"], "Jamuna Bridge")
        groups = {row["id"]: row for row in response.data["groups"]}
        self.assertEqual(len(groups), Group.objects.count())
        for group in Group.objects.select_related("profile"):
            self.assertEqual(groups[group.pk]["name"], group.name)
            self.assertEqual(groups[group.pk]["type"], group.profile.type)

    def test_get_does_not_require_view_company(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["sites"], [])

    def test_get_allowed_when_subscription_expired(self):
        self.company.paid_until = timezone.localdate() - timedelta(days=1)
        self.company.save(update_fields=["paid_until"])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Achib Builders")


class CompanyUpdateTests(CompanyAPITestCase):
    def setUp(self):
        super().setUp()
        self._grant_company_permissions(self.user, ["change_company"])

    def test_patch_name(self):
        response = self.client.patch(self.url, {"name": "New Builders"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Builders")
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "New Builders")

    def test_patch_labour_transfer_allowed(self):
        response = self.client.patch(
            self.url,
            {"labour_transfer_allowed": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["labour_transfer_allowed"])
        self.company.refresh_from_db()
        self.assertFalse(self.company.labour_transfer_allowed)

    def test_patch_ignores_entitlements(self):
        original_until = self.company.paid_until
        response = self.client.patch(
            self.url,
            {
                "site_limit": 99,
                "active_user_limit": 99,
                "active_labour_limit": 99,
                "paid_until": "2099-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.site_limit, 2)
        self.assertEqual(self.company.active_user_limit, 4)
        self.assertEqual(self.company.active_labour_limit, 30)
        self.assertEqual(self.company.paid_until, original_until)

    def test_patch_blocked_when_subscription_expired(self):
        self.company.paid_until = timezone.localdate() - timedelta(days=1)
        self.company.save(update_fields=["paid_until"])

        response = self.client.patch(self.url, {"name": "Too Late"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Achib Builders")


class CompanyDeleteTests(CompanyAPITestCase):
    def setUp(self):
        super().setUp()
        self._grant_company_permissions(self.user, ["delete_company"])

    def test_delete_requires_password(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_delete_rejects_wrong_password(self):
        response = self.client.delete(self.url, {"password": "wrong-pass"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_removes_company_and_related_rows(self):
        site = Site.objects.create(name="Padma Bridge", company=self.company)
        labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            current_site=site,
            default_salary=500,
        )
        DailyRecord.objects.create(
            labour=labour,
            site=site,
            company=self.company,
            date=timezone.localdate(),
            present=Decimal("1"),
            wage=500,
            is_sealed=False,
        )
        company_id = self.company.pk
        user_id = self.user.pk

        response = self.client.delete(self.url, {"password": "strong-pass-123"})

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Company.objects.filter(pk=company_id).exists())
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(Site.objects.filter(pk=site.pk).exists())
        self.assertFalse(Labour.objects.filter(pk=labour.pk).exists())
        self.assertFalse(DailyRecord.objects.filter(site_id=site.pk).exists())

