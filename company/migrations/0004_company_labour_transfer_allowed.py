from django.db import migrations, models


def copy_labour_transfer_allowed(apps, schema_editor):
    Company = apps.get_model("company", "Company")
    CompanyConfig = apps.get_model("company", "CompanyConfig")
    for cfg in CompanyConfig.objects.all().iterator():
        Company.objects.filter(pk=cfg.company_id).update(
            labour_transfer_allowed=cfg.labour_transfer_allowed,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0003_company_active_labour_limit_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="labour_transfer_allowed",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(
            copy_labour_transfer_allowed,
            migrations.RunPython.noop,
        ),
        migrations.DeleteModel(
            name="CompanyConfig",
        ),
    ]
