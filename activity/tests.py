from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserSite
from activity.models import ActivityAction, ActivityLog
from activity.services import (
    build_changes,
    log_change,
    log_deletion,
    resolve_site_id,
    snapshot_instance,
)
from company.models import Company
from labours.models import Labour, LabourPayment, LabourPaymentCategory, LabourPaymentType
from sites.models import PrivateSiteCash, Site, SiteCash, SiteCashType
from subscription.models import Subscription

User = get_user_model()


class ActivityServiceTests(TestCase):
    def test_build_changes_only_diffs(self):
        changes = build_changes(
            {"amount": 1000, "note": "a"},
            {"amount": 2000, "note": "a"},
        )
        self.assertEqual(changes, {"amount": {"before": 1000, "after": 2000}})

    def test_build_changes_deletion_sets_after_null(self):
        changes = build_changes({"amount": 1000, "type": "deposit"}, after=None)
        self.assertEqual(
            changes,
            {
                "amount": {"before": 1000, "after": None},
                "type": {"before": "deposit", "after": None},
            },
        )

    def test_log_change_skips_empty_diff(self):
        company = Company.objects.create(name="Co")
        user = User.objects.create_user(
            phone_number="+8801711111111",
            name="U",
            password="x",
            company=company,
        )
        site = Site.objects.create(name="S", company=company, created_by=user)
        cash = SiteCash.objects.create(
            company=company,
            site=site,
            type=SiteCashType.DEPOSIT,
            amount=100,
            created_by=user,
        )
        result = log_change(
            actor=user,
            company=company,
            instance=cash,
            before={"amount": 100},
            after={"amount": 100},
        )
        self.assertIsNone(result)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_log_change_sets_site_id(self):
        company = Company.objects.create(name="Co")
        user = User.objects.create_user(
            phone_number="+8801711111113",
            name="U",
            password="x",
            company=company,
        )
        site = Site.objects.create(name="S", company=company, created_by=user)
        cash = SiteCash.objects.create(
            company=company,
            site=site,
            type=SiteCashType.DEPOSIT,
            amount=100,
            created_by=user,
        )
        log = log_change(
            actor=user,
            company=company,
            instance=cash,
            before={"amount": 100},
            after={"amount": 200},
        )
        self.assertEqual(log.site_id, site.pk)

    def test_resolve_site_id_uses_labour_current_site(self):
        company = Company.objects.create(name="Co")
        user = User.objects.create_user(
            phone_number="+8801711111114",
            name="U",
            password="x",
            company=company,
        )
        site = Site.objects.create(name="S", company=company, created_by=user)
        labour = Labour.objects.create(
            name="Karim",
            company=company,
            created_by=user,
            current_site=site,
            default_salary=500,
        )
        self.assertEqual(resolve_site_id(labour), site.pk)


class ActivityLogImmutabilityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
        self.user = User.objects.create_user(
            phone_number="+8801711111112",
            name="U",
            password="x",
            company=self.company,
        )
        self.site = Site.objects.create(
            name="S", company=self.company, created_by=self.user
        )
        self.log = ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(Site),
            object_id=self.site.pk,
            action_flag=ActivityAction.CHANGE,
            changes={"name": {"before": "a", "after": "b"}},
        )

    def test_cannot_update(self):
        with self.assertRaises(ValidationError):
            self.log.action_flag = ActivityAction.DELETION
            self.log.save()

    def test_cannot_delete(self):
        with self.assertRaises(ValidationError):
            self.log.delete()


