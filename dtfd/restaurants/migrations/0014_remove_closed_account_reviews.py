from django.db import migrations
from django.db.models import Avg, Count


def remove_closed_account_reviews(apps, schema_editor):
    Review = apps.get_model('restaurants', 'RestaurantReview')
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    alias = schema_editor.connection.alias
    reviews = Review.objects.using(alias).filter(author__deleted_at__isnull=False)
    ids = list(reviews.values_list('restaurant_id', flat=True).distinct())
    reviews.delete()
    for pk in ids:
        totals = Review.objects.using(alias).filter(restaurant_id=pk, deleted_at__isnull=True).aggregate(average=Avg('rating'), count=Count('pk'))
        Restaurant.objects.using(alias).filter(pk=pk).update(average_rating=round(totals['average'] or 0, 2), total_reviews=totals['count'])


class Migration(migrations.Migration):
    dependencies = [('restaurants', '0013_restaurantimage_attribution_restaurantimage_license_and_more')]
    # Conteúdo removido por encerramento de conta não deve ser restaurado.
    operations = [migrations.RunPython(remove_closed_account_reviews, migrations.RunPython.noop)]
