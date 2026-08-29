from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .notifications import NotificationDeliveryError, deliver_otp


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="SiteMan <otp@example.com>",
)
class EmailNotificationTests(SimpleTestCase):
    def test_deliver_otp_sends_email(self):
        result = deliver_otp(
            email="user@example.com",
            otp="123456",
        )

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["user@example.com"])
        self.assertEqual(message.subject, "SiteMan verification code")
        self.assertIn("123456", message.body)

    @patch("core.notifications.logger.exception")
    @patch("core.notifications.send_mail", side_effect=RuntimeError("provider down"))
    def test_delivery_failure_returns_service_unavailable_error(
        self, _send_mail, _logger_exception
    ):
        with self.assertRaises(NotificationDeliveryError):
            deliver_otp(email="user@example.com", otp="123456")

    @patch("core.notifications.logger.exception")
    def test_missing_email_returns_service_unavailable_error(self, _logger_exception):
        with self.assertRaises(NotificationDeliveryError):
            deliver_otp(email=None, otp="123456")


class AdminUrlTests(TestCase):
    def test_admin_mounted_at_configured_path(self):
        self.assertEqual(reverse("admin:index"), f"/{settings.ADMIN_URL}")

    def test_default_admin_path_is_not_mounted(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 404)

    def test_configured_admin_path_redirects_to_login(self):
        response = self.client.get(f"/{settings.ADMIN_URL}")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/{settings.ADMIN_URL}login/", response["Location"])


