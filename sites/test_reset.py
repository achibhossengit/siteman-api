from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, UserSite
from activity.models import ActivityAction, ActivityEntityType, ActivityLog
from company.models import Company
from labours.models import DailyRecord, Labour, LabourSession
from sites.models import (
    BillingCategory,
    PrivateSiteCash,
    PrivateSiteCashType,
    Site,
    SiteCash,
    SiteCashType,
)
from sites.reset import preview_site_reset, reset_site


class SiteResetTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Reset Co")
        self.site = Site.objects.create(name="Site A", company=self.company)
        self.other_site = Site.objects.create(name="Site B", company=self.company)
        self.actor = User.objects.create_superuser(
            phone_number="+8801700000001",
            name="Staff",
            password="pass-12345",
        )
        self.day1 = timezone.localdate() - timedelta(days=3)
        self.day2 = timezone.localdate() - timedelta(days=2)
        self.day3 = timezone.localdate() - timedelta(days=1)

    def _labour(self, name="Worker", current_site=None):
        return Labour.objects.create(
            company=self.company,
            name=name,
            current_site=current_site or self.site,
        )

    def _record(self, labour, site, day, **kwargs):
        defaults = {
            "company": self.company,
            "labour": labour,
            "site": site,
            "date": day,
            "present": Decimal("1"),
            "wage": 500,
        }
        defaults.update(kwargs)
        return DailyRecord.objects.create(**defaults)

    def _session(self, labour, start, end=None, affected_rows=1, previous_payable=0):
        end = end or start
        return LabourSession.objects.create(
            company=self.company,
            labour=labour,
            start_date=start,
            end_date=end,
            present_days=Decimal("1"),
            salary_earnings=500,
            extra_earnings=0,
            total_fooding_pay=0,
            total_advance_pay=0,
            total_return=0,
            affected_rows=affected_rows,
            previous_payable=previous_payable,
        )

    def _log(self, *, entity_type, entity_id, site=None, labour=None):
        return ActivityLog.objects.create(
            company=self.company,
            site=site,
            labour=labour,
            actor=self.actor,
            actor_name=self.actor.name,
            action=ActivityAction.CREATED,
            entity_type=entity_type,
            entity_id=entity_id,
        )


