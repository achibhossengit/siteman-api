from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from sites.models import (
    BillingCategory,
    PrivateSiteCash,
    PrivateSiteCashType,
    Site,
    SiteCash,
    SiteCashCategory,
    SiteCashType,
)
from subscription.models import Subscription
from accounts.models import UserSite
from core import status_codes

User = get_user_model()


class SiteAPITestCase(APITestCase):
    """Shared fixtures for site endpoint tests."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)
        # Trial default is 1 open site; raise for most CRUD tests.
        self.subscription.open_site_limit = 5
        self.subscription.save(update_fields=["open_site_limit"])

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_site_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.list_url = reverse("site-list", kwargs={"version": "v1"})

    def _grant_site_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_site",
            "add_site",
            "change_site",
            "delete_site",
        ]
        ct = ContentType.objects.get_for_model(Site)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _detail_url(self, site_id):
        return reverse("site-detail", kwargs={"version": "v1", "pk": site_id})

    def _create_site(self, name="Site A", company=None, **kwargs):
        company = company or self.company
        return Site.objects.create(
            name=name,
            company=company,
            created_by=self.user,
            **kwargs,
        )


class SiteAuthPermissionTests(SiteAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        # unauthenticate user first
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_change_permission_returns_403(self):
        site = self._create_site(name="Locked")
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_site_permissions(self.user, ["view_site", "add_site"])
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(self._detail_url(site.pk), {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_site_permissions(self.user, ["view_site"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url, {"name": "New Site"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SiteCRUDTests(SiteAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_site_success(self):
        response = self.client.post(self.list_url, {"name": "Padma Bridge"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Padma Bridge")
        self.assertTrue(response.data["is_active"])
        self.assertFalse(response.data["is_closed"])
        self.assertIsNone(response.data["closed_at"])
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["created_by"], self.user.pk)

    def test_create_forces_open_and_active(self):
        response = self.client.post(
            self.list_url,
            {"name": "Forced", "is_active": False, "is_closed": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["is_active"])
        self.assertFalse(response.data["is_closed"])
        self.assertIsNone(response.data["closed_at"])

    def test_list_uses_list_serializer_fields(self):
        site = self._create_site(name="List Site")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            ["id", "name", "is_active", "is_closed"],
        )
        self.assertEqual(response.data[0]["id"], site.pk)

    def test_retrieve_site_detail(self):
        site = self._create_site(name="Detail Site")
        response = self.client.get(self._detail_url(site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Detail Site")
        self.assertIn("company", response.data)
        self.assertIn("created_at", response.data)

    def test_patch_name_and_is_active(self):
        site = self._create_site(name="Old Name")
        response = self.client.patch(
            self._detail_url(site.pk),
            {"name": "New Name", "is_active": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Name")
        self.assertFalse(response.data["is_active"])
        site.refresh_from_db()
        self.assertEqual(site.name, "New Name")
        self.assertFalse(site.is_active)

    def test_patch_closed_site_rejected(self):
        site = self._create_site(name="Closed Site", is_closed=True, closed_at=timezone.now())
        response = self.client.patch(
            self._detail_url(site.pk),
            {"name": "Should Fail"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_site_success(self):
        site = self._create_site(name="To Delete")
        response = self.client.delete(self._detail_url(site.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Site.objects.filter(pk=site.pk).exists())

    def test_put_not_allowed(self):
        site = self._create_site()
        response = self.client.put(self._detail_url(site.pk), {"name": "Put"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_duplicate_name_rejected(self):
        self._create_site(name="Padma Bridge")
        response = self.client.post(self.list_url, {"name": "Padma Bridge"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["errors"][0]["attr"])

    def test_duplicate_name_allowed_across_companies(self):
        other = Company.objects.create(name="Other Co")
        Site.objects.create(
            name="Shared",
            company=other,
            created_by=self.user,
        )
        response = self.client.post(self.list_url, {"name": "Shared"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_patch_same_name_allowed(self):
        site = self._create_site(name="Keep")
        response = self.client.patch(
            self._detail_url(site.pk),
            {"is_active": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class SiteFilterIsolationTests(SiteAPITestCase):
    def test_filter_by_is_active(self):
        self._create_site(name="Active", is_active=True)
        self._create_site(name="Inactive", is_active=False)

        response = self.client.get(self.list_url, {"is_active": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Active")

        response = self.client.get(self.list_url, {"is_active": "false"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Inactive")

    def test_filter_by_is_closed(self):
        open_site = self._create_site(name="Open")
        closed_site = self._create_site(
            name="Closed",
            is_closed=True,
            closed_at=timezone.now(),
        )

        response = self.client.get(self.list_url, {"is_closed": "false"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], open_site.pk)

        response = self.client.get(self.list_url, {"is_closed": "true"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], closed_site.pk)
        
    def test_cannot_create_site_under_other_company(self):
        other_company = Company.objects.create(name="Other Co")
        response = self.client.post(self.list_url, {"name": "Other Site", "company": other_company.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data["company"], other_company.pk)
        self.assertEqual(response.data["company"], self.company.pk)

    def test_cannot_see_other_company_sites(self):
        other_company = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111111",
            name="Other Admin",
            password="strong-pass-123",
            company=other_company,
        )
        Site.objects.create(
            name="Other Site",
            company=other_company,
            created_by=other_user,
        )
        self._create_site(name="Mine")

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Mine")

    def test_cannot_retrieve_other_company_site(self):
        other_company = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111112",
            name="Other Admin 2",
            password="strong-pass-123",
            company=other_company,
        )
        other_site = Site.objects.create(
            name="Secret",
            company=other_company,
            created_by=other_user,
        )
        response = self.client.get(self._detail_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SiteSubscriptionTests(SiteAPITestCase):
    def test_create_blocked_when_open_site_limit_exceeded(self):
        self.subscription.open_site_limit = 1
        self.subscription.save(update_fields=["open_site_limit"])
        self._create_site(name="Only Slot")

        response = self.client.post(self.list_url, {"name": "Overflow"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Site.objects.filter(name="Overflow").exists())
        self.assertEqual(response.data["errors"][0]["code"], status_codes.SUBSCRIPTION_LIMIT_EXCEEDED)

    def test_closed_site_does_not_count_toward_open_limit(self):
        self.subscription.open_site_limit = 1
        self.subscription.save(update_fields=["open_site_limit"])
        self._create_site(
            name="Closed Slot",
            is_closed=True,
            closed_at=timezone.now(),
        )

        response = self.client.post(self.list_url, {"name": "New Open"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(self.list_url, {"name": "Too Late"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Site.objects.filter(name="Too Late").exists())
        self.assertEqual(response.data["errors"][0]["code"], status_codes.SUBSCRIPTION_EXPIRED)

    def test_list_allowed_when_subscription_expired(self):
        self._create_site(name="Readable")
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_patch_blocked_when_subscription_expired(self):
        site = self._create_site(name="Editable")
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(site.pk),
            {"name": "No Write"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["code"], status_codes.SUBSCRIPTION_EXPIRED)
        site.refresh_from_db()
        self.assertEqual(site.name, "Editable")


class SiteCashAPITestCase(APITestCase):
    """Shared fixtures for nested site cash endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_cash_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)
        self.billing = self._create_billing(name="Basement")
        self.list_url = self._list_url(self.site.pk)

    def _grant_cash_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_sitecash",
            "add_sitecash",
            "change_sitecash",
            "delete_sitecash",
        ]
        ct = ContentType.objects.get_for_model(SiteCash)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _assign_site(self, user, site):
        return UserSite.objects.create(
            user=user,
            site=site,
            company=user.company,
            created_by=user,
        )

    def _create_billing(self, name="Basement", site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "name": name,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return BillingCategory.objects.create(**defaults)

    def _list_url(self, site_id):
        return reverse(
            "site-cash-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _detail_url(self, site_id, cash_id):
        return reverse(
            "site-cash-detail",
            kwargs={"version": "v1", "site_pk": site_id, "pk": cash_id},
        )

    def _create_cash(self, site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "date": timezone.localdate(),
            "type": SiteCashType.DEPOSIT,
            "amount": 1000,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return SiteCash.objects.create(**defaults)


class SiteCashAuthPermissionTests(SiteCashAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_cash_permissions(self.user, ["view_sitecash"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.DEPOSIT,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        cash = self._create_cash()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_cash_permissions(self.user, ["view_sitecash", "add_sitecash"])
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"amount": 2000},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_site_member_returns_403(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )

    def test_inactive_site_blocks_create(self):
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.DEPOSIT,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_site_still_allows_list(self):
        self._create_cash()
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_other_company_site_returns_403(self):
        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111111",
            name="Other Admin",
            password="strong-pass-123",
            company=other,
        )
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
            created_by=other_user,
        )
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SiteCashCRUDTests(SiteCashAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_deposit_success(self):
        today = timezone.localdate()
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "type": SiteCashType.DEPOSIT,
                "amount": 1500,
                "note": "Owner deposit",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["created_by"], self.user.pk)
        self.assertEqual(response.data["type"], SiteCashType.DEPOSIT)
        self.assertEqual(response.data["amount"], 1500)
        self.assertIsNone(response.data["category"])
        self.assertTrue(
            SiteCash.objects.filter(
                site=self.site,
                date=today,
                type=SiteCashType.DEPOSIT,
            ).exists()
        )

    def test_create_cost_with_billing_and_category(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.COST,
                "category": SiteCashCategory.FOOD,
                "billing": self.billing.pk,
                "amount": 800,
                "note": "Lunch",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], SiteCashType.COST)
        self.assertEqual(response.data["category"], SiteCashCategory.FOOD)
        self.assertEqual(response.data["billing"], self.billing.pk)

    def test_create_stamps_site_from_url(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.WITHDRAWAL,
                "amount": 200,
                "site": other_site.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)

    def test_list_uses_list_serializer_fields(self):
        cash = self._create_cash()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "date",
                "type",
                "category",
                "amount",
                "note",
                "billing",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(response.data[0]["id"], cash.pk)

    def test_retrieve_cash_detail(self):
        cash = self._create_cash(note="detail")
        response = self.client.get(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)
        self.assertIn("created_by", response.data)

    def test_patch_amount_and_note(self):
        cash = self._create_cash(amount=1000, note="old")
        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"amount": 1800, "note": "updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 1800)
        self.assertEqual(response.data["note"], "updated")
        cash.refresh_from_db()
        self.assertEqual(cash.amount, 1800)

    def test_delete_cash(self):
        cash = self._create_cash()
        response = self.client.delete(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(SiteCash.objects.filter(pk=cash.pk).exists())

    def test_put_not_allowed(self):
        cash = self._create_cash()
        response = self.client.put(
            self._detail_url(self.site.pk, cash.pk),
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.DEPOSIT,
                "amount": 1,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SiteCashValidationTests(SiteCashAPITestCase):
    def test_future_date_rejected(self):
        future = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            self.list_url,
            {
                "date": str(future),
                "type": SiteCashType.DEPOSIT,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_FUTURE_DATE,
        )

    def test_create_with_billing_from_other_site_rejected(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        other_billing = self._create_billing(name="Foreign Cat", site=other_site)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.COST,
                "category": SiteCashCategory.EQUIPMENT,
                "billing": other_billing.pk,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_update_billing_from_other_site_rejected(self):
        cash = self._create_cash(type=SiteCashType.COST)
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        other_billing = self._create_billing(name="Foreign Cat", site=other_site)
        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"billing": other_billing.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )


class SiteCashFilterIsolationTests(SiteCashAPITestCase):
    def test_filter_by_type(self):
        today = timezone.localdate()
        self._create_cash(date=today, type=SiteCashType.DEPOSIT)
        self._create_cash(
            date=today - timedelta(days=1),
            type=SiteCashType.COST,
            category=SiteCashCategory.FOOD,
            amount=50,
        )
        response = self.client.get(self.list_url, {"type": SiteCashType.COST})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type"], SiteCashType.COST)

    def test_filter_by_category(self):
        today = timezone.localdate()
        self._create_cash(
            date=today,
            type=SiteCashType.COST,
            category=SiteCashCategory.FOOD,
        )
        self._create_cash(
            date=today - timedelta(days=1),
            type=SiteCashType.COST,
            category=SiteCashCategory.EQUIPMENT,
            amount=80,
        )
        response = self.client.get(
            self.list_url, {"category": SiteCashCategory.EQUIPMENT}
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["category"], SiteCashCategory.EQUIPMENT)

    def test_filter_by_billing(self):
        cat_b = self._create_billing(name="Floor-1")
        self._create_cash(date=timezone.localdate(), billing=self.billing)
        self._create_cash(
            date=timezone.localdate() - timedelta(days=1),
            billing=cat_b,
            amount=200,
        )
        response = self.client.get(self.list_url, {"billing": cat_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["billing"], cat_b.pk)

    def test_nested_under_other_site_hides_cash(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, other_site)
        cash = self._create_cash()
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        response = self.client.get(self._detail_url(other_site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_see_other_company_cash(self):
        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811222333",
            name="Other Admin",
            password="strong-pass-123",
            company=other,
        )
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
            created_by=other_user,
        )
        SiteCash.objects.create(
            company=other,
            site=other_site,
            date=timezone.localdate(),
            type=SiteCashType.DEPOSIT,
            amount=999,
            created_by=other_user,
        )
        self._create_cash(amount=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["amount"], 100)


class SiteCashSubscriptionTests(SiteCashAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.DEPOSIT,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(SiteCash.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_cash()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_patch_blocked_when_subscription_expired(self):
        cash = self._create_cash(amount=100)
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"amount": 200},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        cash.refresh_from_db()
        self.assertEqual(cash.amount, 100)


class PrivateSiteCashAPITestCase(APITestCase):
    """Shared fixtures for nested private site cash endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_private_cash_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)
        self.billing = self._create_billing(name="Basement")
        self.list_url = self._list_url(self.site.pk)

    def _grant_private_cash_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_privatesitecash",
            "add_privatesitecash",
            "change_privatesitecash",
            "delete_privatesitecash",
        ]
        ct = ContentType.objects.get_for_model(PrivateSiteCash)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _assign_site(self, user, site):
        return UserSite.objects.create(
            user=user,
            site=site,
            company=user.company,
            created_by=user,
        )

    def _create_billing(self, name="Basement", site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "name": name,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return BillingCategory.objects.create(**defaults)

    def _list_url(self, site_id):
        return reverse(
            "site-private-cash-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _detail_url(self, site_id, cash_id):
        return reverse(
            "site-private-cash-detail",
            kwargs={"version": "v1", "site_pk": site_id, "pk": cash_id},
        )

    def _create_cash(self, site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "date": timezone.localdate(),
            "type": PrivateSiteCashType.BILL,
            "amount": 1000,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return PrivateSiteCash.objects.create(**defaults)


class PrivateSiteCashAuthPermissionTests(PrivateSiteCashAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_private_cash_permissions(self.user, ["view_privatesitecash"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.BILL,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        cash = self._create_cash()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_private_cash_permissions(
            self.user, ["view_privatesitecash", "add_privatesitecash"]
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"amount": 2000},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_site_member_returns_403(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )

    def test_inactive_site_blocks_create(self):
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.BILL,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_site_still_allows_list(self):
        self._create_cash()
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_other_company_site_returns_403(self):
        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111111",
            name="Other Admin",
            password="strong-pass-123",
            company=other,
        )
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
            created_by=other_user,
        )
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PrivateSiteCashCRUDTests(PrivateSiteCashAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_bill_success(self):
        today = timezone.localdate()
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "type": PrivateSiteCashType.BILL,
                "amount": 1500,
                "note": "Owner bill",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["created_by"], self.user.pk)
        self.assertEqual(response.data["type"], PrivateSiteCashType.BILL)
        self.assertEqual(response.data["amount"], 1500)
        self.assertTrue(
            PrivateSiteCash.objects.filter(
                site=self.site,
                date=today,
                type=PrivateSiteCashType.BILL,
            ).exists()
        )

    def test_create_cost_with_billing(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.COST,
                "billing": self.billing.pk,
                "amount": 800,
                "note": "Hidden cost",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], PrivateSiteCashType.COST)
        self.assertEqual(response.data["billing"], self.billing.pk)
        self.assertNotIn("category", response.data)

    def test_create_stamps_site_from_url(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.BILL,
                "amount": 200,
                "site": other_site.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)

    def test_list_uses_list_serializer_fields(self):
        cash = self._create_cash()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "date",
                "type",
                "amount",
                "note",
                "billing",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(response.data[0]["id"], cash.pk)

    def test_retrieve_cash_detail(self):
        cash = self._create_cash(note="detail")
        response = self.client.get(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)
        self.assertIn("created_by", response.data)
        self.assertNotIn("category", response.data)

    def test_patch_amount_and_note(self):
        cash = self._create_cash(amount=1000, note="old")
        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"amount": 1800, "note": "updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 1800)
        self.assertEqual(response.data["note"], "updated")
        cash.refresh_from_db()
        self.assertEqual(cash.amount, 1800)

    def test_delete_cash(self):
        cash = self._create_cash()
        response = self.client.delete(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PrivateSiteCash.objects.filter(pk=cash.pk).exists())

    def test_put_not_allowed(self):
        cash = self._create_cash()
        response = self.client.put(
            self._detail_url(self.site.pk, cash.pk),
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.BILL,
                "amount": 1,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class PrivateSiteCashValidationTests(PrivateSiteCashAPITestCase):
    def test_future_date_rejected(self):
        future = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            self.list_url,
            {
                "date": str(future),
                "type": PrivateSiteCashType.BILL,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_FUTURE_DATE,
        )

    def test_create_with_billing_from_other_site_rejected(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        other_billing = self._create_billing(name="Foreign Cat", site=other_site)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.COST,
                "billing": other_billing.pk,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_update_billing_from_other_site_rejected(self):
        cash = self._create_cash(type=PrivateSiteCashType.COST)
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        other_billing = self._create_billing(name="Foreign Cat", site=other_site)
        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"billing": other_billing.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )


class PrivateSiteCashFilterIsolationTests(PrivateSiteCashAPITestCase):
    def test_filter_by_type(self):
        today = timezone.localdate()
        self._create_cash(date=today, type=PrivateSiteCashType.BILL)
        self._create_cash(
            date=today - timedelta(days=1),
            type=PrivateSiteCashType.COST,
            amount=50,
        )
        response = self.client.get(self.list_url, {"type": PrivateSiteCashType.COST})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type"], PrivateSiteCashType.COST)

    def test_filter_by_billing(self):
        cat_b = self._create_billing(name="Floor-1")
        self._create_cash(date=timezone.localdate(), billing=self.billing)
        self._create_cash(
            date=timezone.localdate() - timedelta(days=1),
            billing=cat_b,
            amount=200,
        )
        response = self.client.get(self.list_url, {"billing": cat_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["billing"], cat_b.pk)

    def test_nested_under_other_site_hides_cash(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, other_site)
        cash = self._create_cash()
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        response = self.client.get(self._detail_url(other_site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_see_other_company_cash(self):
        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811222333",
            name="Other Admin",
            password="strong-pass-123",
            company=other,
        )
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
            created_by=other_user,
        )
        PrivateSiteCash.objects.create(
            company=other,
            site=other_site,
            date=timezone.localdate(),
            type=PrivateSiteCashType.BILL,
            amount=999,
            created_by=other_user,
        )
        self._create_cash(amount=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["amount"], 100)


class PrivateSiteCashSubscriptionTests(PrivateSiteCashAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": PrivateSiteCashType.BILL,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(PrivateSiteCash.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_cash()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_patch_blocked_when_subscription_expired(self):
        cash = self._create_cash(amount=100)
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(self.site.pk, cash.pk),
            {"amount": 200},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        cash.refresh_from_db()
        self.assertEqual(cash.amount, 100)