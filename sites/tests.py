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
from activity.models import ActivityAction, ActivityEntityType, ActivityLog
from sites.models import (
    BillingCategory,
    PrivateSiteCash,
    PrivateSiteCashType,
    Site,
    SiteCash,
    SiteCashType,
)
from subscription.models import Subscription
from accounts.models import UserSite
from core import status_codes
from labours.models import DailyRecord, Labour

User = get_user_model()


def _list_results(response):
    """Return list rows from a paginated or unpaginated list response."""
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


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
            is_companyadmin=True,
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
        self.assertEqual(_list_results(response), [])

    def test_create_site_success(self):
        response = self.client.post(self.list_url, {"name": "Padma Bridge"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Padma Bridge")
        self.assertTrue(response.data["is_active"])
        self.assertFalse(response.data["is_closed"])
        self.assertIsNone(response.data["closed_at"])
        self.assertEqual(response.data["company"], self.company.pk)
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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertCountEqual(
            _list_results(response)[0].keys(),
            ["id", "name", "is_active", "is_closed"],
        )
        self.assertEqual(_list_results(response)[0]["id"], site.pk)

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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Active")

        response = self.client.get(self.list_url, {"is_active": "false"})
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Inactive")

    def test_filter_by_is_closed(self):
        open_site = self._create_site(name="Open")
        closed_site = self._create_site(
            name="Closed",
            is_closed=True,
            closed_at=timezone.now(),
        )

        response = self.client.get(self.list_url, {"is_closed": "false"})
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], open_site.pk)

        response = self.client.get(self.list_url, {"is_closed": "true"})
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], closed_site.pk)
        
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
        )
        self._create_site(name="Mine")

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Mine")

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
        )
        response = self.client.get(self._detail_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SiteAssignmentVisibilityTests(SiteAPITestCase):
    def test_companyadmin_sees_all_company_sites(self):
        a = self._create_site(name="Alpha")
        b = self._create_site(name="Beta")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            [row["id"] for row in _list_results(response)],
            [a.pk, b.pk],
        )

    def test_non_admin_sees_only_assigned_sites(self):
        assigned = self._create_site(name="Assigned")
        self._create_site(name="Unassigned")

        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        UserSite.objects.create(
            user=self.user,
            site=assigned,
            company=self.company,
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], assigned.pk)

    def test_non_admin_cannot_retrieve_unassigned_site(self):
        site = self._create_site(name="Hidden")
        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self._detail_url(site.pk))
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
        self.assertEqual(len(_list_results(response)), 1)

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