class ResetSiteServiceTests(SiteResetTestCase):
    def test_deletes_cash_categories_records_and_keeps_labours(self):
        labour = self._labour()
        user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Incharge",
            password="pass-12345",
            company=self.company,
        )
        assignment = UserSite.objects.create(
            user=user, site=self.site, company=self.company
        )
        category = BillingCategory.objects.create(
            company=self.company, site=self.site, name="Floor-1"
        )
        cash = SiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=SiteCashType.DEPOSIT,
            amount=1000,
        )
        private = PrivateSiteCash.objects.create(
            company=self.company,
            site=self.site,
            type=PrivateSiteCashType.BILL,
            amount=200,
        )
        record = self._record(labour, self.site, self.day1)
        self._log(
            entity_type=ActivityEntityType.SITE_CASH,
            entity_id=cash.pk,
            site=self.site,
        )
        self._log(
            entity_type=ActivityEntityType.PRIVATE_SITE_CASH,
            entity_id=private.pk,
            site=self.site,
        )
        self._log(
            entity_type=ActivityEntityType.BILLING_CATEGORY,
            entity_id=category.pk,
            site=self.site,
        )
        self._log(
            entity_type=ActivityEntityType.DAILY_RECORD,
            entity_id=record.pk,
            site=self.site,
            labour=labour,
        )
        labour_log = self._log(
            entity_type=ActivityEntityType.LABOUR,
            entity_id=labour.pk,
            site=self.site,
            labour=labour,
        )
        site_log = self._log(
            entity_type=ActivityEntityType.SITE,
            entity_id=self.site.pk,
            site=self.site,
        )

        reset_site(self.site, actor=self.actor)

        self.assertFalse(DailyRecord.objects.filter(site=self.site).exists())
        self.assertFalse(SiteCash.objects.filter(site=self.site).exists())
        self.assertFalse(PrivateSiteCash.objects.filter(site=self.site).exists())
        self.assertFalse(BillingCategory.objects.filter(site=self.site).exists())
        self.assertTrue(Labour.objects.filter(pk=labour.pk).exists())
        self.assertTrue(Site.objects.filter(pk=self.site.pk).exists())
        self.assertTrue(UserSite.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(pk=labour_log.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(pk=site_log.pk).exists())
        self.assertFalse(
            ActivityLog.objects.filter(
                site=self.site,
                entity_type__in=[
                    ActivityEntityType.SITE_CASH,
                    ActivityEntityType.PRIVATE_SITE_CASH,
                    ActivityEntityType.BILLING_CATEGORY,
                    ActivityEntityType.DAILY_RECORD,
                ],
            ).exists()
        )
        self.assertFalse(
            ActivityLog.objects.filter(
                entity_type=ActivityEntityType.SITE,
                entity_id=self.site.pk,
                action=ActivityAction.UPDATED,
            ).exists()
        )
        entry = LogEntry.objects.get(
            user=self.actor,
            object_id=str(self.site.pk),
            action_flag=CHANGE,
        )
        self.assertEqual(
            entry.content_type,
            ContentType.objects.get_for_model(Site),
        )
        self.assertIn("Reset site operational data", entry.change_message)

    def test_last_session_only_unwinds_that_session(self):
        labour = self._labour()
        other_record = self._record(labour, self.other_site, self.day1)
        self._session(labour, self.day1)
        site_record = self._record(labour, self.site, self.day2)
        last = self._session(labour, self.day2, previous_payable=500)
        other_record.refresh_from_db()
        site_record.refresh_from_db()
        self.assertTrue(other_record.is_sealed)
        self.assertTrue(site_record.is_sealed)

        reset_site(self.site, actor=self.actor)

        self.assertFalse(DailyRecord.objects.filter(pk=site_record.pk).exists())
        self.assertFalse(LabourSession.objects.filter(pk=last.pk).exists())
        self.assertEqual(LabourSession.objects.filter(labour=labour).count(), 1)
        other_record.refresh_from_db()
        self.assertTrue(other_record.is_sealed)
        labour.refresh_from_db()
        self.assertEqual(labour.last_session_date, self.day1)

    def test_not_last_session_deletes_later_sessions_on_other_site(self):
        labour = self._labour()
        a_record = self._record(labour, self.site, self.day1)
        first = self._session(labour, self.day1)
        b_record = self._record(labour, self.other_site, self.day2)
        later = self._session(labour, self.day2, previous_payable=500)
        session_log = self._log(
            entity_type=ActivityEntityType.LABOUR_SESSION,
            entity_id=later.pk,
            site=self.other_site,
            labour=labour,
        )

        reset_site(self.site, actor=self.actor)

        self.assertFalse(DailyRecord.objects.filter(pk=a_record.pk).exists())
        self.assertFalse(LabourSession.objects.filter(pk=first.pk).exists())
        self.assertFalse(LabourSession.objects.filter(pk=later.pk).exists())
        self.assertFalse(ActivityLog.objects.filter(pk=session_log.pk).exists())
        b_record.refresh_from_db()
        self.assertFalse(b_record.is_sealed)
        labour.refresh_from_db()
        self.assertIsNone(labour.last_session_date)

    def test_unsealed_records_are_deleted_without_sessions(self):
        labour = self._labour()
        record = self._record(labour, self.site, self.day1)
        self.assertFalse(record.is_sealed)

        reset_site(self.site, actor=self.actor)

        self.assertFalse(DailyRecord.objects.filter(pk=record.pk).exists())
        self.assertFalse(LabourSession.objects.exists())

    def test_get_preview_does_not_delete(self):
        labour = self._labour()
        self._record(labour, self.site, self.day1)
        counts = preview_site_reset(self.site)
        self.assertEqual(counts["daily_records"], 1)
        self.assertTrue(DailyRecord.objects.filter(site=self.site).exists())


class ResetSiteAdminTests(SiteResetTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.actor)
        self.reset_url = reverse("admin:sites_site_reset", args=[self.site.pk])
        self.change_url = reverse("admin:sites_site_change", args=[self.site.pk])

    def test_change_page_shows_reset_button(self):
        response = self.client.get(self.change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.reset_url)

    def test_get_confirmation_does_not_mutate(self):
        labour = self._labour()
        self._record(labour, self.site, self.day1)
        response = self.client.get(self.reset_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Type the site name")
        self.assertTrue(DailyRecord.objects.filter(site=self.site).exists())

    def test_post_without_matching_name_does_not_reset(self):
        labour = self._labour()
        self._record(labour, self.site, self.day1)
        response = self.client.post(self.reset_url, {"confirm_name": "Wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site name did not match")
        self.assertTrue(DailyRecord.objects.filter(site=self.site).exists())

    def test_post_with_name_resets_and_redirects(self):
        labour = self._labour()
        self._record(labour, self.site, self.day1)
        response = self.client.post(self.reset_url, {"confirm_name": self.site.name})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.change_url)
        self.assertFalse(DailyRecord.objects.filter(site=self.site).exists())

    def test_staff_without_superuser_is_forbidden(self):
        staff = User.objects.create_user(
            phone_number="+8801711111111",
            name="Ops",
            password="pass-12345",
            is_staff=True,
        )
        ct = ContentType.objects.get_for_model(Site)
        staff.user_permissions.add(
            Permission.objects.get(content_type=ct, codename="view_site")
        )
        self.client.force_login(staff)
        response = self.client.get(self.reset_url)
        self.assertEqual(response.status_code, 403)
        change = self.client.get(self.change_url)
        self.assertEqual(change.status_code, 200)
        self.assertNotContains(change, self.reset_url)
