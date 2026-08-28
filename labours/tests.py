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
from activity.models import ActivityAction, ActivityEntityType, ActivityLog
from company.models import Company
from core import status_codes
from labours.models import DailyRecord, Labour, LabourSession
from sites.models import BillingCategory, Site
from subscription.models import Subscription

User = get_user_model()


def _list_results(response):
    """Return list rows from a paginated or unpaginated list response."""
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def _by_labour_id(response):
    return {row["labour"]["id"]: row for row in _list_results(response)}


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
        self.assertEqual(_list_results(response), [])

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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertCountEqual(
            _list_results(response)[0].keys(),
            [
                "id",
                "name",
                "photo",
                "current_site",
                "default_attendance",
                "default_salary",
                "default_fooding",
                "last_session_date",
                "is_active",
            ],
        )
        self.assertEqual(_list_results(response)[0]["id"], labour.pk)

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

    def test_patch_photo(self):
        import tempfile
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image

        labour = self._create_labour(name="Photo Labour")
        buf = BytesIO()
        Image.new("RGB", (1, 1), "blue").save(buf, format="PNG")
        upload = SimpleUploadedFile(
            "labour.png",
            buf.getvalue(),
            content_type="image/png",
        )
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                response = self.client.patch(
                    self._detail_url(labour.pk),
                    {"photo": upload},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIsNotNone(response.data["photo"])
                self.assertIn("/media/labours/", response.data["photo"])
                labour.refresh_from_db()
                self.assertTrue(
                    labour.photo.name.startswith(f"labours/{labour.company_id}/")
                )
                self.assertTrue(labour.photo.name.endswith(".jpg"))

    def test_patch_photo_rejects_over_5mb(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core import status_codes

        labour = self._create_labour(name="Huge Photo Labour")
        upload = SimpleUploadedFile(
            "huge.jpg",
            b"x" * (5 * 1024 * 1024 + 1),
            content_type="image/jpeg",
        )
        response = self.client.patch(
            self._detail_url(labour.pk),
            {"photo": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.PHOTO_TOO_LARGE,
        )

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
        )
        Labour.objects.create(
            name="Shared",
            company=other,
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
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Active")

        response = self.client.get(self.list_url, {"is_active": "false"})
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Inactive")

    def test_filter_by_current_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self._create_labour(name="On Padma", current_site=self.site)
        self._create_labour(name="On Other", current_site=other_site)

        response = self.client.get(self.list_url, {"current_site": self.site.pk})
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "On Padma")

    def test_filter_by_current_site_null(self):
        self._create_labour(name="Unassigned", current_site=None)
        self._create_labour(name="On Padma", current_site=self.site)

        response = self.client.get(self.list_url, {"current_site": "null"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Unassigned")
        self.assertIsNone(results[0]["current_site"])

    def test_search_by_name(self):
        self._create_labour(name="Karim Mia")
        self._create_labour(name="Rahim Uddin")

        response = self.client.get(self.list_url, {"search": "Karim"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Karim Mia")

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
            current_site=Site.objects.create(
                name="Other Site",
                company=other,
            ),
            default_salary=500,
        )
        self._create_labour(name="Mine")

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Mine")

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
            current_site=Site.objects.create(
                name="Other Site",
                company=other,
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
        )
        a = self._create_labour(name="On Padma", current_site=self.site)
        b = self._create_labour(name="On Other", current_site=other_site)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            [row["id"] for row in _list_results(response)],
            [a.pk, b.pk],
        )

    def test_non_admin_sees_only_assigned_site_labours(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        assigned_labour = self._create_labour(name="Mine", current_site=self.site)
        self._create_labour(name="Theirs", current_site=other_site)

        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], assigned_labour.pk)

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
            [row["id"] for row in _list_results(response)],
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
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], assigned.pk)


class LabourCurrentSiteAssignmentTests(LabourAPITestCase):
    def _as_site_member(self, site=None):
        site = site or self.site
        self.user.is_companyadmin = False
        self.user.save(update_fields=["is_companyadmin"])
        UserSite.objects.create(
            user=self.user,
            site=site,
            company=self.company,
        )
        self.client.force_authenticate(user=self.user)

    def test_non_admin_can_assign_own_site(self):
        self._as_site_member()
        response = self.client.post(
            self.list_url,
            {
                "name": "Mine",
                "current_site": self.site.pk,
                "default_salary": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["current_site"], self.site.pk)

    def test_non_admin_cannot_assign_other_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self._as_site_member(self.site)
        response = self.client.post(
            self.list_url,
            {
                "name": "Steal",
                "current_site": other_site.pk,
                "default_salary": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )

    def test_non_admin_cannot_clear_current_site(self):
        labour = self._create_labour(name="Movable")
        self._as_site_member()
        response = self.client.patch(
            self._detail_url(labour.pk),
            {"current_site": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_UNASSIGNED,
        )

    def test_non_admin_cannot_create_unassigned(self):
        self._as_site_member()
        response = self.client.post(
            self.list_url,
            {"name": "Pool", "default_salary": 500},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_UNASSIGNED,
        )

    def test_companyadmin_can_assign_any_company_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        response = self.client.post(
            self.list_url,
            {
                "name": "Anywhere",
                "current_site": other_site.pk,
                "default_salary": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["current_site"], other_site.pk)


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
        self.assertEqual(len(_list_results(response)), 1)

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
    def _create_session(self, labour, session_date):
        return LabourSession.objects.create(
            company=self.company,
            labour=labour,
            start_date=session_date,
            end_date=session_date,
            present_days=Decimal("1"),
            salary_earnings=500,
            extra_earnings=0,
            total_fooding_pay=0,
            total_advance_pay=0,
            total_return=0,
            affected_rows=1,
            previous_payable=0,
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


class DailyRecordAPITestCase(APITestCase):
    """Shared fixtures for ``/labours/<labour_pk>/daily-records``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_daily_record_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.billing = self._create_billing(name="Basement")
        self.list_url = self._list_url(self.labour.pk)

    def _grant_daily_record_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_dailyrecord",
            "add_dailyrecord",
            "change_dailyrecord",
            "delete_dailyrecord",
        ]
        ct = ContentType.objects.get_for_model(DailyRecord)
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

    def _list_url(self, labour_id):
        return reverse(
            "labour-daily-record-list",
            kwargs={"version": "v1", "labour_pk": labour_id},
        )

    def _detail_url(self, labour_id, record_id):
        return reverse(
            "labour-daily-record-detail",
            kwargs={"version": "v1", "labour_pk": labour_id, "pk": record_id},
        )

    def _create_daily_record(self, labour=None, site=None, **kwargs):
        labour = labour or self.labour
        site = site or labour.current_site
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": site,
            "date": timezone.localdate(),
            "present": Decimal("1"),
            "wage": labour.default_salary,
        }
        defaults.update(kwargs)
        return DailyRecord.objects.create(**defaults)


class DailyRecordAuthPermissionTests(DailyRecordAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_daily_record_permissions(self.user, ["view_dailyrecord"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        record = self._create_daily_record()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_daily_record_permissions(
            self.user, ["view_dailyrecord", "add_dailyrecord"]
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_delete_permission_returns_403(self):
        record = self._create_daily_record()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_daily_record_permissions(
            self.user, ["view_dailyrecord", "add_dailyrecord", "change_dailyrecord"]
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(self._detail_url(self.labour.pk, record.pk))
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
        self._create_daily_record()
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)

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


class DailyRecordCRUDTests(DailyRecordAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])

    def test_create_daily_record_success(self):
        today = timezone.localdate()
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "present": "1",
                "wage": 500,
                "extra_earn": 100,
                "fooding_pay": 50,
                "note": "Full day",
                "billing": self.billing.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["labour"], self.labour.pk)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertEqual(response.data["billing"], self.billing.pk)
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("1"))
        self.assertEqual(response.data["extra_earn"], 100)
        self.assertEqual(response.data["fooding_pay"], 50)
        self.assertFalse(response.data["is_sealed"])
        self.assertTrue(
            DailyRecord.objects.filter(labour=self.labour, date=today).exists()
        )

    def test_create_wage_defaults_from_labour_salary(self):
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate()), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["wage"], self.labour.default_salary)

    def test_create_stamps_site_from_labour_current_site(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
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
        record = self._create_daily_record(billing=self.billing)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertCountEqual(
            results[0].keys(),
            [
                "id",
                "date",
                "present",
                "wage",
                "extra_earn",
                "fooding_pay",
                "advance_pay",
                "return_amount",
                "note",
                "billing",
                "site",
                "is_sealed",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(results[0]["id"], record.pk)
        self.assertEqual(results[0]["site"], self.site.pk)
        self.assertEqual(results[0]["billing"], self.billing.pk)

    def test_retrieve_daily_record_detail(self):
        record = self._create_daily_record(note="detail")
        response = self.client.get(self._detail_url(self.labour.pk, record.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "detail")
        self.assertIn("company", response.data)

    def test_patch_fields(self):
        record = self._create_daily_record(present=Decimal("1"), note="old")
        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "2", "note": "updated", "advance_pay": 200},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("2"))
        self.assertEqual(response.data["note"], "updated")
        self.assertEqual(response.data["advance_pay"], 200)
        record.refresh_from_db()
        self.assertEqual(record.present, Decimal("2"))

    def test_delete_daily_record(self):
        record = self._create_daily_record()
        response = self.client.delete(self._detail_url(self.labour.pk, record.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DailyRecord.objects.filter(pk=record.pk).exists())


class DailyRecordActivityLogTests(DailyRecordAPITestCase):
    def test_create_writes_activity_log(self):
        today = timezone.localdate()
        response = self.client.post(
            self.list_url,
            {
                "date": str(today),
                "present": "1",
                "wage": 500,
                "fooding_pay": 50,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        record_id = response.data["id"]
        log = ActivityLog.objects.get(
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=record_id,
            action=ActivityAction.CREATED,
        )
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.labour_id, self.labour.pk)
        self.assertEqual(log.labour_name, self.labour.name)
        self.assertEqual(log.business_date, today)
        self.assertEqual(log.changes["present"], "1")
        self.assertEqual(log.changes["wage"], 500)
        self.assertEqual(log.changes["fooding_pay"], 50)

    def test_patch_writes_activity_log_diff(self):
        record = self._create_daily_record(present=Decimal("1"), note="old")
        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "2", "note": "updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.get(
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=record.pk,
            action=ActivityAction.UPDATED,
        )
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.labour_id, self.labour.pk)
        self.assertEqual(log.changes["present"]["old"], "1.00")
        self.assertEqual(log.changes["present"]["new"], "2")
        self.assertEqual(log.changes["note"]["old"], "old")
        self.assertEqual(log.changes["note"]["new"], "updated")

    def test_delete_writes_activity_log(self):
        record = self._create_daily_record(
            present=Decimal("1"),
            wage=500,
            note="to delete",
        )
        record_id = record.pk
        response = self.client.delete(self._detail_url(self.labour.pk, record_id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = ActivityLog.objects.get(
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=record_id,
            action=ActivityAction.DELETED,
        )
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.labour_id, self.labour.pk)
        self.assertEqual(log.labour_name, self.labour.name)
        self.assertEqual(log.changes["present"], "1.00")
        self.assertEqual(log.changes["wage"], 500)
        self.assertEqual(log.changes["note"], "to delete")


class DailyRecordValidationTests(DailyRecordAPITestCase):
    def test_all_zero_values_rejected(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "present": "0",
                "extra_earn": 0,
                "fooding_pay": 0,
                "advance_pay": 0,
                "return_amount": 0,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.DAILY_RECORD_VALUE_REQUIRED,
        )

    def test_empty_payload_rejected(self):
        response = self.client.post(
            self.list_url,
            {"date": str(timezone.localdate())},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.DAILY_RECORD_VALUE_REQUIRED,
        )

    def test_payment_only_fooding_ok(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "fooding_pay": 100,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["fooding_pay"], 100)
        self.assertIsNone(response.data["present"])

    def test_payment_only_advance_ok(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "advance_pay": 500,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["advance_pay"], 500)

    def test_present_and_extra_earn_only_ok(self):
        response = self.client.post(
            self.list_url,
            {
                "date": str(timezone.localdate()),
                "present": "1",
                "extra_earn": 150,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["extra_earn"], 150)
        self.assertIsNone(response.data["fooding_pay"])

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

    def test_date_on_or_before_last_session_rejected(self):
        boundary = timezone.localdate() - timedelta(days=1)
        Labour.objects.filter(pk=self.labour.pk).update(last_session_date=boundary)
        response = self.client.post(
            self.list_url,
            {"date": str(boundary), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_DATE_NOT_AFTER_LAST_SESSION,
        )

    def test_duplicate_date_rejected(self):
        today = timezone.localdate()
        self._create_daily_record(date=today)
        response = self.client.post(
            self.list_url,
            {"date": str(today), "present": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            "unique",
        )


class DailyRecordObjectPermissionTests(DailyRecordAPITestCase):
    def test_sealed_record_cannot_be_patched(self):
        record = self._create_daily_record(is_sealed=True)
        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_SEALED,
        )

    def test_sealed_record_cannot_be_deleted(self):
        record = self._create_daily_record(is_sealed=True)
        response = self.client.delete(self._detail_url(self.labour.pk, record.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.RECORD_SEALED,
        )
        self.assertTrue(DailyRecord.objects.filter(pk=record.pk).exists())

    def test_cannot_patch_record_from_unauthorized_site(self):
        other_site = Site.objects.create(
            name="Old Yard",
            company=self.company,
        )
        record = self._create_daily_record(site=other_site)
        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "0.5"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.UNAUTHORIZED_SITE,
        )

    def test_can_patch_when_member_of_record_site(self):
        other_site = Site.objects.create(
            name="Old Yard",
            company=self.company,
        )
        self._assign_site(self.user, other_site)
        record = self._create_daily_record(site=other_site, present=Decimal("1"))
        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "0.5"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(response.data["present"])), Decimal("0.5"))


class DailyRecordFilterIsolationTests(DailyRecordAPITestCase):
    def test_filter_by_date(self):
        today = timezone.localdate()
        earlier = today - timedelta(days=2)
        self._create_daily_record(date=today)
        self._create_daily_record(date=earlier, present=Decimal("0.5"))

        response = self.client.get(self.list_url, {"date": str(today)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["date"], str(today))

    def test_filter_by_is_sealed(self):
        self._create_daily_record(is_sealed=False)
        sealed = self._create_daily_record(
            date=timezone.localdate() - timedelta(days=1),
            is_sealed=True,
        )
        response = self.client.get(self.list_url, {"is_sealed": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], sealed.pk)

    def test_nested_under_other_labour_hides_records(self):
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            current_site=self.site,
            default_salary=500,
        )
        self._create_daily_record()
        response = self.client.get(self._list_url(other_labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_list_results(response), [])


class DailyRecordSubscriptionTests(DailyRecordAPITestCase):
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
        self.assertFalse(DailyRecord.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_daily_record()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)

    def test_patch_blocked_when_subscription_expired(self):
        record = self._create_daily_record(present=Decimal("1"))
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.patch(
            self._detail_url(self.labour.pk, record.pk),
            {"present": "2"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        record.refresh_from_db()
        self.assertEqual(record.present, Decimal("1"))


class SiteDailyRecordAPITestCase(APITestCase):
    """Shared fixtures for ``/sites/<site_pk>/daily-records``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_daily_record_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            current_site=self.site,
            default_salary=500,
            default_fooding=100,
        )
        self.labour_b = Labour.objects.create(
            name="Rahim",
            company=self.company,
            current_site=self.site,
            default_salary=400,
            default_fooding=80,
        )
        self.billing = self._create_billing(name="Basement")
        self.list_url = self._list_url(self.site.pk)
        self.today = str(timezone.localdate())

    def _grant_daily_record_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_dailyrecord",
            "add_dailyrecord",
            "change_dailyrecord",
            "delete_dailyrecord",
        ]
        ct = ContentType.objects.get_for_model(DailyRecord)
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
            "site-daily-record-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _create_daily_record(self, labour=None, site=None, **kwargs):
        labour = labour or self.labour
        site = site or self.site
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": site,
            "date": timezone.localdate(),
            "present": Decimal("1"),
            "wage": labour.default_salary,
        }
        defaults.update(kwargs)
        return DailyRecord.objects.create(**defaults)

    def _record_payload(self, labour, **overrides):
        data = {
            "labour": labour.pk,
            "date": self.today,
            "present": "1",
        }
        data.update(overrides)
        return data


class SiteDailyRecordAuthPermissionTests(SiteDailyRecordAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_daily_record_permissions(self.user, ["view_dailyrecord"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            [self._record_payload(self.labour)],
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
            [self._record_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SITE_INACTIVE,
        )


class SiteDailyRecordCRUDTests(SiteDailyRecordAPITestCase):
    def test_list_empty_returns_site_labours_with_empty_records(self):
        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        self.assertEqual(len(by_id), 2)
        self.assertEqual(by_id[self.labour.pk]["records"], [])
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])

    def test_bulk_create_success(self):
        response = self.client.post(
            self.list_url,
            [
                self._record_payload(
                    self.labour,
                    present="1",
                    extra_earn=50,
                    billing=self.billing.pk,
                ),
                self._record_payload(
                    self.labour_b,
                    present="0.5",
                    fooding_pay=80,
                ),
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data), 2)
        by_labour = {row["labour"]: row for row in response.data}
        self.assertEqual(by_labour[self.labour.pk]["extra_earn"], 50)
        self.assertEqual(by_labour[self.labour.pk]["site"], self.site.pk)
        self.assertFalse(by_labour[self.labour.pk]["is_sealed"])
        self.assertEqual(by_labour[self.labour_b.pk]["fooding_pay"], 80)
        self.assertEqual(
            by_labour[self.labour.pk]["wage"], self.labour.default_salary
        )
        self.assertEqual(DailyRecord.objects.count(), 2)

    def test_list_uses_list_serializer_fields(self):
        record = self._create_daily_record(billing=self.billing)
        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        row = by_id[self.labour.pk]
        self.assertCountEqual(row.keys(), ["labour", "records", "totals"])
        self.assertCountEqual(
            row["labour"].keys(),
            [
                "id",
                "name",
                "photo",
                "current_site",
                "default_attendance",
                "default_salary",
                "default_fooding",
                "last_session_date",
                "is_active",
            ],
        )
        self.assertEqual(len(row["records"]), 1)
        self.assertCountEqual(
            row["records"][0].keys(),
            [
                "id",
                "date",
                "present",
                "wage",
                "extra_earn",
                "fooding_pay",
                "advance_pay",
                "return_amount",
                "note",
                "billing",
                "is_sealed",
                "created_at",
                "updated_at",
                "pending_activities",
            ],
        )
        self.assertEqual(row["records"][0]["id"], record.pk)
        self.assertEqual(row["records"][0]["billing"], self.billing.pk)
        self.assertEqual(row["labour"]["current_site"], self.site.pk)
        self.assertEqual(row["records"][0]["pending_activities"], [])
        self.assertEqual(
            row["totals"],
            {
                "present": "1.00",
                "extra_earn": 0,
                "fooding_pay": 0,
                "advance_pay": 0,
                "return_amount": 0,
            },
        )
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])
        self.assertEqual(by_id[self.labour_b.pk]["totals"]["present"], "0.00")


class SiteDailyRecordPendingActivitiesTests(SiteDailyRecordAPITestCase):
    def _log(self, record, *, action, reviewed=False, **kwargs):
        defaults = {
            "company": record.company,
            "site": record.site,
            "labour": record.labour,
            "labour_name": record.labour.name,
            "actor": self.user,
            "actor_name": self.user.name,
            "action": action,
            "entity_type": ActivityEntityType.DAILY_RECORD,
            "entity_id": record.pk,
            "business_date": record.date,
            "changes": {"present": str(record.present)},
        }
        if reviewed:
            defaults["reviewed_at"] = timezone.now()
            defaults["reviewed_by"] = self.user
        defaults.update(kwargs)
        return ActivityLog.objects.create(**defaults)

    def test_empty_pending_when_no_logs(self):
        self._create_daily_record()
        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            _by_labour_id(response)[self.labour.pk]["records"][0]["pending_activities"],
            [],
        )

    def test_unreviewed_created_and_updated_newest_first(self):
        record = self._create_daily_record()
        created = self._log(record, action=ActivityAction.CREATED)
        updated = self._log(record, action=ActivityAction.UPDATED)
        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pending = _by_labour_id(response)[self.labour.pk]["records"][0]["pending_activities"]
        self.assertEqual(
            pending,
            [
                {"id": updated.pk, "action": ActivityAction.UPDATED},
                {"id": created.pk, "action": ActivityAction.CREATED},
            ],
        )
        self.assertEqual(set(pending[0].keys()), {"id", "action"})

    def test_reviewed_logs_are_excluded(self):
        record = self._create_daily_record()
        self._log(record, action=ActivityAction.CREATED, reviewed=True)
        pending_log = self._log(record, action=ActivityAction.UPDATED)
        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(
            _by_labour_id(response)[self.labour.pk]["records"][0]["pending_activities"],
            [{"id": pending_log.pk, "action": ActivityAction.UPDATED}],
        )

    def test_logs_for_other_record_row_are_not_attached(self):
        record_a = self._create_daily_record(labour=self.labour)
        record_b = self._create_daily_record(labour=self.labour_b)
        self._log(record_b, action=ActivityAction.CREATED)
        response = self.client.get(self.list_url, {"date": self.today})
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[record_a.labour_id]["records"][0]["pending_activities"], [])
        self.assertEqual(len(by_id[record_b.labour_id]["records"][0]["pending_activities"]), 1)

    def test_all_records_returned_without_pagination(self):
        first = self._create_daily_record(labour=self.labour)
        second = self._create_daily_record(labour=self.labour_b)
        response = self.client.get(
            self.list_url, {"date": self.today, "page": 1, "page_size": 1}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[first.labour_id]["records"][0]["id"], first.pk)
        self.assertEqual(by_id[second.labour_id]["records"][0]["id"], second.pk)

    def test_view_dailyrecord_alone_includes_pending_activities(self):
        record = self._create_daily_record()
        log = self._log(record, action=ActivityAction.CREATED)
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_daily_record_permissions(self.user, ["view_dailyrecord"])
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            _by_labour_id(response)[self.labour.pk]["records"][0]["pending_activities"],
            [{"id": log.pk, "action": ActivityAction.CREATED}],
        )