class ProfilePhotoPrepareTests(SimpleTestCase):
    def test_resize_caps_longest_edge(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from core.images import MAX_EDGE, resize_profile_photo

        buf = BytesIO()
        Image.new("RGB", (800, 600), "navy").save(buf, format="JPEG")
        upload = SimpleUploadedFile(
            "wide.jpg", buf.getvalue(), content_type="image/jpeg"
        )
        result = resize_profile_photo(upload)
        with Image.open(result) as image:
            self.assertEqual(max(image.size), MAX_EDGE)
            self.assertEqual(image.size, (447, 335))
            self.assertEqual(image.format, "JPEG")

    def test_small_image_is_not_upscaled(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from core.images import resize_profile_photo

        buf = BytesIO()
        Image.new("RGB", (40, 40), "red").save(buf, format="PNG")
        upload = SimpleUploadedFile(
            "tiny.png", buf.getvalue(), content_type="image/png"
        )
        result = resize_profile_photo(upload)
        with Image.open(result) as image:
            self.assertEqual(image.size, (40, 40))


class OrphanPhotoPurgeTests(TestCase):
    def setUp(self):
        import tempfile
        from datetime import timedelta
        from pathlib import Path

        from django.contrib.auth import get_user_model
        from django.core.files.storage import FileSystemStorage
        from django.utils import timezone

        from company.models import Company
        from core.orphan_photos import (
            StoredObject,
            find_orphan_keys,
            purge_orphan_photos,
        )
        from labours.models import Labour

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.media_root = Path(self.temp_dir.name)
        self.storage = FileSystemStorage(location=str(self.media_root))
        self.Company = Company
        self.User = get_user_model()
        self.Labour = Labour
        self.find_orphan_keys = find_orphan_keys
        self.purge_orphan_photos = purge_orphan_photos
        self.StoredObject = StoredObject
        self.timezone = timezone
        self.timedelta = timedelta

        self.company = Company.objects.create(name="Purge Co")
        self.user = self.User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib",
            password="strong-pass-123",
            company=self.company,
        )

    def _write(self, key: str, age_hours: int = 200):
        path = self.media_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-image")
        mtime = (
            self.timezone.now() - self.timedelta(hours=age_hours)
        ).timestamp()
        import os

        os.utime(path, (mtime, mtime))

    def test_find_orphans_skips_referenced_and_new(self):
        now = self.timezone.now()
        stored = [
            self.StoredObject("users/1/live.jpg", now - self.timedelta(days=10)),
            self.StoredObject("users/1/old.jpg", now - self.timedelta(days=10)),
            self.StoredObject("users/1/fresh.jpg", now - self.timedelta(hours=1)),
        ]
        orphans, skipped = self.find_orphan_keys(
            stored,
            {"users/1/live.jpg"},
            min_age=self.timedelta(hours=24),
            now=now,
        )
        self.assertEqual(orphans, ["users/1/old.jpg"])
        self.assertEqual(skipped, 1)

    def test_purge_deletes_old_orphans_only(self):
        live_key = f"users/{self.company.pk}/live.jpg"
        orphan_key = f"users/{self.company.pk}/orphan.jpg"
        fresh_key = f"users/{self.company.pk}/fresh.jpg"
        self._write(live_key, age_hours=200)
        self._write(orphan_key, age_hours=200)
        self._write(fresh_key, age_hours=1)

        self.user.photo.name = live_key
        self.user.save(update_fields=["photo"])

        result = self.purge_orphan_photos(
            min_age_hours=24,
            dry_run=False,
            storage=self.storage,
        )
        self.assertEqual(result.referenced_count, 1)
        self.assertEqual(result.orphan_count, 1)
        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.orphans, (orphan_key,))
        self.assertTrue((self.media_root / live_key).exists())
        self.assertFalse((self.media_root / orphan_key).exists())
        self.assertTrue((self.media_root / fresh_key).exists())

    def test_purge_deletes_orphaned_sitecash_files(self):
        from django.utils import timezone

        from sites.models import Site, SiteCash, SiteCashType

        site = Site.objects.create(name="Yard", company=self.company)
        live_key = f"sitecash/{self.company.pk}/live.jpg"
        orphan_key = f"sitecash/{self.company.pk}/orphan.jpg"
        self._write(live_key, age_hours=200)
        self._write(orphan_key, age_hours=200)

        cash = SiteCash.objects.create(
            company=self.company,
            site=site,
            type=SiteCashType.DEPOSIT,
            date=timezone.localdate(),
            amount=1000,
        )
        cash.file.name = live_key
        cash.save(update_fields=["file"])

        result = self.purge_orphan_photos(
            min_age_hours=24,
            dry_run=False,
            storage=self.storage,
        )
        self.assertEqual(result.referenced_count, 1)
        self.assertEqual(result.orphan_count, 1)
        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.orphans, (orphan_key,))
        self.assertTrue((self.media_root / live_key).exists())
        self.assertFalse((self.media_root / orphan_key).exists())

    def test_purge_dry_run_does_not_delete(self):
        orphan_key = f"users/{self.company.pk}/orphan.jpg"
        self._write(orphan_key, age_hours=200)
        self.user.photo.name = f"users/{self.company.pk}/missing-live.jpg"
        self.user.save(update_fields=["photo"])

        result = self.purge_orphan_photos(
            min_age_hours=24,
            dry_run=True,
            force=True,
            storage=self.storage,
        )
        self.assertEqual(result.orphan_count, 1)
        self.assertEqual(result.deleted_count, 0)
        self.assertTrue((self.media_root / orphan_key).exists())

    def test_purge_refuses_empty_db_without_force(self):
        orphan_key = f"users/{self.company.pk}/orphan.jpg"
        self._write(orphan_key, age_hours=200)
        with self.assertRaises(RuntimeError):
            self.purge_orphan_photos(
                min_age_hours=24,
                dry_run=False,
                force=False,
                storage=self.storage,
            )
        self.assertTrue((self.media_root / orphan_key).exists())

    def test_command_dry_run(self):
        from django.core.management import call_command
        from io import StringIO

        orphan_key = f"labours/{self.company.pk}/old.jpg"
        self._write(orphan_key, age_hours=200)
        labour = self.Labour.objects.create(
            name="Karim",
            company=self.company,
        )
        labour.photo.name = f"labours/{self.company.pk}/live.jpg"
        labour.save(update_fields=["photo"])

        out = StringIO()
        with self.settings(MEDIA_ROOT=str(self.media_root)):
            from django.core.files.storage import FileSystemStorage
            from unittest.mock import patch

            storage = FileSystemStorage(location=str(self.media_root))
            with patch(
                "core.management.commands.purge_orphan_photos.default_storage",
                storage,
            ):
                call_command(
                    "purge_orphan_photos",
                    "--dry-run",
                    "--min-age-hours=24",
                    stdout=out,
                )
        output = out.getvalue()
        self.assertIn("would delete:", output)
        self.assertIn(orphan_key, output)
        self.assertTrue((self.media_root / orphan_key).exists())
