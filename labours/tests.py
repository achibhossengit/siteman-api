from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from core import status_codes
from labours.models import Labour
from sites.models import Site
from subscription.models import Subscription

User = get_user_model()


class LabourAPITestCase(APITestCase):
    """Shared fixtures for labour endpoint tests."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)
        # Trial default is unlimited labour (-1); cap for most CRUD tests.
        self.subscription.active_labour_limit = 10
        self.subscription.save(update_fields=["active_labour_limit"])

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_labour_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.list_url = reverse("labour-list", kwargs={"version": "v1"})

    def _grant_labour_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_labour",
            "add_labour",
            "change_labour",
            "delete_labour",
        ]
        ct = ContentType.objects.get_for_model(Labour)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _detail_url(self, labour_id):
        return reverse("labour-detail", kwargs={"version": "v1", "pk": labour_id})

    def _create_labour(self, name="Karim", company=None, **kwargs):
        company = company or self.company
        defaults = {
            "name": name,
            "company": company,
            "created_by": self.user,
            "default_attendance": Decimal("1.0"),
            "default_salary": 500,
            "default_fooding": 100,
        }
        defaults.update(kwargs)
        return Labour.objects.create(**defaults)


class LabourAuthPermissionTests(LabourAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_change_permission_returns_403(self):
        labour = self._create_labour(name="Locked")
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_labour_permissions(self.user, ["view_labour", "add_labour"])
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(self._detail_url(labour.pk), {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_labour_permissions(self.user, ["view_labour"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url, {"name": "New Labour"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class LabourCRUDTests(LabourAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_labour_success(self):
        payload = {
            "name": "Rahim",
            "current_site": self.site.pk,
            "default_attendance": "1.0",
            "default_salary": 800,
            "default_fooding": 150,
        }
        response = self.client.post(self.list_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Rahim")
        self.assertEqual(response.data["current_site"], self.site.pk)
        self.assertEqual(response.data["default_salary"], 800)
        self.assertEqual(response.data["default_fooding"], 150)
        self.assertEqual(Decimal(response.data["default_attendance"]), Decimal("1.0"))
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["created_by"], self.user.pk)

    def test_create_forces_is_active_true(self):
        response = self.client.post(
            self.list_url,
            {"name": "Forced", "is_active": False, "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["is_active"])

    def test_list_uses_list_serializer_fields(self):
        labour = self._create_labour(name="List Labour")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "name",
                "current_site",
                "default_attendance",
                "default_salary",
                "default_fooding",
                "is_active",
            ],
        )
        self.assertEqual(response.data[0]["id"], labour.pk)

    def test_retrieve_labour_detail(self):
        labour = self._create_labour(name="Detail Labour")
        response = self.client.get(self._detail_url(labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Detail Labour")
        self.assertIn("company", response.data)
        self.assertIn("created_at", response.data)

    def test_patch_fields(self):
        labour = self._create_labour(name="Old Name")
        response = self.client.patch(
            self._detail_url(labour.pk),
            {
                "name": "New Name",
                "default_salary": 900,
                "is_active": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Name")
        self.assertEqual(response.data["default_salary"], 900)
        self.assertFalse(response.data["is_active"])
        labour.refresh_from_db()
        self.assertEqual(labour.name, "New Name")
        self.assertFalse(labour.is_active)

    def test_put_not_allowed(self):
        labour = self._create_labour()
        response = self.client.put(self._detail_url(labour.pk), {"name": "Put"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        labour = self._create_labour()
        response = self.client.delete(self._detail_url(labour.pk))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Labour.objects.filter(pk=labour.pk).exists())


class LabourValidationTests(LabourAPITestCase):
    def test_duplicate_name_rejected(self):
        self._create_labour(name="Karim")
        response = self.client.post(
            self.list_url,
            {"name": "Karim", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["errors"][0]["attr"])

    def test_duplicate_name_allowed_across_companies(self):
        other = Company.objects.create(name="Other Co")
        Labour.objects.create(
            name="Shared",
            company=other,
            created_by=self.user,
            default_salary=500,
        )
        response = self.client.post(
            self.list_url,
            {"name": "Shared", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_patch_same_name_allowed(self):
        labour = self._create_labour(name="Keep")
        response = self.client.patch(
            self._detail_url(labour.pk),
            {"default_salary": 600},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_current_site_wrong_company_rejected(self):
        other = Company.objects.create(name="Other Co")
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            {"name": "Bad Site", "current_site": other_site.pk, "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_current_site_closed_rejected(self):
        closed = Site.objects.create(
            name="Closed Yard",
            company=self.company,
            created_by=self.user,
            is_closed=True,
            closed_at=timezone.now(),
        )
        response = self.client.post(
            self.list_url,
            {"name": "On Closed", "current_site": closed.pk, "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LabourFilterIsolationTests(LabourAPITestCase):
    def test_filter_by_is_active(self):
        self._create_labour(name="Active", is_active=True)
        self._create_labour(name="Inactive", is_active=False)

        response = self.client.get(self.list_url, {"is_active": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Active")

        response = self.client.get(self.list_url, {"is_active": "false"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Inactive")

    def test_filter_by_current_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self._create_labour(name="On Padma", current_site=self.site)
        self._create_labour(name="On Other", current_site=other_site)
        self._create_labour(name="Unassigned", current_site=None)

        response = self.client.get(self.list_url, {"current_site": self.site.pk})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "On Padma")

    def test_search_by_name(self):
        self._create_labour(name="Karim Mia")
        self._create_labour(name="Rahim Uddin")

        response = self.client.get(self.list_url, {"search": "Karim"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Karim Mia")

    def test_cannot_create_under_other_company(self):
        other = Company.objects.create(name="Other Co")
        response = self.client.post(
            self.list_url,
            {"name": "Hijack", "company": other.pk, "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["company"], self.company.pk)

    def test_cannot_see_other_company_labours(self):
        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111111",
            name="Other Admin",
            password="strong-pass-123",
            company=other,
        )
        Labour.objects.create(
            name="Secret",
            company=other,
            created_by=other_user,
            default_salary=500,
        )
        self._create_labour(name="Mine")

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Mine")

    def test_cannot_retrieve_other_company_labour(self):
        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111112",
            name="Other Admin 2",
            password="strong-pass-123",
            company=other,
        )
        foreign = Labour.objects.create(
            name="Secret",
            company=other,
            created_by=other_user,
            default_salary=500,
        )
        response = self.client.get(self._detail_url(foreign.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LabourSubscriptionTests(LabourAPITestCase):
    def test_create_blocked_when_active_labour_limit_exceeded(self):
        self.subscription.active_labour_limit = 1
        self.subscription.save(update_fields=["active_labour_limit"])
        self._create_labour(name="Only Slot")

        response = self.client.post(
            self.list_url,
            {"name": "Overflow", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Labour.objects.filter(name="Overflow").exists())
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_LIMIT_EXCEEDED,
        )

    def test_inactive_labour_does_not_count_toward_limit(self):
        self.subscription.active_labour_limit = 1
        self.subscription.save(update_fields=["active_labour_limit"])
        self._create_labour(name="Inactive Slot", is_active=False)

        response = self.client.post(
            self.list_url,
            {"name": "New Active", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            {"name": "Too Late", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Labour.objects.filter(name="Too Late").exists())
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )

    def test_list_allowed_when_subscription_expired(self):
        self._create_labour(name="Readable")
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_patch_blocked_when_subscription_expired(self):
        labour = self._create_labour(name="Editable")
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(labour.pk),
            {"name": "No Write"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        labour.refresh_from_db()
        self.assertEqual(labour.name, "Editable")
