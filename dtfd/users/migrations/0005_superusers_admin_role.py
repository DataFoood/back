from django.db import migrations


def forwards(apps, schema_editor):
    # createsuperuser criava role=customer: o front decide o painel pelo role
    apps.get_model("users", "User").objects.filter(is_superuser=True).update(role="admin", is_staff=True)


class Migration(migrations.Migration):
    dependencies = [("users", "0004_remove_user_level")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
