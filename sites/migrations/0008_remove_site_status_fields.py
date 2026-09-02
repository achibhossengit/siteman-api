from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0007_sitecash_file"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="site",
            name="is_active",
        ),
        migrations.RemoveField(
            model_name="site",
            name="is_closed",
        ),
        migrations.RemoveField(
            model_name="site",
            name="closed_at",
        ),
    ]
