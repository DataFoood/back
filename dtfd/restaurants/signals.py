from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .models import Restaurant, RestaurantItem

# Campos que entram no documento de embedding. Mudou um deles -> reindexar.
DOC_FIELDS = {"name", "description"}


def _mark_stale(restaurant_pk):
    Restaurant.objects.filter(pk=restaurant_pk).update(embedding_stale=True)


@receiver(post_save, sender=Restaurant)
def restaurant_saved(sender, instance, update_fields=None, **kwargs):
    # Saves parciais sem campo de documento (ex: recalc_rating, flag) nao reindexam.
    if update_fields is not None and not (set(update_fields) & DOC_FIELDS):
        return
    _mark_stale(instance.pk)


@receiver(m2m_changed)
def restaurant_m2m_changed(sender, instance, action, **kwargs):
    if action in ("post_add", "post_remove", "post_clear") and isinstance(instance, Restaurant):
        _mark_stale(instance.pk)


@receiver(post_save, sender=RestaurantItem)
@receiver(post_delete, sender=RestaurantItem)
def item_changed(sender, instance, **kwargs):
    _mark_stale(instance.restaurant.pk)
