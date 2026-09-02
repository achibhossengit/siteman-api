import company.models
from django.db import migrations, models


def copy_subscription_entitlements(apps, schema_editor):
    Company = apps.get_model("company", "Company")
    Subscription = apps.get_model("subscription", "Subscription")
    for sub in Subscription.objects.all().iterator():
        Company.objects.filter(pk=sub.company_id).update(
            site_limit=sub.site_limit,
            active_user_limit=sub.active_user_limit,
            active_labour_limit=sub.active_labour_limit,
            paid_until=sub.paid_until,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0002_companyconfig"),
        ("subscription", "0003_rename_open_site_limit_site_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="active_labour_limit",
            field=models.IntegerField(
                default=30,
                help_text="Max active labour; -1 means no limit.",
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="active_user_limit",
            field=models.IntegerField(
                default=4,
                help_text="Max active users; -1 means no limit.",
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="paid_until",
            field=models.DateField(
                blank=True,
                default=company.models.default_paid_until,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="site_limit",
            field=models.IntegerField(
                default=2,
                help_text="Max sites; -1 means no limit.",
            ),
        ),
        migrations.RunPython(copy_subscription_entitlements, migrations.RunPython.noop),
    ]
