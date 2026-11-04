from datetime import timedelta
from uuid import uuid4

from django.core import signing
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from promotions.models import Promotion
from restaurants.models import Restaurant
from users.models import User
from .models import AnalyticsEvent, PromotionRedemption


class InsightsTest(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(email='owner@insights.test', name='Owner', password='Test12345', role='owner')
        self.customer = User.objects.create_user(email='customer@insights.test', name='Customer', password='Test12345')
        self.r = Restaurant.objects.create(name='Insights', slug='insights', owner=self.owner)
        self.p = Promotion.objects.create(restaurant=self.r, title='Oferta', message='Teste', coupon_code='CUPOM', status='sent')
        self.client = APIClient()
        self.events = '/api/insights/events/'
        self.report = f'/api/restaurants/{self.r.pk}/analytics/'
        self.redeem = f'/api/restaurants/{self.r.pk}/redemptions/'

    def test_events_are_deduplicated_without_personal_fields(self):
        payload = dict(id=str(uuid4()), restaurant=self.r.pk, kind='detail_view')
        self.assertEqual(202, self.client.post(self.events, payload, format='json').status_code)
        self.client.post(self.events, payload, format='json')
        self.assertEqual(1, AnalyticsEvent.objects.count())
        self.assertNotIn('user', [f.name for f in AnalyticsEvent._meta.fields])
        self.assertNotIn('ip', [f.name for f in AnalyticsEvent._meta.fields])

    def test_owner_navigation_is_not_counted(self):
        self.client.force_authenticate(self.owner)
        self.client.post(self.events, dict(id=str(uuid4()), restaurant=self.r.pk, kind='detail_view'), format='json')
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_attribution_cannot_be_forged_or_cross_restaurant(self):
        payload = dict(id=str(uuid4()), restaurant=self.r.pk, kind='contact_click', attribution='forged')
        self.assertEqual(400, self.client.post(self.events, payload, format='json').status_code)
        token = signing.dumps({'promotion': self.p.pk, 'channel': 'email'}, salt='campaign-attribution')
        payload['attribution'] = token
        self.assertEqual(202, self.client.post(self.events, payload, format='json').status_code)
        self.assertEqual('email', AnalyticsEvent.objects.get().channel)
        other = Restaurant.objects.create(name='Other', slug='other')
        payload.update(id=str(uuid4()), restaurant=other.pk)
        self.assertEqual(400, self.client.post(self.events, payload, format='json').status_code)

    def test_customer_cannot_confirm_redemption_or_read_bi(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(403, self.client.get(self.report).status_code)
        self.assertEqual(403, self.client.post(self.redeem, dict(promotion=self.p.pk, reference='receipt-1'), format='json').status_code)

    def test_redemption_is_idempotent_and_preserves_original_amount(self):
        self.client.force_authenticate(self.owner)
        payload = dict(promotion=self.p.pk, reference='receipt-1', amount='45.00')
        self.assertEqual(201, self.client.post(self.redeem, payload, format='json').status_code)
        self.assertEqual(200, self.client.post(self.redeem, payload, format='json').status_code)
        payload['amount'] = '500.00'
        self.assertEqual(409, self.client.post(self.redeem, payload, format='json').status_code)
        self.assertEqual(1, PromotionRedemption.objects.count())
        self.assertEqual('45.00', str(PromotionRedemption.objects.get().amount))

    def test_report_period_and_previous_period_do_not_mix(self):
        now = timezone.now()
        current = AnalyticsEvent.objects.create(restaurant=self.r, kind='detail_view')
        previous = AnalyticsEvent.objects.create(restaurant=self.r, kind='contact_click')
        old = AnalyticsEvent.objects.create(restaurant=self.r, kind='menu_click')
        AnalyticsEvent.objects.filter(pk=previous.pk).update(created_at=now-timedelta(days=9))
        AnalyticsEvent.objects.filter(pk=old.pk).update(created_at=now-timedelta(days=20))
        self.client.force_authenticate(self.owner)
        data = self.client.get(self.report, {'days': 7}).json()
        self.assertEqual(1, data['totals']['detail_view'])
        self.assertEqual(0, data['totals']['contact_click'])
        self.assertEqual(1, data['previous']['contact_click'])
        self.assertEqual(0, data['totals']['menu_click'])
        self.assertTrue(data['comparison_available'])
        self.assertIsNone(data['redemption_value'])
        self.assertEqual(400, self.client.get(self.report, {'days': 3}).status_code)
        csv = self.client.get(self.report, {'days': 7, 'export': 'csv'})
        self.assertEqual(200, csv.status_code)
        self.assertIn('text/csv', csv['Content-Type'])

    def test_query_count_does_not_grow_per_campaign(self):
        Promotion.objects.bulk_create(Promotion(restaurant=self.r, title=str(i), message='Teste') for i in range(15))
        self.client.force_authenticate(self.owner)
        with self.assertNumQueries(12):
            response = self.client.get(self.report)
        self.assertEqual(200, response.status_code)

    def test_aggregation_is_repeatable_and_applies_retention(self):
        from django.core.management import call_command
        from io import StringIO
        from .models import AnalyticsDaily
        event = AnalyticsEvent.objects.create(restaurant=self.r, kind='detail_view')
        old = AnalyticsEvent.objects.create(restaurant=self.r, kind='contact_click')
        AnalyticsEvent.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=181))
        call_command('refresh_insights', stdout=StringIO())
        call_command('refresh_insights', stdout=StringIO())
        self.assertEqual(1, AnalyticsDaily.objects.count())
        self.assertEqual(1, AnalyticsDaily.objects.get().count)
        self.assertFalse(AnalyticsEvent.objects.filter(pk=old.pk).exists())