class SiteActiveLabourTests(SiteAPITestCase):
    def _active_labour_url(self, site_id):
        return reverse(
            "site-active-labour",
            kwargs={"version": "v1", "pk": site_id},
        )

    def test_lists_active_labours_for_site_without_pagination(self):
        site = self._create_site(name="Yard")
        active = Labour.objects.create(
            name="Karim",
            company=self.company,
            current_site=site,
            is_active=True,
            default_salary=500,
        )
        Labour.objects.create(
            name="Inactive Worker",
            company=self.company,
            current_site=site,
            is_active=False,
            default_salary=400,
        )
        other_site = self._create_site(name="Other Yard")
        Labour.objects.create(
            name="Elsewhere",
            company=self.company,
            current_site=other_site,
            is_active=True,
            default_salary=400,
        )

        response = self.client.get(self._active_labour_url(site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertNotIn("results", response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], active.pk)
        self.assertEqual(response.data[0]["name"], "Karim")
        self.assertTrue(response.data[0]["is_active"])

    def test_empty_list_when_no_active_labours(self):
        site = self._create_site(name="Empty Yard")
        response = self.client.get(self._active_labour_url(site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_unauthenticated_returns_401(self):
        site = self._create_site(name="Yard")
        self.client.force_authenticate(user=None)
        response = self.client.get(self._active_labour_url(site.pk))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_member_cannot_list(self):
        site = self._create_site(name="Restricted")
        member = User.objects.create_user(
            phone_number="+8801711111111",
            name="Manager",
            password="strong-pass-123",
            company=self.company,
            is_companyadmin=False,
        )
        self._grant_site_permissions(member, ["view_site"])
        self.client.force_authenticate(user=member)
        response = self.client.get(self._active_labour_url(site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


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
        )

    def _create_billing(self, name="Basement", site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "name": name,
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

    def _by_date_url(self, site_id, cash_date):
        return reverse(
            "site-cash-by-date",
            kwargs={
                "version": "v1",
                "site_pk": site_id,
                "cash_date": str(cash_date),
            },
        )

    def _pending_log_url(self, site_id, cash_date):
        return reverse(
            "site-cash-pending-log",
            kwargs={
                "version": "v1",
                "site_pk": site_id,
                "cash_date": str(cash_date),
            },
        )

    def _create_cash(self, site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "date": timezone.localdate(),
            "type": SiteCashType.DEPOSIT,
            "amount": 1000,
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
        self.assertEqual(len(_list_results(response)), 1)

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
        )
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_companyadmin_bypasses_site_assignment(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        self.user.is_companyadmin = True
        self.user.save(update_fields=["is_companyadmin"])
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.DEPOSIT,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_companyadmin_still_needs_model_permission(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        self.user.is_companyadmin = True
        self.user.save(update_fields=["is_companyadmin"])
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

    def test_companyadmin_cannot_access_other_company_site(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        self.user.is_companyadmin = True
        self.user.save(update_fields=["is_companyadmin"])
        self.client.force_authenticate(user=self.user)

        other = Company.objects.create(name="Other Co")
        other_user = User.objects.create_user(
            phone_number="+8801811111112",
            name="Other Admin",
            password="strong-pass-123",
            company=other,
        )
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
        )
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )


class SiteCashCRUDTests(SiteCashAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])

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
        self.assertEqual(response.data["type"], SiteCashType.DEPOSIT)
        self.assertEqual(response.data["amount"], 1500)
        self.assertTrue(
            SiteCash.objects.filter(
                site=self.site,
                date=today,
                type=SiteCashType.DEPOSIT,
            ).exists()
        )

    def test_create_cost_with_billing(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.COST,
                "billing": self.billing.pk,
                "amount": 800,
                "note": "Lunch",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], SiteCashType.COST)
        self.assertEqual(response.data["billing"], self.billing.pk)

    def test_create_stamps_site_from_url(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertCountEqual(
            _list_results(response)[0].keys(),
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
        self.assertEqual(_list_results(response)[0]["id"], cash.pk)

    def test_retrieve_cash_detail(self):
        cash = self._create_cash(note="detail")
        response = self.client.get(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)
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
        )
        other_billing = self._create_billing(name="Foreign Cat", site=other_site)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": SiteCashType.COST,
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
            amount=50,
        )
        response = self.client.get(self.list_url, {"type": SiteCashType.COST})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["type"], SiteCashType.COST)

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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["billing"], cat_b.pk)

    def test_nested_under_other_site_hides_cash(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self._assign_site(self.user, other_site)
        cash = self._create_cash()
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])
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
        )
        SiteCash.objects.create(
            company=other,
            site=other_site,
            date=timezone.localdate(),
            type=SiteCashType.DEPOSIT,
            amount=999,
        )
        self._create_cash(amount=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["amount"], 100)


