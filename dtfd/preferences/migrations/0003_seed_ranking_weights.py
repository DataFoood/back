from django.db import migrations

WEIGHTS = {"semantic": 1.0, "preference": 0.5, "review": 0.3}


def seed(apps, schema_editor):
    RankingWeight = apps.get_model("preferences", "RankingWeight")
    for key, weight in WEIGHTS.items():
        RankingWeight.objects.get_or_create(key=key, defaults={"weight": weight})


def unseed(apps, schema_editor):
    RankingWeight = apps.get_model("preferences", "RankingWeight")
    RankingWeight.objects.filter(key__in=WEIGHTS).delete()


class Migration(migrations.Migration):
    dependencies = [("preferences", "0002_rankingweight")]
    operations = [migrations.RunPython(seed, unseed)]
