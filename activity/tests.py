from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from activity.models import ActivityAction, ActivityEntityType, ActivityLog
from activity.services import (
    diff_snapshots,
    log_created,
    log_deleted,
    log_updated,
    snapshot_instance,
)
from company.models import Company
from labours.models import DailyRecord, Labour
from sites.models import Site, SiteCash, SiteCashType
from subscription.models import Subscription

User = get_user_model()


class ActivityServiceTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Log Co")
        self.user = User.objects.create_user(
            phone_number="+8801711111111",
            name="Logger",
            password="pass-12345",
            company=self.company,
            is_companyadmin=True,
        )
        self.site = Site.objects.create(name="Site A", company=self.company)
        self.labour = Labour.objects.create(
            name="Worker",
            company=self.company,
            current_site=self.site,
            default_salary=500,
        )

    def test_log_created_daily_record(self):
        record = DailyRecord.objects.create(
            labour=self.labour,
            site=self.site,
            company=self.company,
            date=timezone.localdate(),
            present=Decimal("1"),
            wage=500,
        )
        log = log_created(self.user, record)
        self.assertEqual(log.action, ActivityAction.CREATED)
        self.assertEqual(log.entity_type, ActivityEntityType.DAILY_RECORD)
        self.assertEqual(log.entity_id, record.pk)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.business_date, record.date)
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.labour_id, self.labour.pk)
        self.assertEqual(log.labour_name, "Worker")
        self.assertIn("present", log.changes)

    def test_log_updated_daily_record_keeps_labour_name(self):
        record = DailyRecord.objects.create(
            labour=self.labour,
            site=self.site,
            company=self.company,
            date=timezone.localdate(),
            present=Decimal("1"),
            wage=500,
        )
        old = snapshot_instance(record)
        record.present = Decimal("1.5")
        record.save(update_fields=["present"])
        log = log_updated(self.user, record, old_snapshot=old)
        self.assertEqual(log.labour_id, self.labour.pk)
        self.assertEqual(log.labour_name, "Worker")
        self.assertEqual(log.changes["present"]["old"], "1")
        self.assertEqual(log.changes["present"]["new"], "1.5")

    def test_log_updated_diff(self):
        cash = SiteCash.objects.create(
            site=self.site,
            company=self.company,
            type=SiteCashType.DEPOSIT,
            date=timezone.localdate(),
            amount=1000,
        )
        old = snapshot_instance(cash)
        cash.amount = 1500
        cash.save(update_fields=["amount"])
        log = log_updated(self.user, cash, old_snapshot=old)
        self.assertEqual(log.action, ActivityAction.UPDATED)
        self.assertEqual(log.changes["amount"]["old"], 1000)
        self.assertEqual(log.changes["amount"]["new"], 1500)

    def test_log_updated_noop_when_unchanged(self):
        cash = SiteCash.objects.create(
            site=self.site,
            company=self.company,
            type=SiteCashType.DEPOSIT,
            date=timezone.localdate(),
            amount=1000,
        )
        old = snapshot_instance(cash)
        self.assertIsNone(log_updated(self.user, cash, old_snapshot=old))

    def test_log_deleted(self):
        cash = SiteCash.objects.create(
            site=self.site,
            company=self.company,
            type=SiteCashType.COST,
            date=timezone.localdate(),
            amount=50,
        )
        pk = cash.pk
        log = log_deleted(self.user, cash)
        cash.delete()
        self.assertEqual(log.action, ActivityAction.DELETED)
        self.assertEqual(log.entity_id, pk)
        self.assertEqual(log.changes["amount"], 50)

    def test_diff_snapshots(self):
        changes = diff_snapshots({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
        self.assertEqual(
            changes, {"b": {"old": 2, "new": 3}, "c": {"old": None, "new": 4}}
        )

    def test_site_create_api_writes_activity(self):
        Subscription.objects.filter(company=self.company).update(open_site_limit=5)
        ct = ContentType.objects.get_for_model(Site)
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type=ct,
                codename__in=["view_site", "add_site", "change_site"],
            )
        )
        self.client.force_authenticate(user=self.user)
        url = reverse("site-list", kwargs={"version": "v1"})
        response = self.client.post(url, {"name": "New Site"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            ActivityLog.objects.filter(
                entity_type=ActivityEntityType.SITE,
                entity_id=response.data["id"],
                action=ActivityAction.CREATED,
                actor=self.user,
            ).exists()
        )


class PurgeActivityLogsTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Purge Co")
        self.user = User.objects.create_user(
            phone_number="+8801733333333",
            name="Purger",
            password="pass-12345",
            company=self.company,
            is_companyadmin=True,
        )

    def test_purge_deletes_old_rows(self):
        old = ActivityLog.objects.create(
            company=self.company,
            actor=self.user,
            actor_name=self.user.name,
            action=ActivityAction.CREATED,
            entity_type=ActivityEntityType.SITE,
            entity_id=1,
        )
        ActivityLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=200)
        )
        fresh = ActivityLog.objects.create(
            company=self.company,
            actor=self.user,
            actor_name=self.user.name,
            action=ActivityAction.CREATED,
            entity_type=ActivityEntityType.SITE,
            entity_id=2,
        )
        call_command("purge_activity_logs", days=180)
        self.assertFalse(ActivityLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(pk=fresh.pk).exists())


