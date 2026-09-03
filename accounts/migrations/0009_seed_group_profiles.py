from django.db import migrations

def seed_group_profiles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    GroupProfile = apps.get_model("accounts", "GroupProfile")
    for group in Group.objects.all().iterator():
        GroupProfile.objects.create(group=group)


def unseed_group_profiles(apps, schema_editor):
    GroupProfile = apps.get_model("accounts", "GroupProfile")
    GroupProfile.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_groupprofile"),
    ]

    operations = [
        migrations.RunPython(seed_group_profiles, unseed_group_profiles),
    ]
