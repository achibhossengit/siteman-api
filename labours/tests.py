from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserSite
from company.models import Company
from core import status_codes
from labours.models import (
    Attendance,
    Labour,
    LabourPayment,
    LabourPaymentCategory,
    LabourPaymentType,
    LabourSession,
)
from sites.models import BillingCategory, Site
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
            is_companyadmin=True,
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
            "current_site": self.site,
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
            {
                "name": "Forced",
                "current_site": self.site.pk,
                "is_active": False,
                "default_salary": 500,
            },
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
                "last_session_date",
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
    def test_current_site_is_optional(self):
        response = self.client.post(
            self.list_url,
            {"name": "Unassigned", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["current_site"])
        self.assertTrue(
            Labour.objects.filter(name="Unassigned", current_site__isnull=True).exists()
        )

    def test_can_clear_current_site(self):
        labour = self._create_labour(name="Movable")
        response = self.client.patch(
            self._detail_url(labour.pk),
            {"current_site": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["current_site"])
        labour.refresh_from_db()
        self.assertIsNone(labour.current_site_id)

    def test_duplicate_name_rejected(self):
        self._create_labour(name="Karim")
        response = self.client.post(
            self.list_url,
            {
                "name": "Karim",
                "current_site": self.site.pk,
                "default_salary": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["errors"][0]["attr"])

    def test_duplicate_name_allowed_across_companies(self):
        other = Company.objects.create(name="Other Co")
        other_site = Site.objects.create(
            name="Other Site",
            company=other,
            created_by=self.user,
        )
        Labour.objects.create(
            name="Shared",
            company=other,
            created_by=self.user,
            current_site=other_site,
            default_salary=500,
        )
        response = self.client.post(
            self.list_url,
            {
                "name": "Shared",
                "current_site": self.site.pk,
                "default_salary": 500,
            },
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
            {
                "name": "Hijack",
                "company": other.pk,
                "current_site": self.site.pk,
                "default_salary": 500,
            },
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
            current_site=Site.objects.create(
                name="Other Site",
                company=other,
                created_by=other_user,
            ),
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
            current_site=Site.objects.create(
                name="Other Site",
                company=other,
                created_by=other_user,
            ),
            default_salary=500,
        )
        response = self.client.get(self._detail_url(foreign.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LabourAssignmentVisibilityTests(LabourAPITestCase):
    def test_companyadmin_sees_all_company_labours(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        a = self._create_labour(name="On Padma", current_site=self.site)
        b = self._create_labour(name="On Other", current_site=other_site)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            [row["id"] for row in response.data],
            [a.pk, b.pk],
        )

    def test_non_admin_sees_only_assigned_site_labours(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        assigned_labour = self._create_labour(name="Mine", current_site=self.site)
        self._create_labour(name="Theirs", current_site=other_site)

        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
            created_by=self.user,
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], assigned_labour.pk)

    def test_non_admin_cannot_retrieve_unassigned_site_labour(self):
        labour = self._create_labour(name="Hidden")
        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self._detail_url(labour.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_companyadmin_sees_unassigned_labours(self):
        unassigned = self._create_labour(name="Pool", current_site=None)
        assigned = self._create_labour(name="On Site", current_site=self.site)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            [row["id"] for row in response.data],
            [unassigned.pk, assigned.pk],
        )

    def test_non_admin_does_not_see_unassigned_labours(self):
        self._create_labour(name="Pool", current_site=None)
        assigned = self._create_labour(name="On Site", current_site=self.site)

        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
            created_by=self.user,
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], assigned.pk)


class LabourSubscriptionTests(LabourAPITestCase):
    def test_create_blocked_when_active_labour_limit_exceeded(self):
        self.subscription.active_labour_limit = 1
        self.subscription.save(update_fields=["active_labour_limit"])
        self._create_labour(name="Only Slot")

        response = self.client.post(
            self.list_url,
            {
                "name": "Overflow",
                "current_site": self.site.pk,
                "default_salary": 500,
            },
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
            {
                "name": "New Active",
                "current_site": self.site.pk,
                "default_salary": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            {
                "name": "Too Late",
                "current_site": self.site.pk,
                "default_salary": 500,
            },
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


class LabourSessionCacheTests(LabourAPITestCase):
    def _create_session(self, labour, created_date):
        return LabourSession.objects.create(
            company=self.company,
            labour=labour,
            start_date=created_date,
            end_date=created_date,
            created_date=created_date,
            present_days=Decimal("1"),
            salary_earnings=500,
            extra_earnings=0,
            total_payment=0,
            total_return=0,
            affected_attendance_rows=1,
            affected_payment_rows=0,
            created_by=self.user,
        )

    def test_last_session_date_tracks_latest_session_save_and_delete(self):
        labour = self._create_labour(name="Session Worker")
        older_date = timezone.localdate() - timedelta(days=2)
        latest_date = timezone.localdate() - timedelta(days=1)

        older = self._create_session(labour, older_date)
        labour.refresh_from_db()
        self.assertEqual(labour.last_session_date, older_date)

        latest = self._create_session(labour, latest_date)
        labour.refresh_from_db()
        self.assertEqual(labour.last_session_date, latest_date)

        latest.delete()
        labour.refresh_from_db()
        self.assertEqual(labour.last_session_date, older_date)

        older.delete()
        labour.refresh_from_db()
        self.assertIsNone(labour.last_session_date)


class LabourPaymentAPITestCase(APITestCase):
    """Shared fixtures for nested labour payment endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_payment_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.list_url = self._list_url(self.labour.pk)

    def _grant_payment_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_labourpayment",
            "add_labourpayment",
            "change_labourpayment",
            "delete_labourpayment",
        ]
        ct = ContentType.objects.get_for_model(LabourPayment)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _assign_site(self, user, site):
        return UserSite.objects.create(
            user=user,
            site=site,
            company=user.company,
            created_by=user,
        )

    def _list_url(self, labour_id):
        return reverse(
            "labour-payment-list",
            kwargs={"version": "v1", "labour_pk": labour_id},
        )

    def _detail_url(self, labour_id, payment_id):
        return reverse(
            "labour-payment-detail",
            kwargs={"version": "v1", "labour_pk": labour_id, "pk": payment_id},
        )

    def _create_payment(self, labour=None, site=None, **kwargs):
        labour = labour or self.labour
        site = site or labour.current_site
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": site,
            "date": timezone.localdate(),
            "type": LabourPaymentType.PAYMENT,
            "category": LabourPaymentCategory.ADVANCE,
            "amount": 1000,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LabourPayment.objects.create(**defaults)


class LabourPaymentAuthPermissionTests(LabourPaymentAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_payment_permissions(self.user, ["view_labourpayment"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        payment = self._create_payment()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_payment_permissions(
            self.user, ["view_labourpayment", "add_labourpayment"]
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self._detail_url(self.labour.pk, payment.pk),
            {"amount": 2000},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_site_member_returns_403(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_labour_returns_403(self):
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
        foreign_labour = Labour.objects.create(
            name="Secret",
            company=other,
            created_by=other_user,
            current_site=other_site,
            default_salary=500,
        )
        response = self.client.get(self._list_url(foreign_labour.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_labour_blocks_create(self):
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_INACTIVE,
        )

    def test_inactive_site_blocks_create(self):
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_labour_still_allows_list(self):
        self._create_payment()
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_unassigned_labour_blocks_create_for_companyadmin(self):
        self.user.is_companyadmin = True
        self.user.save(update_fields=["is_companyadmin"])
        self.labour.current_site = None
        self.labour.save(update_fields=["current_site"])
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_UNASSIGNED,
        )

    def test_unassigned_labour_blocks_non_admin(self):
        self.labour.current_site = None
        self.labour.save(update_fields=["current_site"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_UNASSIGNED,
        )


class LabourPaymentCRUDTests(LabourPaymentAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_payment_success(self):
        today = timezone.localdate()
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 1500,
                "note": "Friday advance",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["labour"], self.labour.pk)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["created_by"], self.user.pk)
        self.assertEqual(response.data["amount"], 1500)
        self.assertEqual(response.data["category"], LabourPaymentCategory.ADVANCE)
        self.assertFalse(response.data["is_sealed"])
        self.assertTrue(
            LabourPayment.objects.filter(
                labour=self.labour,
                date=today,
                type=LabourPaymentType.PAYMENT,
            ).exists()
        )

    def test_create_return_without_category(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.RETURN,
                "amount": 300,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], LabourPaymentType.RETURN)
        self.assertIsNone(response.data["category"])

    def test_create_return_with_category_allowed(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.RETURN,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 300,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["category"], LabourPaymentCategory.ADVANCE)

    def test_create_stamps_site_from_labour_current_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.FOODING,
                "amount": 200,
                "site": other_site.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)

    def test_create_ignores_client_is_sealed_true(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 500,
                "is_sealed": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["is_sealed"])

    def test_list_uses_list_serializer_fields(self):
        payment = self._create_payment()
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
                "site",
                "is_sealed",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(response.data[0]["id"], payment.pk)

    def test_retrieve_payment_detail(self):
        payment = self._create_payment(note="detail")
        response = self.client.get(self._detail_url(self.labour.pk, payment.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)
        self.assertIn("created_by", response.data)

    def test_patch_amount_and_note(self):
        payment = self._create_payment(amount=1000, note="old")
        response = self.client.patch(
            self._detail_url(self.labour.pk, payment.pk),
            {"amount": 1800, "note": "updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 1800)
        self.assertEqual(response.data["note"], "updated")
        payment.refresh_from_db()
        self.assertEqual(payment.amount, 1800)

    def test_delete_payment(self):
        payment = self._create_payment()
        response = self.client.delete(self._detail_url(self.labour.pk, payment.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LabourPayment.objects.filter(pk=payment.pk).exists())

    def test_put_not_allowed(self):
        payment = self._create_payment()
        response = self.client.put(
            self._detail_url(self.labour.pk, payment.pk),
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 1,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class LabourPaymentValidationTests(LabourPaymentAPITestCase):
    def test_future_date_rejected(self):
        future = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            self.list_url,
            {
                "date": str(future),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_FUTURE_DATE,
        )

    def test_date_must_be_after_last_session_date(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.labour.last_session_date = yesterday
        self.labour.save(update_fields=["last_session_date"])

        response = self.client.post(
            self.list_url,
            {
                "date": str(yesterday),
                "type": LabourPaymentType.PAYMENT,
                "amount": 500,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_DATE_NOT_AFTER_LAST_SESSION,
        )

    def test_date_after_last_session_date_is_allowed(self):
        self.labour.last_session_date = timezone.localdate() - timedelta(days=1)
        self.labour.save(update_fields=["last_session_date"])

        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "amount": 500,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_duplicate_date_labour_type_rejected(self):
        today = timezone.localdate()
        self._create_payment(date=today, type=LabourPaymentType.PAYMENT)
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.FOODING,
                "amount": 200,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
        )

    def test_payment_and_return_same_day_allowed(self):
        today = timezone.localdate()
        self._create_payment(date=today, type=LabourPaymentType.PAYMENT)
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "type": LabourPaymentType.RETURN,
                "amount": 100,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_patch_to_duplicate_type_date_rejected(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        self._create_payment(date=today, type=LabourPaymentType.PAYMENT, amount=100)
        other = self._create_payment(
            date=yesterday,
            type=LabourPaymentType.PAYMENT,
            amount=200,
        )
        response = self.client.patch(
            self._detail_url(self.labour.pk, other.pk),
            {"date": str(today)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
        )


class LabourPaymentObjectPermissionTests(LabourPaymentAPITestCase):
    def test_sealed_payment_cannot_be_patched(self):
        payment = self._create_payment(is_sealed=True)
        response = self.client.patch(
            self._detail_url(self.labour.pk, payment.pk),
            {"amount": 999},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_SEALED,
        )

    def test_sealed_payment_cannot_be_deleted(self):
        payment = self._create_payment(is_sealed=True)
        response = self.client.delete(self._detail_url(self.labour.pk, payment.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_SEALED,
        )
        self.assertTrue(LabourPayment.objects.filter(pk=payment.pk).exists())

    def test_cannot_patch_payment_from_unauthorized_site(self):
        other_site = Site.objects.create(
            name="Old Yard",
            company=self.company,
            created_by=self.user,
        )
        # Historical payment recorded at other_site; user is only on current site.
        payment = self._create_payment(site=other_site)
        response = self.client.patch(
            self._detail_url(self.labour.pk, payment.pk),
            {"amount": 50},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )

    def test_can_patch_when_member_of_payment_site(self):
        other_site = Site.objects.create(
            name="Old Yard",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, other_site)
        payment = self._create_payment(site=other_site, amount=100)
        response = self.client.patch(
            self._detail_url(self.labour.pk, payment.pk),
            {"amount": 250},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 250)


class LabourPaymentFilterIsolationTests(LabourPaymentAPITestCase):
    def test_filter_by_type(self):
        today = timezone.localdate()
        self._create_payment(date=today, type=LabourPaymentType.PAYMENT)
        self._create_payment(
            date=today,
            type=LabourPaymentType.RETURN,
            category=None,
            amount=50,
        )
        response = self.client.get(self.list_url, {"type": LabourPaymentType.RETURN})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type"], LabourPaymentType.RETURN)

    def test_filter_by_category(self):
        today = timezone.localdate()
        self._create_payment(
            date=today,
            type=LabourPaymentType.PAYMENT,
            category=LabourPaymentCategory.ADVANCE,
        )
        self._create_payment(
            date=today - timedelta(days=1),
            type=LabourPaymentType.PAYMENT,
            category=LabourPaymentCategory.FOODING,
            amount=80,
        )
        response = self.client.get(
            self.list_url, {"category": LabourPaymentCategory.FOODING}
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["category"], LabourPaymentCategory.FOODING)

    def test_nested_under_other_labour_hides_payments(self):
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
        )
        payment = self._create_payment()
        response = self.client.get(self._list_url(other_labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        response = self.client.get(self._detail_url(other_labour.pk, payment.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_see_other_company_payments(self):
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
        other_labour = Labour.objects.create(
            name="Foreign Labour",
            company=other,
            created_by=other_user,
            current_site=other_site,
            default_salary=500,
        )
        LabourPayment.objects.create(
            company=other,
            labour=other_labour,
            site=other_site,
            date=timezone.localdate(),
            type=LabourPaymentType.PAYMENT,
            category=LabourPaymentCategory.ADVANCE,
            amount=999,
            created_by=other_user,
        )
        self._create_payment(amount=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["amount"], 100)


class LabourPaymentSubscriptionTests(LabourPaymentAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "type": LabourPaymentType.PAYMENT,
                "category": LabourPaymentCategory.ADVANCE,
                "amount": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(LabourPayment.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_payment()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_patch_blocked_when_subscription_expired(self):
        payment = self._create_payment(amount=100)
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(self.labour.pk, payment.pk),
            {"amount": 200},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.amount, 100)


class LabourAttendanceAPITestCase(APITestCase):
    """Shared fixtures for nested labour attendance endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_attendance_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.billing = self._create_billing(name="Basement")
        self.list_url = self._list_url(self.labour.pk)

    def _grant_attendance_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_attendance",
            "add_attendance",
            "change_attendance",
            "delete_attendance",
        ]
        ct = ContentType.objects.get_for_model(Attendance)
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

    def _list_url(self, labour_id):
        return reverse(
            "labour-attendance-list",
            kwargs={"version": "v1", "labour_pk": labour_id},
        )

    def _detail_url(self, labour_id, attendance_id):
        return reverse(
            "labour-attendance-detail",
            kwargs={"version": "v1", "labour_pk": labour_id, "pk": attendance_id},
        )

    def _create_attendance(self, labour=None, site=None, **kwargs):
        labour = labour or self.labour
        site = site or labour.current_site
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": site,
            "date": timezone.localdate(),
            "present": Decimal("1"),
            "salary": 500,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return Attendance.objects.create(**defaults)


class LabourAttendanceAuthPermissionTests(LabourAttendanceAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_attendance_permissions(self.user, ["view_attendance"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        attendance = self._create_attendance()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_attendance_permissions(
            self.user, ["view_attendance", "add_attendance"]
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_site_member_returns_403(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_labour_blocks_create(self):
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_INACTIVE,
        )

    def test_inactive_site_blocks_create(self):
        self.site.is_active = False
        self.site.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_labour_still_allows_list(self):
        self._create_attendance()
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_unassigned_labour_blocks_create_for_companyadmin(self):
        self.user.is_companyadmin = True
        self.user.save(update_fields=["is_companyadmin"])
        self.labour.current_site = None
        self.labour.save(update_fields=["current_site"])
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_UNASSIGNED,
        )

    def test_unassigned_labour_blocks_non_admin(self):
        self.labour.current_site = None
        self.labour.save(update_fields=["current_site"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_UNASSIGNED,
        )


class LabourAttendanceCRUDTests(LabourAttendanceAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_attendance_success(self):
        today = timezone.localdate()
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "present": "1",
                "salary": 500,
                "extra": 100,
                "note": "Full day",
                "billing": self.billing.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["labour"], self.labour.pk)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["created_by"], self.user.pk)
        self.assertEqual(response.data["billing"], self.billing.pk)
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("1"))
        self.assertEqual(response.data["extra"], 100)
        self.assertFalse(response.data["is_sealed"])
        self.assertTrue(
            Attendance.objects.filter(labour=self.labour, date=today).exists()
        )

    def test_create_without_billing_allowed(self):
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "0.5"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["billing"])
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("0.5"))

    def test_create_stamps_site_from_labour_current_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "present": "1",
                "site": other_site.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site"], self.site.pk)

    def test_create_ignores_client_is_sealed_true(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "present": "1",
                "is_sealed": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["is_sealed"])

    def test_list_uses_list_serializer_fields(self):
        attendance = self._create_attendance()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "date",
                "present",
                "salary",
                "extra",
                "note",
                "billing",
                "site",
                "is_sealed",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(response.data[0]["id"], attendance.pk)

    def test_retrieve_attendance_detail(self):
        attendance = self._create_attendance(note="detail")
        response = self.client.get(self._detail_url(self.labour.pk, attendance.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)
        self.assertIn("created_by", response.data)

    def test_patch_present_and_note(self):
        attendance = self._create_attendance(present=Decimal("1"), note="old")
        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"present": "2", "note": "updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("2"))
        self.assertEqual(response.data["note"], "updated")
        attendance.refresh_from_db()
        self.assertEqual(attendance.present, Decimal("2"))

    def test_delete_attendance(self):
        attendance = self._create_attendance()
        response = self.client.delete(self._detail_url(self.labour.pk, attendance.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Attendance.objects.filter(pk=attendance.pk).exists())

    def test_put_not_allowed(self):
        attendance = self._create_attendance()
        response = self.client.put(
            self._detail_url(self.labour.pk, attendance.pk),
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class LabourAttendanceValidationTests(LabourAttendanceAPITestCase):
    def test_future_date_rejected(self):
        future = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            self.list_url,
            {"date": str(future), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_FUTURE_DATE,
        )

    def test_date_must_be_after_last_session_date(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.labour.last_session_date = yesterday
        self.labour.save(update_fields=["last_session_date"])

        response = self.client.post(
            self.list_url,
            {"date": str(yesterday), "present": "1"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_DATE_NOT_AFTER_LAST_SESSION,
        )

    def test_duplicate_date_labour_rejected(self):
        today = timezone.localdate()
        self._create_attendance(date=today)
        response = self.client.post(
            self.list_url,
            {"date": str(today), "present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
        )

    def test_invalid_present_choice_rejected(self):
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1.25"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_active_billing_allowed(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "present": "1",
                "billing": self.billing.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["billing"], self.billing.pk)

    def test_create_with_inactive_billing_rejected(self):
        inactive = self._create_billing(name="Old Floor", is_active=False)
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "present": "1",
                "billing": inactive.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.BILLING_CATEGORY_INACTIVE,
        )
        self.assertFalse(Attendance.objects.exists())

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
                "present": "1",
                "billing": other_billing.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_update_can_set_inactive_billing(self):
        # Active-billing check only applies on create, not update.
        attendance = self._create_attendance()
        inactive = self._create_billing(name="Done Floor", is_active=False)
        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"billing": inactive.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["billing"], inactive.pk)


class LabourAttendanceObjectPermissionTests(LabourAttendanceAPITestCase):
    def test_sealed_attendance_cannot_be_patched(self):
        attendance = self._create_attendance(is_sealed=True)
        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_SEALED,
        )

    def test_sealed_attendance_cannot_be_deleted(self):
        attendance = self._create_attendance(is_sealed=True)
        response = self.client.delete(self._detail_url(self.labour.pk, attendance.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_SEALED,
        )
        self.assertTrue(Attendance.objects.filter(pk=attendance.pk).exists())

    def test_cannot_patch_attendance_from_unauthorized_site(self):
        other_site = Site.objects.create(
            name="Old Yard",
            company=self.company,
            created_by=self.user,
        )
        # Historical attendance at other_site; user is only on current site.
        attendance = self._create_attendance(site=other_site)
        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )

    def test_can_patch_when_member_of_attendance_site(self):
        other_site = Site.objects.create(
            name="Old Yard",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, other_site)
        attendance = self._create_attendance(site=other_site, present=Decimal("1"))
        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("2"))


class LabourAttendanceFilterIsolationTests(LabourAttendanceAPITestCase):
    def test_filter_by_billing(self):
        cat_b = self._create_billing(name="Floor-1")
        self._create_attendance(date=timezone.localdate(), billing=self.billing)
        self._create_attendance(
            date=timezone.localdate() - timedelta(days=1), billing=cat_b
        )
        response = self.client.get(self.list_url, {"billing": cat_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["billing"], cat_b.pk)

    def test_filter_by_date(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        self._create_attendance(date=today)
        self._create_attendance(date=yesterday)
        response = self.client.get(self.list_url, {"date": str(yesterday)})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["date"], str(yesterday))

    def test_nested_under_other_labour_hides_attendances(self):
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
        )
        attendance = self._create_attendance()
        response = self.client.get(self._list_url(other_labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        response = self.client.get(
            self._detail_url(other_labour.pk, attendance.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_see_other_company_attendances(self):
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
        other_labour = Labour.objects.create(
            name="Foreign Labour",
            company=other,
            created_by=other_user,
            current_site=other_site,
            default_salary=500,
        )
        Attendance.objects.create(
            company=other,
            labour=other_labour,
            site=other_site,
            date=timezone.localdate(),
            present=Decimal("1"),
            created_by=other_user,
        )
        self._create_attendance(present=Decimal("1"))

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class LabourAttendanceSubscriptionTests(LabourAttendanceAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(Attendance.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_attendance()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_patch_blocked_when_subscription_expired(self):
        attendance = self._create_attendance(present=Decimal("1"))
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(self.labour.pk, attendance.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        attendance.refresh_from_db()
        self.assertEqual(attendance.present, Decimal("1"))


class SiteLabourPaymentAPITestCase(APITestCase):
    """Shared fixtures for nested site labour-payment endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_payment_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.labour_b = Labour.objects.create(
            name="Rahim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=400,
            default_fooding=80,
        )
        self.list_url = self._list_url(self.site.pk)
        self.today = str(timezone.localdate())

    def _grant_payment_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_labourpayment",
            "add_labourpayment",
            "change_labourpayment",
            "delete_labourpayment",
        ]
        ct = ContentType.objects.get_for_model(LabourPayment)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _assign_site(self, user, site):
        return UserSite.objects.create(
            user=user,
            site=site,
            company=user.company,
            created_by=user,
        )

    def _list_url(self, site_id):
        return reverse(
            "site-labour-payment-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _create_payment(self, labour=None, site=None, **kwargs):
        labour = labour or self.labour
        site = site or self.site
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": site,
            "date": timezone.localdate(),
            "type": LabourPaymentType.PAYMENT,
            "category": LabourPaymentCategory.ADVANCE,
            "amount": 1000,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LabourPayment.objects.create(**defaults)

    def _payment_payload(self, labour, **overrides):
        data = {
            "labour": labour.pk,
            "date": self.today,
            "type": LabourPaymentType.PAYMENT,
            "category": LabourPaymentCategory.ADVANCE,
            "amount": 500,
        }
        data.update(overrides)
        return data


class SiteLabourPaymentAuthPermissionTests(SiteLabourPaymentAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_payment_permissions(self.user, ["view_labourpayment"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            [self._payment_payload(self.labour)],
            format="json",
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
            [self._payment_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_site_still_allows_list(self):
        self._create_payment()
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


class SiteLabourPaymentCRUDTests(SiteLabourPaymentAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_bulk_create_success(self):
        response = self.client.post(
            self.list_url,
            [
                self._payment_payload(self.labour, amount=500),
                self._payment_payload(self.labour_b, amount=700),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(LabourPayment.objects.count(), 2)

        by_labour = {row["labour"]: row for row in response.data}
        self.assertEqual(by_labour[self.labour.pk]["site"], self.site.pk)
        self.assertEqual(by_labour[self.labour.pk]["company"], self.company.pk)
        self.assertEqual(by_labour[self.labour.pk]["created_by"], self.user.pk)
        self.assertFalse(by_labour[self.labour.pk]["is_sealed"])
        self.assertEqual(by_labour[self.labour.pk]["amount"], 500)
        self.assertEqual(by_labour[self.labour_b.pk]["amount"], 700)

    def test_create_stamps_site_from_url(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            [self._payment_payload(self.labour, site=other_site.pk)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data[0]["site"], self.site.pk)

    def test_list_uses_list_serializer_fields(self):
        payment = self._create_payment()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "labour_id",
                "labour_name",
                "date",
                "type",
                "category",
                "amount",
                "note",
                "is_sealed",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(response.data[0]["id"], payment.pk)

    def test_retrieve_not_allowed(self):
        payment = self._create_payment()
        response = self.client.get(f"{self.list_url}/{payment.pk}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_not_allowed(self):
        payment = self._create_payment()
        response = self.client.patch(
            f"{self.list_url}/{payment.pk}",
            {"amount": 2000},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_not_allowed(self):
        payment = self._create_payment()
        response = self.client.delete(f"{self.list_url}/{payment.pk}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(LabourPayment.objects.filter(pk=payment.pk).exists())


class SiteLabourPaymentValidationTests(SiteLabourPaymentAPITestCase):
    def test_non_list_payload_rejected(self):
        response = self.client.post(
            self.list_url,
            self._payment_payload(self.labour),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_future_date_rejected_with_index(self):
        future = str(timezone.localdate() + timedelta(days=1))
        response = self.client.post(
            self.list_url,
            [
                self._payment_payload(self.labour),
                self._payment_payload(self.labour_b, date=future),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "1.date")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_FUTURE_DATE,
        )
        self.assertFalse(LabourPayment.objects.exists())

    def test_last_session_date_error_has_item_index(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.labour_b.last_session_date = yesterday
        self.labour_b.save(update_fields=["last_session_date"])

        response = self.client.post(
            self.list_url,
            [
                self._payment_payload(self.labour),
                self._payment_payload(self.labour_b, date=str(yesterday)),
            ],
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "1.date")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_DATE_NOT_AFTER_LAST_SESSION,
        )
        self.assertFalse(LabourPayment.objects.exists())

    def test_inactive_labour_rejected_with_index(self):
        self.labour_b.is_active = False
        self.labour_b.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            [
                self._payment_payload(self.labour),
                self._payment_payload(self.labour_b),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "1.labour")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_INACTIVE,
        )
        self.assertFalse(LabourPayment.objects.exists())

    def test_labour_from_other_site_rejected(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self.labour_b.current_site = other_site
        self.labour_b.save(update_fields=["current_site"])
        response = self.client.post(
            self.list_url,
            [self._payment_payload(self.labour_b)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.labour")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_labour_from_other_company_rejected(self):
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
        foreign_labour = Labour.objects.create(
            name="Foreign Worker",
            company=other,
            created_by=other_user,
            current_site=other_site,
        )
        response = self.client.post(
            self.list_url,
            [self._payment_payload(foreign_labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.labour")

    def test_duplicate_unique_constraint_rejected(self):
        self._create_payment(labour=self.labour)
        response = self.client.post(
            self.list_url,
            [self._payment_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = {e["code"] for e in response.data["errors"]}
        self.assertTrue(
            codes
            & {
                status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
                "unique",
            },
            response.data,
        )

    def test_one_invalid_item_rolls_back_entire_batch(self):
        future = str(timezone.localdate() + timedelta(days=1))
        response = self.client.post(
            self.list_url,
            [
                self._payment_payload(self.labour, amount=500),
                self._payment_payload(self.labour_b, date=future, amount=700),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(LabourPayment.objects.exists())


class SiteLabourPaymentFilterIsolationTests(SiteLabourPaymentAPITestCase):
    def test_filter_by_type(self):
        self._create_payment(type=LabourPaymentType.PAYMENT)
        self._create_payment(
            labour=self.labour_b,
            type=LabourPaymentType.RETURN,
            category=None,
            amount=50,
        )
        response = self.client.get(
            self.list_url, {"type": LabourPaymentType.RETURN}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type"], LabourPaymentType.RETURN)

    def test_filter_by_labour(self):
        self._create_payment(labour=self.labour)
        self._create_payment(labour=self.labour_b, amount=200)
        response = self.client.get(self.list_url, {"labour": self.labour_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["labour_id"], self.labour_b.pk)

    def test_nested_under_other_site_hides_payments(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, other_site)
        self._create_payment()
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_cannot_see_other_company_payments(self):
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
        other_labour = Labour.objects.create(
            name="Foreign Worker",
            company=other,
            created_by=other_user,
            current_site=other_site,
        )
        LabourPayment.objects.create(
            company=other,
            labour=other_labour,
            site=other_site,
            date=timezone.localdate(),
            type=LabourPaymentType.PAYMENT,
            amount=999,
            created_by=other_user,
        )
        self._create_payment(amount=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["amount"], 100)


class SiteLabourPaymentSubscriptionTests(SiteLabourPaymentAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            [self._payment_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(LabourPayment.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_payment()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class SiteLabourAttendanceAPITestCase(APITestCase):
    """Shared fixtures for nested site labour-attendance endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_attendance_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.labour_b = Labour.objects.create(
            name="Rahim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=400,
            default_fooding=80,
        )
        self.billing = self._create_billing(name="Basement")
        self.list_url = self._list_url(self.site.pk)
        self.today = str(timezone.localdate())

    def _grant_attendance_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_attendance",
            "add_attendance",
            "change_attendance",
            "delete_attendance",
        ]
        ct = ContentType.objects.get_for_model(Attendance)
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
            "site-labour-attendance-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _create_attendance(self, labour=None, site=None, **kwargs):
        labour = labour or self.labour
        site = site or self.site
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": site,
            "date": timezone.localdate(),
            "present": Decimal("1"),
            "salary": labour.default_salary,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return Attendance.objects.create(**defaults)

    def _attendance_payload(self, labour, **overrides):
        data = {
            "labour": labour.pk,
            "date": self.today,
            "present": "1",
            "salary": labour.default_salary,
        }
        data.update(overrides)
        return data


class SiteLabourAttendanceAuthPermissionTests(SiteLabourAttendanceAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_attendance_permissions(self.user, ["view_attendance"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour)],
            format="json",
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
            [self._attendance_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )

    def test_inactive_site_still_allows_list(self):
        self._create_attendance()
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


class SiteLabourAttendanceCRUDTests(SiteLabourAttendanceAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_bulk_create_success(self):
        response = self.client.post(
            self.list_url,
            [
                self._attendance_payload(self.labour, extra=50),
                self._attendance_payload(self.labour_b, present="0.5"),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(Attendance.objects.count(), 2)

        by_labour = {row["labour"]: row for row in response.data}
        self.assertEqual(by_labour[self.labour.pk]["site"], self.site.pk)
        self.assertEqual(by_labour[self.labour.pk]["company"], self.company.pk)
        self.assertEqual(by_labour[self.labour.pk]["created_by"], self.user.pk)
        self.assertFalse(by_labour[self.labour.pk]["is_sealed"])
        self.assertEqual(by_labour[self.labour.pk]["extra"], 50)
        self.assertEqual(Decimal(by_labour[self.labour_b.pk]["present"]), Decimal("0.5"))

    def test_bulk_create_with_billing(self):
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour, billing=self.billing.pk)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data[0]["billing"], self.billing.pk)

    def test_create_stamps_site_from_url(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour, site=other_site.pk)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data[0]["site"], self.site.pk)

    def test_list_uses_list_serializer_fields(self):
        attendance = self._create_attendance()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "labour_id",
                "labour_name",
                "date",
                "present",
                "salary",
                "extra",
                "note",
                "billing",
                "is_sealed",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(response.data[0]["id"], attendance.pk)

    def test_retrieve_not_allowed(self):
        attendance = self._create_attendance()
        response = self.client.get(f"{self.list_url}/{attendance.pk}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_not_allowed(self):
        attendance = self._create_attendance()
        response = self.client.patch(
            f"{self.list_url}/{attendance.pk}",
            {"present": "2"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_not_allowed(self):
        attendance = self._create_attendance()
        response = self.client.delete(f"{self.list_url}/{attendance.pk}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Attendance.objects.filter(pk=attendance.pk).exists())


class SiteLabourAttendanceValidationTests(SiteLabourAttendanceAPITestCase):
    def test_non_list_payload_rejected(self):
        response = self.client.post(
            self.list_url,
            self._attendance_payload(self.labour),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_future_date_rejected_with_index(self):
        future = str(timezone.localdate() + timedelta(days=1))
        response = self.client.post(
            self.list_url,
            [
                self._attendance_payload(self.labour),
                self._attendance_payload(self.labour_b, date=future),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "1.date")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_FUTURE_DATE,
        )
        self.assertFalse(Attendance.objects.exists())

    def test_last_session_date_error_has_item_index(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.labour_b.last_session_date = yesterday
        self.labour_b.save(update_fields=["last_session_date"])

        response = self.client.post(
            self.list_url,
            [
                self._attendance_payload(self.labour),
                self._attendance_payload(self.labour_b, date=str(yesterday)),
            ],
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "1.date")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_DATE_NOT_AFTER_LAST_SESSION,
        )
        self.assertFalse(Attendance.objects.exists())

    def test_invalid_present_choice_rejected(self):
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour, present="1.7")],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.present")

    def test_inactive_labour_rejected_with_index(self):
        self.labour_b.is_active = False
        self.labour_b.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            [
                self._attendance_payload(self.labour),
                self._attendance_payload(self.labour_b),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "1.labour")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_INACTIVE,
        )
        self.assertFalse(Attendance.objects.exists())

    def test_labour_from_other_site_rejected(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self.labour_b.current_site = other_site
        self.labour_b.save(update_fields=["current_site"])
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour_b)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.labour")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_labour_from_other_company_rejected(self):
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
        foreign_labour = Labour.objects.create(
            name="Foreign Worker",
            company=other,
            created_by=other_user,
            current_site=other_site,
        )
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(foreign_labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.labour")

    def test_billing_from_other_site_rejected(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        other_billing = self._create_billing(name="Foreign Cat", site=other_site)
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour, billing=other_billing.pk)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.billing")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )

    def test_inactive_billing_rejected(self):
        inactive_billing = self._create_billing(name="Done Cat", is_active=False)
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour, billing=inactive_billing.pk)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "0.billing")
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.BILLING_CATEGORY_INACTIVE,
        )

    def test_duplicate_unique_constraint_rejected(self):
        self._create_attendance(labour=self.labour)
        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = {e["code"] for e in response.data["errors"]}
        self.assertTrue(
            codes
            & {
                status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
                "unique",
            },
            response.data,
        )

    def test_one_invalid_item_rolls_back_entire_batch(self):
        future = str(timezone.localdate() + timedelta(days=1))
        response = self.client.post(
            self.list_url,
            [
                self._attendance_payload(self.labour),
                self._attendance_payload(self.labour_b, date=future),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Attendance.objects.exists())


class SiteLabourAttendanceFilterIsolationTests(SiteLabourAttendanceAPITestCase):
    def test_filter_by_date(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self._create_attendance()
        self._create_attendance(labour=self.labour_b, date=yesterday)
        response = self.client.get(self.list_url, {"date": str(yesterday)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["labour_id"], self.labour_b.pk)

    def test_filter_by_labour(self):
        self._create_attendance(labour=self.labour)
        self._create_attendance(labour=self.labour_b)
        response = self.client.get(self.list_url, {"labour": self.labour_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["labour_id"], self.labour_b.pk)

    def test_filter_by_billing(self):
        self._create_attendance(labour=self.labour, billing=self.billing)
        self._create_attendance(labour=self.labour_b)
        response = self.client.get(self.list_url, {"billing": self.billing.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["billing"], self.billing.pk)

    def test_nested_under_other_site_hides_attendances(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, other_site)
        self._create_attendance()
        response = self.client.get(self._list_url(other_site.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_cannot_see_other_company_attendances(self):
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
        other_labour = Labour.objects.create(
            name="Foreign Worker",
            company=other,
            created_by=other_user,
            current_site=other_site,
        )
        Attendance.objects.create(
            company=other,
            labour=other_labour,
            site=other_site,
            date=timezone.localdate(),
            present=Decimal("1"),
            created_by=other_user,
        )
        self._create_attendance(extra=100)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["extra"], 100)


class SiteLabourAttendanceSubscriptionTests(SiteLabourAttendanceAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            [self._attendance_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(Attendance.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_attendance()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class LabourSessionAPITestCase(APITestCase):
    """Shared fixtures for ``/labours/<labour_pk>/sessions`` tests."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_session_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.list_url = self._list_url(self.labour.pk)

    def _grant_session_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_laboursession",
            "add_laboursession",
            "delete_laboursession",
        ]
        ct = ContentType.objects.get_for_model(LabourSession)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _assign_site(self, user, site):
        return UserSite.objects.create(
            user=user,
            site=site,
            company=user.company,
            created_by=user,
        )

    def _list_url(self, labour_id):
        return reverse(
            "labour-session-list",
            kwargs={"version": "v1", "labour_pk": labour_id},
        )

    def _detail_url(self, labour_id, session_id):
        return reverse(
            "labour-session-detail",
            kwargs={"version": "v1", "labour_pk": labour_id, "pk": session_id},
        )

    def _running_url(self, labour_id):
        return reverse(
            "labour-session-running-session",
            kwargs={"version": "v1", "labour_pk": labour_id},
        )

    def _create_attendance(self, date, present="1", salary=500, extra=0, **kwargs):
        labour = kwargs.pop("labour", self.labour)
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": labour.current_site,
            "date": date,
            "present": Decimal(present),
            "salary": salary,
            "extra": extra,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return Attendance.objects.create(**defaults)

    def _create_payment(
        self,
        date,
        amount,
        type=LabourPaymentType.PAYMENT,
        category=LabourPaymentCategory.ADVANCE,
        **kwargs,
    ):
        labour = kwargs.pop("labour", self.labour)
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": labour.current_site,
            "date": date,
            "type": type,
            "category": category,
            "amount": amount,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LabourPayment.objects.create(**defaults)

    def _create_session_via_orm(self, labour=None, created_date=None, **kwargs):
        labour = labour or self.labour
        defaults = {
            "company": labour.company,
            "labour": labour,
            "start_date": timezone.localdate() - timedelta(days=3),
            "end_date": timezone.localdate() - timedelta(days=1),
            "created_date": created_date or timezone.localdate(),
            "present_days": Decimal("1"),
            "salary_earnings": 500,
            "extra_earnings": 0,
            "total_payment": 0,
            "total_return": 0,
            "affected_attendance_rows": 1,
            "affected_payment_rows": 0,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LabourSession.objects.create(**defaults)

    def _seed_open_period(self):
        """Two attendances + two payments in the open (unsealed) period."""
        self.day1 = timezone.localdate() - timedelta(days=3)
        self.day2 = timezone.localdate() - timedelta(days=1)
        self._create_attendance(self.day1, present="1", salary=500)
        self._create_attendance(self.day2, present="0.5", salary=500, extra=100)
        self._create_payment(
            self.day2, 1000, type=LabourPaymentType.PAYMENT,
            category=LabourPaymentCategory.ADVANCE,
        )
        self._create_payment(
            self.day1, 200, type=LabourPaymentType.RETURN, category=None,
        )


class LabourSessionAuthPermissionTests(LabourSessionAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_session_permissions(self.user, ["view_laboursession"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_delete_permission_returns_403(self):
        session = self._create_session_via_orm()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_session_permissions(self.user, ["view_laboursession"])
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(self._detail_url(self.labour.pk, session.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_site_member_returns_403(self):
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_labour_returns_403(self):
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
        foreign_labour = Labour.objects.create(
            name="Secret",
            company=other,
            created_by=other_user,
            current_site=other_site,
        )
        response = self.client.get(self._list_url(foreign_labour.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_labour_blocks_create(self):
        self._seed_open_period()
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_INACTIVE,
        )


class LabourSessionCreateTests(LabourSessionAPITestCase):
    def test_create_session_success(self):
        self._seed_open_period()

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.data
        self.assertEqual(data["start_date"], str(self.day1))
        self.assertEqual(data["end_date"], str(self.day2))
        self.assertEqual(data["created_date"], str(timezone.localdate()))
        self.assertEqual(Decimal(data["present_days"]), Decimal("1.5"))
        self.assertEqual(data["salary_earnings"], 750)  # 1*500 + 0.5*500
        self.assertEqual(data["extra_earnings"], 100)
        self.assertEqual(data["total_payment"], 1000)
        self.assertEqual(data["total_return"], 200)
        self.assertEqual(data["total_earnings"], 850)
        self.assertEqual(data["payable"], 850 + 200 - 1000)
        self.assertEqual(data["affected_attendance_rows"], 2)
        self.assertEqual(data["affected_payment_rows"], 2)
        self.assertNotIn("site", data)
        self.assertNotIn("details", data)

        session = LabourSession.objects.get()
        self.assertEqual(session.affected_attendance_rows, 2)
        self.assertEqual(session.affected_payment_rows, 2)

        self.labour.refresh_from_db()
        self.assertEqual(self.labour.last_session_date, timezone.localdate())

    def test_create_aggregates_multi_site_records(self):
        other_site = Site.objects.create(
            name="Metro Rail",
            company=self.company,
            created_by=self.user,
        )
        day1 = timezone.localdate() - timedelta(days=2)
        day2 = timezone.localdate() - timedelta(days=1)
        self._create_attendance(day1, present="1", salary=500, site=other_site)
        self._create_attendance(day2, present="1", salary=500)
        self._create_payment(day2, 300, site=other_site)

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["salary_earnings"], 1000)
        self.assertEqual(response.data["total_payment"], 300)
        self.assertEqual(response.data["affected_attendance_rows"], 2)
        self.assertEqual(response.data["affected_payment_rows"], 1)

    def test_create_seals_records_without_touching_updated_at(self):
        self._seed_open_period()
        attendance = Attendance.objects.get(date=self.day1)
        payment = LabourPayment.objects.get(type=LabourPaymentType.RETURN)
        attendance_updated_at = attendance.updated_at
        payment_updated_at = payment.updated_at

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        attendance.refresh_from_db()
        payment.refresh_from_db()
        self.assertTrue(attendance.is_sealed)
        self.assertTrue(payment.is_sealed)
        self.assertEqual(attendance.updated_at, attendance_updated_at)
        self.assertEqual(payment.updated_at, payment_updated_at)
        self.assertFalse(
            Attendance.objects.filter(labour=self.labour, is_sealed=False).exists()
        )
        self.assertFalse(
            LabourPayment.objects.filter(labour=self.labour, is_sealed=False).exists()
        )

    def test_create_does_not_touch_other_labour_records(self):
        self._seed_open_period()
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
        )
        other_attendance = self._create_attendance(
            self.day1, present="1", labour=other_labour
        )

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        other_attendance.refresh_from_db()
        self.assertFalse(other_attendance.is_sealed)
        other_labour.refresh_from_db()
        self.assertIsNone(other_labour.last_session_date)

    def test_create_only_counts_records_after_last_session_date(self):
        boundary = timezone.localdate() - timedelta(days=2)
        Labour.objects.filter(pk=self.labour.pk).update(last_session_date=boundary)
        old_attendance = self._create_attendance(
            boundary - timedelta(days=1), present="1", salary=500
        )
        self._create_attendance(
            timezone.localdate() - timedelta(days=1), present="1", salary=500
        )

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["start_date"],
            str(timezone.localdate() - timedelta(days=1)),
        )
        self.assertEqual(response.data["salary_earnings"], 500)
        self.assertEqual(Decimal(response.data["present_days"]), Decimal("1"))
        self.assertEqual(response.data["affected_attendance_rows"], 1)
        self.assertEqual(response.data["affected_payment_rows"], 0)

        old_attendance.refresh_from_db()
        self.assertFalse(old_attendance.is_sealed)

    def test_create_without_records_returns_400(self):
        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SESSION_NO_RECORDS,
        )
        self.assertFalse(LabourSession.objects.exists())

    def test_create_after_session_without_new_records_returns_400(self):
        self._seed_open_period()
        self.assertEqual(
            self.client.post(self.list_url).status_code, status.HTTP_201_CREATED
        )

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SESSION_NO_RECORDS,
        )
        self.assertEqual(LabourSession.objects.count(), 1)

    def test_same_date_duplicate_session_returns_400(self):
        self._seed_open_period()
        self.assertEqual(
            self.client.post(self.list_url).status_code, status.HTTP_201_CREATED
        )
        # Force the boundary back so the same records are visible again;
        # the (created_date, labour) constraint must reject a second
        # session on the same day.
        Labour.objects.filter(pk=self.labour.pk).update(last_session_date=None)

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
        )
        self.assertEqual(LabourSession.objects.count(), 1)

class LabourSessionListRetrieveTests(LabourSessionAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_list_uses_list_serializer_fields(self):
        self._create_session_via_orm()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertCountEqual(
            list(response.data[0].keys()),
            [
                "id",
                "labour",
                "start_date",
                "end_date",
                "created_date",
                "present_days",
                "salary_earnings",
                "extra_earnings",
                "total_payment",
                "total_return",
                "affected_attendance_rows",
                "affected_payment_rows",
                "total_earnings",
                "payable",
                "company",
                "created_by",
                "created_at",
                "updated_at",
            ],
        )

    def test_list_orders_latest_first(self):
        older = self._create_session_via_orm(
            created_date=timezone.localdate() - timedelta(days=5)
        )
        latest = self._create_session_via_orm(created_date=timezone.localdate())
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in response.data], [latest.pk, older.pk]
        )

    def test_retrieve_session(self):
        session = self._create_session_via_orm()
        response = self.client.get(self._detail_url(self.labour.pk, session.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], session.pk)
        self.assertNotIn("details", response.data)

    def test_cannot_see_other_labour_sessions(self):
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
        )
        self._create_session_via_orm(labour=other_labour)
        mine = self._create_session_via_orm(
            created_date=timezone.localdate() - timedelta(days=1)
        )
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.data], [mine.pk])


class LabourSessionRunningSessionTests(LabourSessionAPITestCase):
    def test_running_session_empty_when_no_records(self):
        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["start_date"])
        self.assertIsNone(response.data["end_date"])
        self.assertEqual(Decimal(response.data["present_days"]), Decimal("0"))
        self.assertEqual(response.data["payable"], 0)
        self.assertEqual(response.data["last_session_payable"], 0)
        self.assertEqual(response.data["total_payable"], 0)
        self.assertEqual(response.data["labour"], self.labour.pk)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["affected_attendance_rows"], 0)
        self.assertEqual(response.data["affected_payment_rows"], 0)
        self.assertEqual(response.data["company"], self.company.pk)

    def test_running_session_with_open_period(self):
        self._seed_open_period()
        # present=1.5, salary=750, extra=100, payment=1000, return=200
        # payable = 850 + 200 - 1000 = 50
        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["start_date"], str(self.day1))
        self.assertEqual(response.data["end_date"], str(self.day2))
        self.assertEqual(Decimal(response.data["present_days"]), Decimal("1.5"))
        self.assertEqual(response.data["salary_earnings"], 750)
        self.assertEqual(response.data["extra_earnings"], 100)
        self.assertEqual(response.data["total_payment"], 1000)
        self.assertEqual(response.data["total_return"], 200)
        self.assertEqual(response.data["total_earnings"], 850)
        self.assertEqual(response.data["payable"], 50)
        self.assertEqual(response.data["last_session_payable"], 0)
        self.assertEqual(response.data["total_payable"], 50)
        self.assertEqual(response.data["affected_attendance_rows"], 2)
        self.assertEqual(response.data["affected_payment_rows"], 2)

    def test_running_session_includes_last_session_payable(self):
        # Closed session: earnings 500, payment 200 → payable 300
        self._create_session_via_orm(
            created_date=timezone.localdate() - timedelta(days=5),
            salary_earnings=500,
            extra_earnings=0,
            total_payment=200,
            total_return=0,
        )
        self.labour.refresh_from_db()

        day = timezone.localdate() - timedelta(days=1)
        self._create_attendance(day, present="1", salary=500)
        # running payable = 500

        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["payable"], 500)
        self.assertEqual(response.data["last_session_payable"], 300)
        self.assertEqual(response.data["total_payable"], 800)

    def test_running_session_after_close_is_empty_but_keeps_last_payable(self):
        self._seed_open_period()
        create = self.client.post(self.list_url)
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        closed_payable = create.data["payable"]

        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["start_date"])
        self.assertEqual(response.data["payable"], 0)
        self.assertEqual(response.data["last_session_payable"], closed_payable)
        self.assertEqual(response.data["total_payable"], closed_payable)


class LabourSessionDeleteTests(LabourSessionAPITestCase):
    def _create_session_via_api(self):
        self._seed_open_period()
        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return LabourSession.objects.get(pk=response.data["id"])

    def test_delete_latest_session_success(self):
        session = self._create_session_via_api()

        response = self.client.delete(
            self._detail_url(self.labour.pk, session.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LabourSession.objects.exists())

        # Records are unsealed and the boundary reverts.
        self.assertFalse(Attendance.objects.filter(is_sealed=True).exists())
        self.assertFalse(LabourPayment.objects.filter(is_sealed=True).exists())
        self.labour.refresh_from_db()
        self.assertIsNone(self.labour.last_session_date)

    def test_delete_non_latest_session_returns_400(self):
        older = self._create_session_via_orm(
            created_date=timezone.localdate() - timedelta(days=5)
        )
        self._create_session_via_orm(created_date=timezone.localdate())

        response = self.client.delete(self._detail_url(self.labour.pk, older.pk))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SESSION_NOT_LATEST,
        )
        self.assertEqual(LabourSession.objects.count(), 2)

    def test_delete_blocked_when_record_amount_changed(self):
        session = self._create_session_via_api()
        LabourPayment.objects.filter(type=LabourPaymentType.PAYMENT).update(
            amount=9999
        )

        response = self.client.delete(
            self._detail_url(self.labour.pk, session.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SESSION_SNAPSHOT_MISMATCH,
        )
        self.assertTrue(LabourSession.objects.filter(pk=session.pk).exists())

    def test_delete_blocked_when_record_removed(self):
        session = self._create_session_via_api()
        Attendance.objects.filter(date=self.day2).delete()

        response = self.client.delete(
            self._detail_url(self.labour.pk, session.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SESSION_SNAPSHOT_MISMATCH,
        )

    def test_recreate_after_delete_produces_same_totals(self):
        session = self._create_session_via_api()
        original_salary_earnings = session.salary_earnings
        original_attendance_count = session.affected_attendance_rows
        original_payment_count = session.affected_payment_rows
        self.assertEqual(
            self.client.delete(
                self._detail_url(self.labour.pk, session.pk)
            ).status_code,
            status.HTTP_204_NO_CONTENT,
        )

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["salary_earnings"], original_salary_earnings
        )
        self.assertEqual(
            response.data["affected_attendance_rows"], original_attendance_count
        )
        self.assertEqual(
            response.data["affected_payment_rows"], original_payment_count
        )


class LabourSessionSubscriptionTests(LabourSessionAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self._seed_open_period()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(LabourSession.objects.exists())

    def test_delete_blocked_when_subscription_expired(self):
        session = self._create_session_via_orm()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.delete(
            self._detail_url(self.labour.pk, session.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )

    def test_list_allowed_when_subscription_expired(self):
        self._create_session_via_orm()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
