from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.views import COMPANY_ADMIN_GROUP
from company.models import Company, CompanyConfig


class CompanyAdminAddTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            phone_number="+8801700000001",
            name="Staff",
            password="pass-12345",
        )
        self.client.force_login(self.staff)
        self.add_url = reverse("admin:company_company_add")

    def test_add_page_shows_onboarding_fields_only(self):
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Company name")
        self.assertContains(response, "Admin name")
        self.assertContains(response, "Admin phone")
        self.assertContains(response, 'name="password"')
        self.assertNotContains(response, 'id="id_is_active"')
        self.assertNotContains(response, 'id="id_site_limit"')
        self.assertNotContains(response, 'id="id_paid_until"')

    def test_save_creates_company_and_company_admin(self):
        response = self.client.post(
            self.add_url,
            {
                "name": "New Builders",
                "admin_name": "Owner",
                "admin_phone": "01712345678",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, 302)

        company = Company.objects.get(name="New Builders")
        user = User.objects.get(phone_number="+8801712345678")
        self.assertEqual(user.company, company)
        self.assertEqual(user.name, "Owner")
        self.assertTrue(user.is_companyadmin)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password("strong-pass-123"))
        self.assertTrue(user.groups.filter(name=COMPANY_ADMIN_GROUP).exists())
        self.assertTrue(CompanyConfig.objects.filter(company=company).exists())

    def test_duplicate_phone_does_not_create_company(self):
        User.objects.create_user(
            phone_number="+8801712345678",
            name="Existing",
            password="pass-12345",
        )
        response = self.client.post(
            self.add_url,
            {
                "name": "Dup Co",
                "admin_name": "Owner",
                "admin_phone": "01712345678",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Company.objects.filter(name="Dup Co").exists())
        self.assertContains(response, "already registered")


class CompanyAdminChangeTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            phone_number="+8801700000001",
            name="Staff",
            password="pass-12345",
        )
        self.client.force_login(self.staff)
        self.company = Company.objects.create(name="Acme Builders")
        self.change_url = reverse(
            "admin:company_company_change", args=[self.company.pk]
        )

    def test_users_are_a_read_only_list_linking_to_detail(self):
        user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Site Incharge",
            password="pass-12345",
            company=self.company,
        )
        detail_url = reverse("admin:accounts_user_change", args=[user.pk])

        response = self.client.get(self.change_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site Incharge")
        self.assertContains(response, f'href="{detail_url}"')
        self.assertContains(response, "+8801712345678")
        self.assertContains(response, 'name="users-MAX_NUM_FORMS" value="0"')
        self.assertNotContains(response, 'id="users-empty"')
        self.assertNotContains(response, 'name="users-0-phone_number"')
        self.assertNotContains(response, 'name="users-0-name"')