class SiteCashByDateTests(SiteCashAPITestCase):
    def test_lists_cash_for_date_without_pagination(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        first = self._create_cash(date=today, amount=1000, type=SiteCashType.DEPOSIT)
        second = self._create_cash(date=today, amount=200, type=SiteCashType.COST)
        self._create_cash(date=yesterday, amount=500)

        response = self.client.get(self._by_date_url(self.site.pk, today))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertNotIn("results", response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(
            {row["id"] for row in response.data},
            {first.pk, second.pk},
        )
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

    def test_empty_list_when_no_cash_for_date(self):
        self._create_cash(date=timezone.localdate() - timedelta(days=1))
        response = self.client.get(
            self._by_date_url(self.site.pk, timezone.localdate())
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_invalid_calendar_date_returns_400(self):
        response = self.client.get(self._by_date_url(self.site.pk, "2026-02-30"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(
            self._by_date_url(self.site.pk, timezone.localdate())
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_not_allowed(self):
        response = self.client.post(
            self._by_date_url(self.site.pk, timezone.localdate()),
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_numeric_detail_still_works(self):
        cash = self._create_cash()
        response = self.client.get(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], cash.pk)


class SiteCashPendingLogTests(SiteCashAPITestCase):
    def _create_cash_log(self, *, site=None, business_date=None, reviewed=False, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "actor": self.user,
            "actor_name": self.user.name,
            "action": ActivityAction.CREATED,
            "entity_type": ActivityEntityType.SITE_CASH,
            "entity_id": 1,
            "business_date": business_date or timezone.localdate(),
            "changes": {"amount": 100},
        }
        defaults.update(kwargs)
        log = ActivityLog.objects.create(**defaults)
        if reviewed:
            log.reviewed_at = timezone.now()
            log.reviewed_by = self.user
            log.save(update_fields=["reviewed_at", "reviewed_by"])
        return log

    def test_lists_pending_site_cash_logs_without_pagination(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        pending = self._create_cash_log(business_date=today, entity_id=10)
        self._create_cash_log(business_date=today, entity_id=11, reviewed=True)
        self._create_cash_log(business_date=yesterday, entity_id=12)
        self._create_cash_log(
            business_date=today,
            entity_id=13,
            entity_type=ActivityEntityType.DAILY_RECORD,
        )

        response = self.client.get(self._pending_log_url(self.site.pk, today))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertNotIn("results", response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], pending.pk)
        self.assertEqual(response.data[0]["entity_type"], ActivityEntityType.SITE_CASH)
        self.assertIsNone(response.data[0]["reviewed_at"])

    def test_empty_list_when_no_pending_logs(self):
        self._create_cash_log(reviewed=True)
        response = self.client.get(
            self._pending_log_url(self.site.pk, timezone.localdate())
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_other_site_logs_hidden(self):
        other_site = Site.objects.create(name="Other Yard", company=self.company)
        self._assign_site(self.user, other_site)
        self._create_cash_log(site=other_site)
        response = self.client.get(
            self._pending_log_url(self.site.pk, timezone.localdate())
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_invalid_calendar_date_returns_400(self):
        response = self.client.get(self._pending_log_url(self.site.pk, "2026-02-30"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(
            self._pending_log_url(self.site.pk, timezone.localdate())
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_not_allowed(self):
        response = self.client.post(
            self._pending_log_url(self.site.pk, timezone.localdate()),
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


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
        self.assertEqual(len(_list_results(response)), 1)

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
        )

    def _create_billing(self, name="Basement", site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "name": name,
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
        self.assertEqual(len(_list_results(response)), 1)

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
        )
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PrivateSiteCashCRUDTests(PrivateSiteCashAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])

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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertCountEqual(
            _list_results(response)[0].keys(),
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
        self.assertEqual(_list_results(response)[0]["id"], cash.pk)

    def test_retrieve_cash_detail(self):
        cash = self._create_cash(note="detail")
        response = self.client.get(self._detail_url(self.site.pk, cash.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)
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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["type"], PrivateSiteCashType.COST)

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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["billing"], cat_b.pk)

    def test_nested_under_other_site_hides_cash(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self._assign_site(self.user, other_site)
        cash = self._create_cash()
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])
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
        )
        PrivateSiteCash.objects.create(
            company=other,
            site=other_site,
            date=timezone.localdate(),
            type=PrivateSiteCashType.BILL,
            amount=999,
        )
        self._create_cash(amount=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["amount"], 100)


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
        self.assertEqual(len(_list_results(response)), 1)

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


class SiteDailyReportAPITestCase(APITestCase):
    """Shared fixtures for ``/sites/<pk>/daily-reports``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
        )
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
        )
        self.report_date = timezone.localdate()
        self.url = reverse(
            "site-daily-reports",
            kwargs={"version": "v1", "pk": self.site.pk},
        )

    def _grant_private_cash_view(self, user):
        ct = ContentType.objects.get_for_model(PrivateSiteCash)
        perm = Permission.objects.get(content_type=ct, codename="view_privatesitecash")
        user.user_permissions.add(perm)
        # Clear permission cache so has_perm sees the new grant.
        user = User.objects.get(pk=user.pk)
        self.client.force_authenticate(user=user)
        return user

    def _create_labour(self, name="Karim"):
        return Labour.objects.create(
            name=name,
            company=self.company,
            current_site=self.site,
            default_salary=500,
        )


class SiteDailyReportAuthTests(SiteDailyReportAPITestCase):
    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_other_company_site_returns_403(self):
        other_company = Company.objects.create(name="Other Co")
        other_site = Site.objects.create(
            name="Foreign Site",
            company=other_company,
        )
        url = reverse(
            "site-daily-reports",
            kwargs={"version": "v1", "pk": other_site.pk},
        )
        response = self.client.get(url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unassigned_site_returns_403(self):
        other = Site.objects.create(
            name="Unassigned",
            company=self.company,
        )
        url = reverse(
            "site-daily-reports",
            kwargs={"version": "v1", "pk": other.pk},
        )
        response = self.client.get(url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_date_query_param_defaults_to_today(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["date"], str(self.report_date))

    def test_invalid_date_returns_400(self):
        response = self.client.get(self.url, {"date": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date")


class SiteDailyReportSummaryTests(SiteDailyReportAPITestCase):
    def test_empty_day_returns_zeros(self):
        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["date"], str(self.report_date))
        self.assertEqual(Decimal(response.data["present_count"]), Decimal("0"))
        self.assertEqual(response.data["labour_payment"], 0)
        self.assertEqual(response.data["labour_return"], 0)
        self.assertEqual(response.data["deposit"], 0)
        self.assertEqual(response.data["withdrawal"], 0)
        self.assertEqual(response.data["site_cost"], 0)
        self.assertEqual(response.data["total_cost"], 0)
        self.assertEqual(response.data["remaining"], 0)
        self.assertEqual(response.data["balance"], 0)
        self.assertEqual(response.data["previous_balance"], 0)
        self.assertNotIn("total_salary", response.data)

    def test_public_summary_aggregates(self):
        labour = self._create_labour()
        DailyRecord.objects.create(
            company=self.company,
            labour=labour,
            site=self.site,
            date=self.report_date,
            present=Decimal("1.5"),
            wage=500,
            extra_earn=100,
            advance_pay=1000,
            return_amount=200,
        )
        labour_b = self._create_labour(name="Rahim")
        DailyRecord.objects.create(
            company=self.company,
            labour=labour_b,
            site=self.site,
            date=self.report_date,
            advance_pay=150,
        )
        SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.DEPOSIT,
            date=self.report_date,
            amount=5000,
        )
        SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.COST,
            date=self.report_date,
            amount=300,
        )

        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(response.data["present_count"]), Decimal("1.5"))
        self.assertEqual(response.data["labour_payment"], 1150)
        self.assertEqual(response.data["labour_return"], 200)
        self.assertEqual(response.data["deposit"], 5000)
        self.assertEqual(response.data["site_cost"], 300)
        # total_cost = labour_payment + site_cost (return is cash in)
        self.assertEqual(response.data["total_cost"], 1450)
        # remaining = (deposit + return) - (withdrawal + total_cost) = 5200 - 1450
        self.assertEqual(response.data["remaining"], 3750)
        self.assertEqual(response.data["balance"], 3750)
        self.assertNotIn("total_salary", response.data)

    def test_balance_and_previous_balance(self):
        yesterday = self.report_date - timedelta(days=1)
        SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.DEPOSIT,
            date=yesterday,
            amount=1000,
        )
        SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.DEPOSIT,
            date=self.report_date,
            amount=500,
        )
        SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.WITHDRAWAL,
            date=self.report_date,
            amount=200,
        )

        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["previous_balance"], 1000)
        self.assertEqual(response.data["remaining"], 300)  # 500 - 200
        self.assertEqual(response.data["balance"], 1300)  # 1000 + 300
        self.assertEqual(response.data["deposit"], 500)
        self.assertEqual(response.data["withdrawal"], 200)

    def test_private_fields_included_with_permission(self):
        self._grant_private_cash_view(self.user)
        labour = self._create_labour()
        DailyRecord.objects.create(
            company=self.company,
            labour=labour,
            site=self.site,
            date=self.report_date,
            present=Decimal("1"),
            wage=500,
            extra_earn=50,
        )
        PrivateSiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=PrivateSiteCashType.BILL,
            date=self.report_date,
            amount=1000,
        )
        PrivateSiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=PrivateSiteCashType.COST,
            date=self.report_date,
            amount=250,
        )

        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_salary"], 500)
        self.assertEqual(response.data["extra_earnings"], 50)

    def test_private_fields_omitted_without_permission(self):
        PrivateSiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=PrivateSiteCashType.BILL,
            date=self.report_date,
            amount=1000,
        )
        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("total_salary", response.data)
        self.assertNotIn("extra_earnings", response.data)

    def test_other_site_data_not_included(self):
        other = Site.objects.create(
            name="Metro",
            company=self.company,
        )
        SiteCash.objects.create(
            company=self.company,
            site=other,
            type=SiteCashType.DEPOSIT,
            date=self.report_date,
            amount=9999,
        )
        response = self.client.get(self.url, {"date": str(self.report_date)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deposit"], 0)
        self.assertEqual(response.data["balance"], 0)


class SiteBillingCategoryAPITestCase(APITestCase):
    """Shared fixtures for nested ``/sites/<pk>/billing-categories``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)
        self.subscription.open_site_limit = 5
        self.subscription.save(update_fields=["open_site_limit"])

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_billing_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
        )
        self._assign_site(self.user, self.site)
        self.list_url = self._list_url(self.site.pk)

    def _grant_billing_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_billingcategory",
            "add_billingcategory",
            "change_billingcategory",
            "delete_billingcategory",
        ]
        ct = ContentType.objects.get_for_model(BillingCategory)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _assign_site(self, user, site):
        return UserSite.objects.create(
            user=user,
            site=site,
            company=user.company,
        )

    def _list_url(self, site_id):
        return reverse(
            "site-billing-category-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _active_billing_url(self, site_id):
        return reverse(
            "site-billing-category-active-billing",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _detail_url(self, site_id, billing_id):
        return reverse(
            "site-billing-category-detail",
            kwargs={"version": "v1", "site_pk": site_id, "pk": billing_id},
        )

    def _create_billing(self, site=None, **kwargs):
        site = site or self.site
        defaults = {
            "company": site.company,
            "site": site,
            "name": "Basement",
        }
        defaults.update(kwargs)
        return BillingCategory.objects.create(**defaults)


class SiteBillingCategoryAuthPermissionTests(SiteBillingCategoryAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_billing_permissions(self.user, ["view_billingcategory"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url, {"name": "Floor-1"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        billing = self._create_billing()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_billing_permissions(
            self.user, ["view_billingcategory", "add_billingcategory"]
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self._detail_url(self.site.pk, billing.pk),
            {"name": "Renamed"},
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
        response = self.client.post(self.list_url, {"name": "Floor-1"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_site_still_allows_list(self):
        self._create_billing()
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)

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
        )
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SiteBillingCategoryCRUDTests(SiteBillingCategoryAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])

    def test_create_success(self):
        response = self.client.post(
            self.list_url,
            {"name": "Basement", "display_order": 1},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["name"], "Basement")
        self.assertEqual(response.data["display_order"], 1)
        self.assertTrue(response.data["is_active"])
        self.assertFalse(response.data["is_done"])
        self.assertTrue(
            BillingCategory.objects.filter(
                site=self.site, name="Basement"
            ).exists()
        )

    def test_create_stamps_site_from_url(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        response = self.client.post(
            self.list_url,
            {"name": "Basement", "site": other_site.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)

    def test_list_uses_list_serializer_fields(self):
        billing = self._create_billing()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertCountEqual(
            results[0].keys(),
            [
                "id",
                "name",
                "display_order",
                "is_active",
                "is_done",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(results[0]["id"], billing.pk)

    def test_retrieve_billing_detail(self):
        billing = self._create_billing(name="Floor-1")
        response = self.client.get(self._detail_url(self.site.pk, billing.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Floor-1")
        self.assertIn("company", response.data)
    def test_patch_name_and_display_order(self):
        billing = self._create_billing(name="Basement", display_order=0)
        response = self.client.patch(
            self._detail_url(self.site.pk, billing.pk),
            {"name": "Floor-1", "display_order": 2},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Floor-1")
        self.assertEqual(response.data["display_order"], 2)
        billing.refresh_from_db()
        self.assertEqual(billing.name, "Floor-1")

    def test_mark_done_deactivates(self):
        billing = self._create_billing(is_active=True, is_done=False)
        response = self.client.patch(
            self._detail_url(self.site.pk, billing.pk),
            {"is_done": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_done"])
        self.assertFalse(response.data["is_active"])
        billing.refresh_from_db()
        self.assertTrue(billing.is_done)
        self.assertFalse(billing.is_active)

    def test_create_as_done_is_inactive(self):
        response = self.client.post(
            self.list_url,
            {"name": "Done Floor", "is_done": True, "is_active": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["is_done"])
        self.assertFalse(response.data["is_active"])

    def test_delete_billing(self):
        billing = self._create_billing()
        response = self.client.delete(self._detail_url(self.site.pk, billing.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BillingCategory.objects.filter(pk=billing.pk).exists())

    def test_put_not_allowed(self):
        billing = self._create_billing()
        response = self.client.put(
            self._detail_url(self.site.pk, billing.pk),
            {"name": "Basement"},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SiteBillingCategoryValidationTests(SiteBillingCategoryAPITestCase):
    def test_duplicate_name_on_same_site_rejected(self):
        self._create_billing(name="Basement")
        response = self.client.post(self.list_url, {"name": "Basement"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.BILLING_CATEGORY_NAME_EXISTS,
        )

    def test_same_name_on_other_site_allowed(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self._assign_site(self.user, other_site)
        self._create_billing(name="Basement", site=other_site)
        response = self.client.post(self.list_url, {"name": "Basement"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_rename_to_existing_name_rejected(self):
        self._create_billing(name="Basement")
        other = self._create_billing(name="Floor-1")
        response = self.client.patch(
            self._detail_url(self.site.pk, other.pk),
            {"name": "Basement"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.BILLING_CATEGORY_NAME_EXISTS,
        )


class SiteBillingCategoryFilterIsolationTests(SiteBillingCategoryAPITestCase):
    def test_filter_by_is_active(self):
        self._create_billing(name="Active", is_active=True)
        self._create_billing(name="Inactive", is_active=False)
        response = self.client.get(self.list_url, {"is_active": "false"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Inactive")

    def test_filter_by_is_done(self):
        self._create_billing(name="Open", is_done=False)
        self._create_billing(name="Done", is_done=True, is_active=False)
        response = self.client.get(self.list_url, {"is_done": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Done")

    def test_other_site_categories_not_listed(self):
        other = Site.objects.create(
            name="Metro",
            company=self.company,
        )
        self._create_billing(name="Mine")
        self._create_billing(name="Theirs", site=other)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Mine")

    def test_ordered_by_display_order(self):
        self._create_billing(name="Second", display_order=2)
        self._create_billing(name="First", display_order=1)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["name"] for row in _list_results(response)],
            ["First", "Second"],
        )


class SiteBillingCategoryActiveBillingTests(SiteBillingCategoryAPITestCase):
    def test_lists_active_billing_without_pagination(self):
        active = self._create_billing(name="Active", is_active=True, display_order=2)
        self._create_billing(name="Inactive", is_active=False, display_order=1)
        also_active = self._create_billing(
            name="Also Active", is_active=True, display_order=1
        )

        response = self.client.get(self._active_billing_url(self.site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertNotIn("results", response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(
            [row["name"] for row in response.data],
            ["Also Active", "Active"],
        )
        self.assertEqual(
            {row["id"] for row in response.data},
            {active.pk, also_active.pk},
        )

    def test_empty_list_when_no_active_billing(self):
        self._create_billing(name="Inactive", is_active=False)
        response = self.client.get(self._active_billing_url(self.site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self._active_billing_url(self.site.pk))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_not_allowed(self):
        response = self.client.post(self._active_billing_url(self.site.pk), {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SiteBillingCategorySubscriptionTests(SiteBillingCategoryAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(self.list_url, {"name": "Basement"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(BillingCategory.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_billing()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)

    def test_patch_blocked_when_subscription_expired(self):
        billing = self._create_billing(name="Basement")
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(self.site.pk, billing.pk),
            {"name": "Renamed"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
