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
from labours.models import Attendance, Labour
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

    def test_log_created_attendance(self):
        att = Attendance.objects.create(
            labour=self.labour,
            site=self.site,
            company=self.company,
            date=timezone.localdate(),
            present=Decimal("1"),
            salary=500,
        )
        log = log_created(self.user, att)
        self.assertEqual(log.action, ActivityAction.CREATED)
        self.assertEqual(log.entity_type, ActivityEntityType.ATTENDANCE)
        self.assertEqual(log.entity_id, att.pk)
        self.assertEqual(log.site_id, self.site.pk)
        self.assertEqual(log.business_date, att.date)
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.labour_id, self.labour.pk)
        self.assertEqual(log.labour_name, "Worker")
        self.assertIn("present", log.changes)

    def test_log_updated_attendance_keeps_labour_name(self):
        att = Attendance.objects.create(
            labour=self.labour,
            site=self.site,
            company=self.company,
            date=timezone.localdate(),
            present=Decimal("1"),
            salary=500,
        )
        old = snapshot_instance(att)
        att.present = Decimal("1.5")
        att.save(update_fields=["present"])
        log = log_updated(self.user, att, old_snapshot=old)
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