class UserActivityAPITests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="User Log Co")
        Subscription.objects.filter(company=self.company).update(
            active_user_limit=10,
        )
        self.admin = User.objects.create_user(
            phone_number="+8801744444444",
            name="Admin",
            password="pass-12345",
            company=self.company,
            is_companyadmin=True,
        )
        ct = ContentType.objects.get_for_model(User)
        self.admin.user_permissions.add(
            *Permission.objects.filter(
                content_type=ct,
                codename__in=["view_user", "add_user", "change_user"],
            )
        )
        self.other = User.objects.create_user(
            phone_number="+8801755555555",
            name="Other",
            password="pass-12345",
            company=self.company,
            is_companyadmin=False,
        )
        self.client.force_authenticate(user=self.admin)

    def test_profile_patch_logs_name_change(self):
        self.client.force_authenticate(user=self.other)
        url = reverse("user-profile", kwargs={"version": "v1"})
        response = self.client.patch(url, {"name": "Other Renamed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.filter(
            entity_type=ActivityEntityType.USER,
            entity_id=self.other.pk,
            action=ActivityAction.UPDATED,
        ).latest("id")
        self.assertEqual(log.changes["name"]["old"], "Other")
        self.assertEqual(log.changes["name"]["new"], "Other Renamed")
        self.assertNotIn("is_active", log.changes)
        self.assertNotIn("is_companyadmin", log.changes)

    def test_users_patch_logs_is_active(self):
        url = reverse(
            "user-detail", kwargs={"version": "v1", "pk": self.other.pk}
        )
        response = self.client.patch(url, {"is_active": False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = ActivityLog.objects.filter(
            entity_type=ActivityEntityType.USER,
            entity_id=self.other.pk,
            action=ActivityAction.UPDATED,
        ).latest("id")
        self.assertEqual(log.changes["is_active"]["old"], True)
        self.assertEqual(log.changes["is_active"]["new"], False)


class ActivityLogAPITests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="API Log Co")
        Subscription.objects.filter(company=self.company).update(
            paid_until=timezone.localdate() + timedelta(days=30),
        )
        self.other_company = Company.objects.create(name="Other Co")
        Subscription.objects.filter(company=self.other_company).update(
            paid_until=timezone.localdate() + timedelta(days=30),
        )

        self.site_a = Site.objects.create(name="Site A", company=self.company)
        self.site_b = Site.objects.create(name="Site B", company=self.company)
        self.other_site = Site.objects.create(
            name="Other Site", company=self.other_company
        )

        self.admin = User.objects.create_user(
            phone_number="+8801766666661",
            name="Admin",
            password="pass-12345",
            company=self.company,
            is_companyadmin=True,
        )
        self.manager = User.objects.create_user(
            phone_number="+8801766666662",
            name="Manager",
            password="pass-12345",
            company=self.company,
            is_companyadmin=False,
        )
        from accounts.models import UserSite

        UserSite.objects.create(
            user=self.manager,
            site=self.site_a,
            company=self.company,
        )

        self.labour = Labour.objects.create(
            name="Worker",
            company=self.company,
            current_site=self.site_a,
            default_salary=500,
        )

        self.log_site_a = ActivityLog.objects.create(
            company=self.company,
            site=self.site_a,
            labour=self.labour,
            labour_name=self.labour.name,
            actor=self.admin,
            actor_name=self.admin.name,
            action=ActivityAction.CREATED,
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=101,
            business_date=timezone.localdate(),
            changes={"present": "1"},
        )
        self.log_site_b = ActivityLog.objects.create(
            company=self.company,
            site=self.site_b,
            actor=self.admin,
            actor_name=self.admin.name,
            action=ActivityAction.CREATED,
            entity_type=ActivityEntityType.SITE_CASH,
            entity_id=201,
            business_date=timezone.localdate(),
            changes={"amount": 100},
        )
        self.log_private = ActivityLog.objects.create(
            company=self.company,
            site=self.site_a,
            actor=self.admin,
            actor_name=self.admin.name,
            action=ActivityAction.CREATED,
            entity_type=ActivityEntityType.PRIVATE_SITE_CASH,
            entity_id=301,
            business_date=timezone.localdate(),
            changes={"amount": 50},
        )
        self.log_user = ActivityLog.objects.create(
            company=self.company,
            site=None,
            actor=self.admin,
            actor_name=self.admin.name,
            action=ActivityAction.UPDATED,
            entity_type=ActivityEntityType.USER,
            entity_id=self.manager.pk,
            changes={"name": {"old": "Manager", "new": "Mgr"}},
        )
        self.log_other_company = ActivityLog.objects.create(
            company=self.other_company,
            site=self.other_site,
            actor=None,
            actor_name="Someone",
            action=ActivityAction.CREATED,
            entity_type=ActivityEntityType.SITE,
            entity_id=self.other_site.pk,
            changes={"name": "Other Site"},
        )

        self.list_url = reverse("activity-list", kwargs={"version": "v1"})

    def _grant(self, user, *perm_strings):
        for label in perm_strings:
            app_label, codename = label.split(".")
            perm = Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )
            user.user_permissions.add(perm)

    def test_missing_view_activitylog_returns_403(self):
        self._grant(self.admin, "labours.view_dailyrecord")
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_sees_only_daily_record_and_site_cash(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
            "sites.view_sitecash",
            "sites.view_privatesitecash",
            "accounts.view_user",
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.log_site_a.pk, self.log_site_b.pk})
        self.assertNotIn(self.log_private.pk, ids)
        self.assertNotIn(self.log_user.pk, ids)
        self.assertNotIn(self.log_other_company.pk, ids)

    def test_manager_only_sees_allowed_site_and_entity(self):
        self._grant(
            self.manager,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
            "sites.view_sitecash",
            "accounts.view_user",
        )
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        # site A daily record only: no site B cash, no private/user (not in API allowlist)
        self.assertEqual(ids, {self.log_site_a.pk})

    def test_filter_by_entity_type_and_entity_id(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
            "sites.view_sitecash",
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(
            self.list_url,
            {
                "entity_type": ActivityEntityType.DAILY_RECORD,
                "entity_id": 101,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.log_site_a.pk)

    def test_filter_reviewed_false(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url, {"reviewed": "false"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.log_site_a.pk)

    def test_list_is_paginated(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
            "sites.view_sitecash",
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url, {"page_size": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["next"])

    def test_review_requires_change_permission(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse(
            "activity-review",
            kwargs={"version": "v1", "pk": self.log_site_a.pk},
        )
        response = self.client.patch(url, {"review_note": "ok"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_review_marks_one_way(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "activity.change_activitylog",
            "labours.view_dailyrecord",
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse(
            "activity-review",
            kwargs={"version": "v1", "pk": self.log_site_a.pk},
        )
        response = self.client.patch(url, {"review_note": "checked"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["reviewed_at"])
        self.assertEqual(response.data["reviewed_by"], self.admin.pk)
        self.assertEqual(response.data["review_note"], "checked")

        again = self.client.patch(url, {"review_note": "again"})
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)

    def test_review_bulk_marks_many(self):
        extra = ActivityLog.objects.create(
            company=self.company,
            site=self.site_a,
            labour=self.labour,
            labour_name=self.labour.name,
            actor=self.admin,
            actor_name=self.admin.name,
            action=ActivityAction.UPDATED,
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=102,
            business_date=timezone.localdate(),
            changes={"present": "0.5"},
        )
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "activity.change_activitylog",
            "labours.view_dailyrecord",
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse("activity-review-bulk", kwargs={"version": "v1"})
        response = self.client.post(
            url,
            {"ids": [self.log_site_a.pk, extra.pk]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(len(response.data["results"]), 2)
        self.log_site_a.refresh_from_db()
        extra.refresh_from_db()
        self.assertIsNotNone(self.log_site_a.reviewed_at)
        self.assertIsNotNone(extra.reviewed_at)
        self.assertIsNone(self.log_site_a.review_note)

    def test_review_bulk_skips_already_reviewed(self):
        self.log_site_a.reviewed_at = timezone.now()
        self.log_site_a.reviewed_by = self.admin
        self.log_site_a.save(update_fields=["reviewed_at", "reviewed_by"])
        extra = ActivityLog.objects.create(
            company=self.company,
            site=self.site_a,
            labour=self.labour,
            labour_name=self.labour.name,
            actor=self.admin,
            actor_name=self.admin.name,
            action=ActivityAction.UPDATED,
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=103,
            business_date=timezone.localdate(),
            changes={"present": "1"},
        )
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "activity.change_activitylog",
            "labours.view_dailyrecord",
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse("activity-review-bulk", kwargs={"version": "v1"})
        response = self.client.post(
            url,
            {"ids": [self.log_site_a.pk, extra.pk]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated"], 1)
        extra.refresh_from_db()
        self.assertIsNotNone(extra.reviewed_at)

    def test_review_bulk_requires_change_permission(self):
        self._grant(
            self.admin,
            "activity.view_activitylog",
            "labours.view_dailyrecord",
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse("activity-review-bulk", kwargs={"version": "v1"})
        response = self.client.post(
            url, {"ids": [self.log_site_a.pk]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_cannot_review_other_site_log(self):
        self._grant(
            self.manager,
            "activity.view_activitylog",
            "activity.change_activitylog",
            "sites.view_sitecash",
        )
        self.client.force_authenticate(user=self.manager)
        url = reverse(
            "activity-review",
            kwargs={"version": "v1", "pk": self.log_site_b.pk},
        )
        response = self.client.patch(url, {})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