class ActivityLogAPITestCase(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self._grant_view_activity(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
            created_by=self.user,
        )
        self.list_url = reverse(
            "site-activity-log-list",
            kwargs={"version": "v1", "site_pk": self.site.pk},
        )

    def _grant_view_activity(self, user):
        ct = ContentType.objects.get_for_model(ActivityLog)
        perm = Permission.objects.get(content_type=ct, codename="view_activitylog")
        user.user_permissions.add(perm)

    def _grant_view_model(self, user, model):
        ct = ContentType.objects.get_for_model(model)
        perm = Permission.objects.get(content_type=ct, codename=f"view_{ct.model}")
        user.user_permissions.add(perm)

    def _detail_url(self, pk):
        return reverse(
            "site-activity-log-detail",
            kwargs={"version": "v1", "site_pk": self.site.pk, "pk": pk},
        )


class ActivityLogReadAPITests(ActivityLogAPITestCase):
    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_view_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_member_returns_403(self):
        self._grant_view_model(self.user, SiteCash)
        UserSite.objects.filter(user=self.user, site=self.site).delete()
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_scoped_to_site(self):
        self._grant_view_model(self.user, SiteCash)
        other_site = Site.objects.create(
            name="Other Site",
            company=self.company,
            created_by=self.user,
        )
        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(SiteCash),
            object_id=1,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 1, "after": 2}},
        )
        ActivityLog.objects.create(
            company=self.company,
            site_id=other_site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(SiteCash),
            object_id=2,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 3, "after": 4}},
        )
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["site_id"], self.site.pk)
        self.assertEqual(response.data[0]["object_id"], 1)

    def test_hides_private_cash_without_view_perm(self):
        self._grant_view_model(self.user, SiteCash)
        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(SiteCash),
            object_id=1,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 1, "after": 2}},
        )
        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(PrivateSiteCash),
            object_id=2,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 3, "after": 4}},
        )
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["content_type"], "sitecash")

    def test_shows_private_cash_with_view_perm(self):
        self._grant_view_model(self.user, SiteCash)
        self._grant_view_model(self.user, PrivateSiteCash)
        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(PrivateSiteCash),
            object_id=2,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 3, "after": 4}},
        )
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["content_type"], "privatesitecash")

    def test_filter_by_model_and_action(self):
        self._grant_view_model(self.user, SiteCash)
        self._grant_view_model(self.user, LabourPayment)
        ct_cash = ContentType.objects.get_for_model(SiteCash)
        ct_pay = ContentType.objects.get_for_model(LabourPayment)
        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ct_cash,
            object_id=10,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 1, "after": 2}},
        )
        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ct_pay,
            object_id=20,
            action_flag=ActivityAction.DELETION,
            changes={"amount": {"before": 5, "after": None}},
        )
        response = self.client.get(
            self.list_url,
            {"model": "sites.sitecash", "action_flag": ActivityAction.CHANGE},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["object_id"], 10)
        self.assertEqual(response.data[0]["content_type"], "sitecash")
        self.assertEqual(response.data[0]["app_label"], "sites")

    def test_retrieve(self):
        self._grant_view_model(self.user, SiteCash)
        log = ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(SiteCash),
            object_id=99,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 1, "after": 2}},
        )
        response = self.client.get(self._detail_url(log.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], log.pk)
        self.assertEqual(response.data["site_id"], self.site.pk)
        self.assertEqual(
            response.data["changes"],
            {"amount": {"before": 1, "after": 2}},
        )

    def test_retrieve_hidden_resource_returns_404(self):
        self._grant_view_model(self.user, SiteCash)
        log = ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(PrivateSiteCash),
            object_id=99,
            action_flag=ActivityAction.CHANGE,
            changes={"amount": {"before": 1, "after": 2}},
        )
        response = self.client.get(self._detail_url(log.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_post_not_allowed(self):
        response = self.client.post(self.list_url, {})
        # No add permission → 403; with add would be 405 (http_method_names).
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED),
        )


class SiteCashActivityLogTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        Subscription.objects.get(company=self.company)
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        ct = ContentType.objects.get_for_model(SiteCash)
        perms = Permission.objects.filter(
            content_type=ct,
            codename__in=[
                "view_sitecash",
                "add_sitecash",
                "change_sitecash",
                "delete_sitecash",
            ],
        )
        self.user.user_permissions.add(*perms)
        self.client.force_authenticate(user=self.user)
        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
            created_by=self.user,
        )
        self.cash = SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.DEPOSIT,
            amount=1000,
            note="opening",
            created_by=self.user,
            date=timezone.localdate(),
        )
        self.detail_url = reverse(
            "site-cash-detail",
            kwargs={"version": "v1", "site_pk": self.site.pk, "pk": self.cash.pk},
        )

    def test_patch_logs_change(self):
        response = self.client.patch(self.detail_url, {"amount": 1500})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.CHANGE)
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.company_id, self.company.pk)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.object_id, self.cash.pk)
        self.assertEqual(
            log.changes,
            {"amount": {"before": 1000, "after": 1500}},
        )

    def test_patch_same_value_no_log(self):
        response = self.client.patch(self.detail_url, {"amount": 1000})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_delete_logs_deletion(self):
        cash_id = self.cash.pk
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(SiteCash.objects.filter(pk=cash_id).exists())
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.DELETION)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.object_id, cash_id)
        self.assertEqual(log.changes["amount"], {"before": 1000, "after": None})
        self.assertIn("type", log.changes)
        self.assertIsNone(log.changes["type"]["after"])


class LabourPaymentActivityLogTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        Subscription.objects.get(company=self.company)
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        ct = ContentType.objects.get_for_model(LabourPayment)
        perms = Permission.objects.filter(
            content_type=ct,
            codename__in=[
                "view_labourpayment",
                "add_labourpayment",
                "change_labourpayment",
                "delete_labourpayment",
            ],
        )
        self.user.user_permissions.add(*perms)
        self.client.force_authenticate(user=self.user)
        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
            created_by=self.user,
        )
        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
        )
        self.payment = LabourPayment.objects.create(
            company=self.company,
            labour=self.labour,
            site=self.site,
            date=timezone.localdate(),
            type=LabourPaymentType.PAYMENT,
            category=LabourPaymentCategory.ADVANCE,
            amount=2000,
            created_by=self.user,
            is_sealed=False,
        )
        self.detail_url = reverse(
            "labour-payment-detail",
            kwargs={
                "version": "v1",
                "labour_pk": self.labour.pk,
                "pk": self.payment.pk,
            },
        )

    def test_patch_logs_change(self):
        response = self.client.patch(self.detail_url, {"amount": 2500})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.CHANGE)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(
            log.changes,
            {"amount": {"before": 2000, "after": 2500}},
        )

    def test_sealed_delete_returns_403_and_no_log(self):
        self.payment.is_sealed = True
        self.payment.save(update_fields=["is_sealed"])
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ActivityLog.objects.count(), 0)
        self.assertTrue(LabourPayment.objects.filter(pk=self.payment.pk).exists())

    def test_delete_logs_deletion(self):
        payment_id = self.payment.pk
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.DELETION)
        self.assertEqual(log.object_id, payment_id)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.company_id, self.company.pk)


class SiteActivityLogTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        sub = Subscription.objects.get(company=self.company)
        sub.open_site_limit = 5
        sub.save(update_fields=["open_site_limit"])
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        ct = ContentType.objects.get_for_model(Site)
        perms = Permission.objects.filter(
            content_type=ct,
            codename__in=["view_site", "add_site", "change_site", "delete_site"],
        )
        self.user.user_permissions.add(*perms)
        self.client.force_authenticate(user=self.user)
        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.detail_url = reverse(
            "site-detail",
            kwargs={"version": "v1", "pk": self.site.pk},
        )

    def test_patch_logs_change(self):
        response = self.client.patch(self.detail_url, {"name": "Padma Renamed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.CHANGE)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(
            log.changes,
            {"name": {"before": "Padma Bridge", "after": "Padma Renamed"}},
        )

    def test_delete_cascades_activity_logs(self):
        # Pre-existing change log for this site must vanish with CASCADE.
        from django.contrib.contenttypes.models import ContentType

        ActivityLog.objects.create(
            company=self.company,
            site_id=self.site.pk,
            actor=self.user,
            content_type=ContentType.objects.get_for_model(Site),
            object_id=self.site.pk,
            action_flag=ActivityAction.CHANGE,
            changes={"name": {"before": "a", "after": "b"}},
        )
        self.assertEqual(ActivityLog.objects.count(), 1)
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_delete_with_children_no_log(self):
        SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.DEPOSIT,
            amount=100,
            created_by=self.user,
            date=timezone.localdate(),
        )
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ActivityLog.objects.count(), 0)
        self.assertTrue(Site.objects.filter(pk=self.site.pk).exists())


class LabourActivityLogTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        Subscription.objects.get(company=self.company)
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        ct = ContentType.objects.get_for_model(Labour)
        perms = Permission.objects.filter(
            content_type=ct,
            codename__in=["view_labour", "add_labour", "change_labour"],
        )
        self.user.user_permissions.add(*perms)
        self.client.force_authenticate(user=self.user)
        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.other_site = Site.objects.create(
            name="Meghna Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.labour = Labour.objects.create(
            name="Karim",
            company=self.company,
            created_by=self.user,
            current_site=self.site,
            default_salary=500,
        )
        self.detail_url = reverse(
            "labour-detail",
            kwargs={"version": "v1", "pk": self.labour.pk},
        )

    def test_patch_name_logs_on_current_site(self):
        response = self.client.patch(self.detail_url, {"name": "Karim Updated"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.CHANGE)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.object_id, self.labour.pk)
        self.assertEqual(
            log.changes,
            {"name": {"before": "Karim", "after": "Karim Updated"}},
        )

    def test_patch_current_site_logs_on_destination_site(self):
        response = self.client.patch(
            self.detail_url, {"current_site": self.other_site.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.get()
        self.assertEqual(log.action_flag, ActivityAction.CHANGE)
        # Destination site, not the previous assignment.
        self.assertEqual(log.site_id, self.other_site.pk)
        self.assertEqual(
            log.changes,
            {
                "current_site_id": {
                    "before": self.site.pk,
                    "after": self.other_site.pk,
                }
            },
        )
