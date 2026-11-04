from celery import shared_task
from django.core.management import call_command


@shared_task
def refresh_insights():
    call_command('refresh_insights')
