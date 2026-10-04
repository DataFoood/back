from django.db import migrations


def seed(apps, schema_editor):
    RankingWeight = apps.get_model("preferences", "RankingWeight")
    RankingWeight.objects.get_or_create(key="distance", defaults={"weight": 0.5})


def unseed(apps, schema_editor):
    apps.get_model("preferences", "RankingWeight").objects.filter(key="distance").delete()


class Migration(migrations.Migration):
    dependencies = [("preferences", "0004_searchhistory")]
    operations = [migrations.RunPython(seed, unseed)]