class SiteDailyRecordRosterTests(SiteDailyRecordAPITestCase):
    def test_invalid_date_returns_400(self):
        response = self.client.get(self.list_url, {"date": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date")

    def test_date_query_param_defaults_to_today(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self._create_daily_record(labour=self.labour, date=yesterday)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[self.labour.pk]["records"], [])

    def test_record_attached_and_empty_row_kept(self):
        record = self._create_daily_record(
            labour=self.labour,
            present=Decimal("2"),
            extra_earn=50,
            billing=self.billing,
        )
        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        attached = by_id[self.labour.pk]["records"]
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0]["id"], record.pk)
        self.assertEqual(attached[0]["present"], Decimal("2.00"))
        self.assertEqual(attached[0]["extra_earn"], 50)
        self.assertEqual(attached[0]["billing"], self.billing.pk)
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])
        self.assertEqual(by_id[self.labour.pk]["totals"]["extra_earn"], 50)
        self.assertEqual(by_id[self.labour.pk]["totals"]["present"], "2.00")

    def test_inactive_site_labour_without_record_excluded(self):
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.get(self.list_url, {"date": self.today})
        labour_ids = [row["labour"]["id"] for row in _list_results(response)]
        self.assertNotIn(self.labour.pk, labour_ids)
        self.assertIn(self.labour_b.pk, labour_ids)

    def test_inactive_site_labour_with_record_included(self):
        record = self._create_daily_record(labour=self.labour)
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.get(self.list_url, {"date": self.today})
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[self.labour.pk]["records"][0]["id"], record.pk)
        self.assertFalse(by_id[self.labour.pk]["labour"]["is_active"])

    def test_transferred_labour_with_record_included(self):
        record = self._create_daily_record(labour=self.labour)
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self.labour.current_site = other_site
        self.labour.save(update_fields=["current_site"])

        response = self.client.get(self.list_url, {"date": self.today})
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[self.labour.pk]["records"][0]["id"], record.pk)
        self.assertEqual(by_id[self.labour.pk]["labour"]["name"], "Karim")
        self.assertEqual(by_id[self.labour.pk]["labour"]["current_site"], other_site.pk)
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])

    def test_transferred_labour_without_record_excluded(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self.labour.current_site = other_site
        self.labour.save(update_fields=["current_site"])
        response = self.client.get(self.list_url, {"date": self.today})
        labour_ids = [row["labour"]["id"] for row in _list_results(response)]
        self.assertNotIn(self.labour.pk, labour_ids)
        self.assertEqual(labour_ids, [self.labour_b.pk])

    def test_other_date_records_not_attached(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self._create_daily_record(labour=self.labour, date=yesterday)
        response = self.client.get(self.list_url, {"date": self.today})
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[self.labour.pk]["records"], [])

    def test_rows_ordered_by_labour_name(self):
        response = self.client.get(self.list_url, {"date": self.today})
        names = [row["labour"]["name"] for row in _list_results(response)]
        self.assertEqual(names, ["Karim", "Rahim"])

    def test_date_range_collects_records_per_labour(self):
        today = timezone.localdate()
        older = self._create_daily_record(
            labour=self.labour, date=today - timedelta(days=3)
        )
        in_range = self._create_daily_record(
            labour=self.labour, date=today - timedelta(days=1)
        )
        self._create_daily_record(labour=self.labour_b, date=today)
        response = self.client.get(
            self.list_url,
            {
                "date__gte": str(today - timedelta(days=2)),
                "date__lte": str(today - timedelta(days=1)),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        self.assertEqual(
            [row["id"] for row in by_id[self.labour.pk]["records"]],
            [in_range.pk],
        )
        self.assertNotIn(older.pk, [row["id"] for row in by_id[self.labour.pk]["records"]])
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])

    def test_date_range_multiple_days_ordered_by_date(self):
        today = timezone.localdate()
        first = self._create_daily_record(
            labour=self.labour, date=today - timedelta(days=2)
        )
        second = self._create_daily_record(
            labour=self.labour, date=today - timedelta(days=1)
        )
        response = self.client.get(
            self.list_url,
            {
                "date__gte": str(today - timedelta(days=2)),
                "date__lte": str(today),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [
            row["id"]
            for row in _by_labour_id(response)[self.labour.pk]["records"]
        ]
        self.assertEqual(ids, [first.pk, second.pk])

    def test_date_gte_only(self):
        today = timezone.localdate()
        self._create_daily_record(
            labour=self.labour, date=today - timedelta(days=2)
        )
        newer = self._create_daily_record(labour=self.labour_b, date=today)
        response = self.client.get(
            self.list_url,
            {"date__gte": str(today - timedelta(days=1))},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[self.labour.pk]["records"], [])
        self.assertEqual(
            [row["id"] for row in by_id[self.labour_b.pk]["records"]],
            [newer.pk],
        )

    def test_cannot_combine_date_with_range(self):
        response = self.client.get(
            self.list_url,
            {"date": self.today, "date__gte": self.today},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date")

    def test_date_gte_after_date_lte_rejected(self):
        today = timezone.localdate()
        response = self.client.get(
            self.list_url,
            {
                "date__gte": str(today),
                "date__lte": str(today - timedelta(days=1)),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date__gte")

    def test_invalid_date_gte_returns_400(self):
        response = self.client.get(self.list_url, {"date__gte": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["attr"], "date__gte")

    def test_range_over_one_month_returns_totals_without_records(self):
        today = timezone.localdate()
        start = today - timedelta(days=31)
        self._create_daily_record(
            labour=self.labour,
            date=start,
            present=Decimal("2"),
            extra_earn=40,
            fooding_pay=10,
            advance_pay=5,
            return_amount=3,
        )
        response = self.client.get(
            self.list_url,
            {"date__gte": str(start), "date__lte": str(today)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        by_id = _by_labour_id(response)
        self.assertEqual(by_id[self.labour.pk]["records"], [])
        self.assertEqual(
            by_id[self.labour.pk]["totals"],
            {
                "present": "2.00",
                "extra_earn": 40,
                "fooding_pay": 10,
                "advance_pay": 5,
                "return_amount": 3,
            },
        )
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])
        self.assertEqual(by_id[self.labour_b.pk]["totals"]["extra_earn"], 0)

    def test_range_of_one_month_still_returns_records(self):
        today = timezone.localdate()
        start = today - timedelta(days=30)
        record = self._create_daily_record(labour=self.labour, date=start)
        response = self.client.get(
            self.list_url,
            {"date__gte": str(start), "date__lte": str(today)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        self.assertEqual(
            [row["id"] for row in by_id[self.labour.pk]["records"]],
            [record.pk],
        )


class SiteDailyRecordValidationTests(SiteDailyRecordAPITestCase):
    def test_inactive_labour_rejected(self):
        self.labour.is_active = False
        self.labour.save(update_fields=["is_active"])
        response = self.client.post(
            self.list_url,
            [self._record_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.LABOUR_INACTIVE,
        )

    def test_labour_on_other_site_rejected(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        self.labour.current_site = other_site
        self.labour.save(update_fields=["current_site"])
        response = self.client.post(
            self.list_url,
            [self._record_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_values_rejected(self):
        response = self.client.post(
            self.list_url,
            [
                {
                    "labour": self.labour.pk,
                    "date": self.today,
                    "present": "0",
                    "extra_earn": 0,
                    "fooding_pay": 0,
                    "advance_pay": 0,
                    "return_amount": 0,
                }
            ],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.DAILY_RECORD_VALUE_REQUIRED,
        )

    def test_duplicate_date_labour_rejected(self):
        self._create_daily_record(date=timezone.localdate())
        response = self.client.post(
            self.list_url,
            [self._record_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            "unique",
        )


class SiteDailyRecordFilterIsolationTests(SiteDailyRecordAPITestCase):
    def test_other_site_records_and_labours_hidden(self):
        other_site = Site.objects.create(
            name="Other Yard",
            company=self.company,
        )
        other_labour = Labour.objects.create(
            name="Other",
            company=self.company,
            current_site=other_site,
            default_salary=500,
        )
        self._create_daily_record()
        self._create_daily_record(labour=other_labour, site=other_site)

        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        labour_ids = [row["labour"]["id"] for row in _list_results(response)]
        self.assertCountEqual(labour_ids, [self.labour.pk, self.labour_b.pk])
        by_id = _by_labour_id(response)
        self.assertTrue(by_id[self.labour.pk]["records"])
        self.assertEqual(by_id[self.labour_b.pk]["records"], [])


class SiteDailyRecordSubscriptionTests(SiteDailyRecordAPITestCase):
    def test_create_blocked_when_subscription_expired(self):
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.post(
            self.list_url,
            [self._record_payload(self.labour)],
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_EXPIRED,
        )
        self.assertFalse(DailyRecord.objects.exists())

    def test_list_allowed_when_subscription_expired(self):
        self._create_daily_record()
        self.subscription.paid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["paid_until"])

        response = self.client.get(self.list_url, {"date": self.today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = _by_labour_id(response)
        self.assertTrue(by_id[self.labour.pk]["records"])
        self.assertEqual(len(by_id), 2)


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
        )
        self._assign_site(self.user, self.site)

        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
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

    def _create_daily_record(self, date, **kwargs):
        labour = kwargs.pop("labour", self.labour)
        defaults = {
            "company": labour.company,
            "labour": labour,
            "site": labour.current_site,
            "date": date,
            "present": Decimal("1"),
            "wage": 500,
        }
        defaults.update(kwargs)
        if "present" in defaults and defaults["present"] is not None:
            defaults["present"] = Decimal(str(defaults["present"]))
        return DailyRecord.objects.create(**defaults)

    def _create_session_via_orm(self, labour=None, *, start_date=None, end_date=None, **kwargs):
        labour = labour or self.labour
        if end_date is None:
            end_date = timezone.localdate() - timedelta(days=1)
        if start_date is None:
            start_date = end_date - timedelta(days=2)
        defaults = {
            "company": labour.company,
            "labour": labour,
            "start_date": start_date,
            "end_date": end_date,
            "present_days": Decimal("1"),
            "salary_earnings": 500,
            "extra_earnings": 0,
            "total_fooding_pay": 0,
            "total_advance_pay": 0,
            "total_return": 0,
            "affected_rows": 1,
            "previous_payable": 0,
        }
        defaults.update(kwargs)
        return LabourSession.objects.create(**defaults)

    def _seed_open_period(self):
        """Two daily records covering attendance + cash in the open period."""
        self.day1 = timezone.localdate() - timedelta(days=3)
        self.day2 = timezone.localdate() - timedelta(days=1)
        self._create_daily_record(
            self.day1,
            present="1",
            wage=500,
            return_amount=200,
        )
        self._create_daily_record(
            self.day2,
            present="0.5",
            wage=500,
            extra_earn=100,
            advance_pay=1000,
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
        other_site = Site.objects.create(
            name="Foreign",
            company=other,
        )
        foreign_labour = Labour.objects.create(
            name="Secret",
            company=other,
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
        self.assertIn("created_at", data)
        self.assertNotIn("created_date", data)
        self.assertEqual(Decimal(data["present_days"]), Decimal("1.5"))
        self.assertEqual(data["salary_earnings"], 750)  # 1*500 + 0.5*500
        self.assertEqual(data["extra_earnings"], 100)
        self.assertEqual(data["total_advance_pay"], 1000)
        self.assertEqual(data["total_fooding_pay"], 0)
        self.assertEqual(data["total_payment"], 1000)
        self.assertEqual(data["total_return"], 200)
        self.assertEqual(data["total_earnings"], 850)
        self.assertEqual(data["payable"], 850 + 200 - 1000)
        self.assertEqual(data["previous_payable"], 0)
        self.assertEqual(data["cumulative_payable"], 50)
        self.assertNotIn("site", data)
        self.assertNotIn("details", data)

        session = LabourSession.objects.get()
        self.assertEqual(session.affected_rows, 2)
        self.assertEqual(session.previous_payable, 0)
        self.assertEqual(session.cumulative_payable, 50)

        self.labour.refresh_from_db()
        self.assertEqual(self.labour.last_session_date, self.day2)

    def test_create_carries_previous_cumulative_payable(self):
        first = self._create_session_via_orm(
            end_date=timezone.localdate() - timedelta(days=2),
            salary_earnings=500,
            extra_earnings=0,
            total_fooding_pay=200,
            total_advance_pay=0,
            total_return=0,
            previous_payable=100,
        )
        self.assertEqual(first.cumulative_payable, 400)  # 100 + 300

        day = timezone.localdate() - timedelta(days=1)
        self._create_daily_record(day, present="1", wage=500)
        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["previous_payable"], 400)
        self.assertEqual(response.data["payable"], 500)
        self.assertEqual(response.data["cumulative_payable"], 900)

    def test_create_aggregates_multi_site_records(self):
        other_site = Site.objects.create(
            name="Metro Rail",
            company=self.company,
        )
        day1 = timezone.localdate() - timedelta(days=2)
        day2 = timezone.localdate() - timedelta(days=1)
        self._create_daily_record(day1, present="1", wage=500, site=other_site)
        self._create_daily_record(day2, present="1", wage=500, advance_pay=300)

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["salary_earnings"], 1000)
        self.assertEqual(response.data["total_payment"], 300)

    def test_create_seals_records_without_touching_updated_at(self):
        self._seed_open_period()
        record = DailyRecord.objects.get(date=self.day1)
        record_updated_at = record.updated_at

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        record.refresh_from_db()
        self.assertTrue(record.is_sealed)
        self.assertEqual(record.updated_at, record_updated_at)
        self.assertFalse(
            DailyRecord.objects.filter(labour=self.labour, is_sealed=False).exists()
        )

    def test_create_does_not_touch_other_labour_records(self):
        self._seed_open_period()
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            current_site=self.site,
        )
        other_record = self._create_daily_record(
            self.day1, present="1", labour=other_labour
        )

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        other_record.refresh_from_db()
        self.assertFalse(other_record.is_sealed)
        other_labour.refresh_from_db()
        self.assertIsNone(other_labour.last_session_date)

    def test_create_only_counts_records_after_last_session_date(self):
        boundary = timezone.localdate() - timedelta(days=2)
        Labour.objects.filter(pk=self.labour.pk).update(last_session_date=boundary)
        old_record = self._create_daily_record(
            boundary - timedelta(days=1), present="1", wage=500
        )
        self._create_daily_record(
            timezone.localdate() - timedelta(days=1), present="1", wage=500
        )

        response = self.client.post(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["start_date"],
            str(timezone.localdate() - timedelta(days=1)),
        )
        self.assertEqual(response.data["salary_earnings"], 500)
        self.assertEqual(Decimal(response.data["present_days"]), Decimal("1"))

        old_record.refresh_from_db()
        self.assertFalse(old_record.is_sealed)

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
        self.assertEqual(_list_results(response), [])

    def test_list_uses_list_serializer_fields(self):
        self._create_session_via_orm()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = _list_results(response)
        self.assertEqual(len(results), 1)
        self.assertCountEqual(
            list(results[0].keys()),
            [
                "id",
                "start_date",
                "end_date",
                "payable",
                "cumulative_payable",
            ],
        )

    def test_list_orders_latest_first(self):
        older = self._create_session_via_orm(
            end_date=timezone.localdate() - timedelta(days=5)
        )
        latest = self._create_session_via_orm(end_date=timezone.localdate())
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in _list_results(response)], [latest.pk, older.pk]
        )

    def test_retrieve_session(self):
        session = self._create_session_via_orm(affected_rows=0)
        response = self.client.get(self._detail_url(self.labour.pk, session.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], session.pk)
        self.assertFalse(response.data["is_modified"])
        self.assertTrue(response.data["is_latest"])
        self.assertNotIn("details", response.data)

    def test_retrieve_marks_modified_when_rows_removed(self):
        self._seed_open_period()
        create = self.client.post(self.list_url)
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        session_id = create.data["id"]
        DailyRecord.objects.filter(date=self.day2).delete()

        response = self.client.get(self._detail_url(self.labour.pk, session_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_modified"])
        self.assertTrue(response.data["is_latest"])

    def test_retrieve_marks_not_latest_for_older_session(self):
        older = self._create_session_via_orm(
            end_date=timezone.localdate() - timedelta(days=5)
        )
        self._create_session_via_orm(end_date=timezone.localdate())

        response = self.client.get(self._detail_url(self.labour.pk, older.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_latest"])

    def test_cannot_see_other_labour_sessions(self):
        other_labour = Labour.objects.create(
            name="Rahim",
            company=self.company,
            current_site=self.site,
        )
        self._create_session_via_orm(labour=other_labour)
        mine = self._create_session_via_orm()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in _list_results(response)], [mine.pk]
        )


class LabourSessionRunningSessionTests(LabourSessionAPITestCase):
    def test_running_session_empty_when_no_records(self):
        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

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
        self.assertEqual(response.data["previous_payable"], 0)
        self.assertEqual(response.data["cumulative_payable"], 50)

    def test_running_session_includes_previous_cumulative_payable(self):
        self._create_session_via_orm(
            end_date=timezone.localdate() - timedelta(days=5),
            salary_earnings=500,
            extra_earnings=0,
            total_fooding_pay=200,
            total_advance_pay=0,
            total_return=0,
            previous_payable=0,
        )
        self.labour.refresh_from_db()

        day = timezone.localdate() - timedelta(days=1)
        self._create_daily_record(day, present="1", wage=500)

        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["payable"], 500)
        self.assertEqual(response.data["previous_payable"], 300)
        self.assertEqual(response.data["cumulative_payable"], 800)

    def test_running_session_after_close_returns_204(self):
        self._seed_open_period()
        create = self.client.post(self.list_url)
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)

        response = self.client.get(self._running_url(self.labour.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


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

        self.assertFalse(DailyRecord.objects.filter(is_sealed=True).exists())
        self.labour.refresh_from_db()
        self.assertIsNone(self.labour.last_session_date)

    def test_delete_non_latest_session_returns_400(self):
        older = self._create_session_via_orm(
            end_date=timezone.localdate() - timedelta(days=5)
        )
        self._create_session_via_orm(end_date=timezone.localdate())

        response = self.client.delete(self._detail_url(self.labour.pk, older.pk))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SESSION_NOT_LATEST,
        )
        self.assertEqual(LabourSession.objects.count(), 2)

    def test_delete_allowed_when_only_record_amount_changed(self):
        """Count-only guard: amount edits do not block delete."""
        session = self._create_session_via_api()
        DailyRecord.objects.filter(date=self.day2).update(advance_pay=9999)

        response = self.client.delete(
            self._detail_url(self.labour.pk, session.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LabourSession.objects.filter(pk=session.pk).exists())

    def test_delete_blocked_when_record_removed(self):
        session = self._create_session_via_api()
        DailyRecord.objects.filter(date=self.day2).delete()

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
        self.assertEqual(len(_list_results(response)), 1)
