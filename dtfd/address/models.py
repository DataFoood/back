from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils import AbstractAudit


class Address(AbstractAudit):
    """Endereço polimórfico: liga a qualquer entidade (User, Restaurant, ...)
    via GenericForeignKey. `entity_type` = content_type."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    entity = GenericForeignKey("content_type", "object_id")

    label = models.CharField(max_length=50, blank=True)  # casa, trabalho...
    street = models.CharField(max_length=255)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=100, blank=True)
    neighborhood = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default="Brasil")
    zipcode = models.CharField(max_length=20)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    geocoded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.street}, {self.number} - {self.city}/{self.state}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            # so um endereco default por entidade: desmarca os irmaos
            Address.objects.filter(
                content_type=self.content_type, object_id=self.object_id, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
