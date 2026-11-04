from datetime import timedelta
from decimal import Decimal

from django.core import signing
from django.db import transaction
from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from promotions.models import Promotion, PromotionDelivery
from promotions.permissions import IsRestaurantManager
from restaurants.models import Restaurant
from .models import AnalyticsEvent, PromotionRedemption


class EventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    restaurant = serializers.IntegerField(min_value=1)
    kind = serializers.ChoiceField(choices=AnalyticsEvent.Kind.choices)
    attribution = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class EventView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'analytics'

    @extend_schema(request=EventSerializer, responses={202: inline_serializer('AnalyticsEventReceipt', {'recorded': serializers.BooleanField()})})
    def post(self, request):
        payload = EventSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        restaurant = get_object_or_404(Restaurant, pk=data['restaurant'])
        if request.user.is_authenticated and (request.user.is_staff or restaurant.owner_id == request.user.pk):
            return Response({'recorded': False}, status=202)
        promotion, channel = None, 'web'
        if data.get('attribution'):
            try:
                attributed = signing.loads(data['attribution'], salt='campaign-attribution', max_age=60 * 86400)
                if not isinstance(attributed, dict) or attributed.get('channel') not in ('email', 'telegram', 'whatsapp', 'shared'):
                    raise signing.BadSignature
                promotion_id = attributed.get('promotion')
                if not isinstance(promotion_id, int) or isinstance(promotion_id, bool):
                    raise signing.BadSignature
                promotion = Promotion.objects.filter(pk=promotion_id, restaurant=restaurant, status__in=['sending', 'sent', 'partial']).first()
                if promotion is None:
                    raise signing.BadSignature
                channel = attributed['channel']
            except (signing.BadSignature, TypeError, ValueError):
                raise serializers.ValidationError({'attribution': 'Referência de campanha inválida.'})
        _, created = AnalyticsEvent.objects.get_or_create(id=data['id'], defaults={
            'restaurant': restaurant, 'kind': data['kind'], 'promotion': promotion, 'channel': channel,
        })
        return Response({'recorded': created}, status=202)


class RedemptionSerializer(serializers.Serializer):
    promotion = serializers.IntegerField(min_value=1)
    reference = serializers.CharField(max_length=100, trim_whitespace=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False, allow_null=True)


class RedemptionView(APIView):
    permission_classes = [IsRestaurantManager]

    @extend_schema(request=RedemptionSerializer, responses={201: inline_serializer('RedemptionReceipt', {'id': serializers.UUIDField(), 'confirmed': serializers.BooleanField(), 'created': serializers.BooleanField()})})
    def post(self, request, restaurant_pk):
        payload = RedemptionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        promotion = get_object_or_404(Promotion, pk=data['promotion'], restaurant_id=restaurant_pk, status__in=['sent', 'partial'])
        if not promotion.coupon_code:
            raise serializers.ValidationError({'promotion': 'Esta campanha não tem cupom.'})
        if promotion.valid_until and promotion.valid_until < timezone.localdate():
            raise serializers.ValidationError({'promotion': 'Cupom expirado.'})
        with transaction.atomic():
            # Mesma ordem de lock de envio. Serializa referência por restaurante.
            Restaurant.objects.select_for_update().get(pk=restaurant_pk)
            redemption, created = PromotionRedemption.objects.get_or_create(
                restaurant_id=restaurant_pk, reference=data['reference'], defaults={
                    'promotion': promotion, 'amount': data.get('amount'), 'confirmed_by': request.user,
                },
            )
        if redemption.promotion_id != promotion.pk or redemption.amount != data.get('amount'):
            return Response({'detail': 'Referência já registrada com outros dados.'}, status=409)
        return Response({'id': str(redemption.pk), 'confirmed': True, 'created': created}, status=201 if created else 200)


def event_counts(qs):
    counts = {key: 0 for key in AnalyticsEvent.Kind.values}
    counts.update({r['kind']: r['n'] for r in qs.values('kind').annotate(n=Count('id'))})
    return counts


def report(restaurant_pk, days):
    end = timezone.now()
    start = end - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    base = AnalyticsEvent.objects.filter(restaurant_id=restaurant_pk)
    current = base.filter(created_at__gte=start, created_at__lt=end)
    previous = base.filter(created_at__gte=previous_start, created_at__lt=start)
    observed_since = base.aggregate(at=Min('created_at'))['at']
    first_day, last_day = timezone.localdate(start), timezone.localdate(end)
    daily = {r['day']: r['n'] for r in current.filter(kind='detail_view').annotate(day=TruncDate('created_at')).values('day').annotate(n=Count('id'))}
    deliveries = PromotionDelivery.objects.filter(promotion__restaurant_id=restaurant_pk, sent_at__gte=start, sent_at__lt=end)
    # Campanhas recentes e totais independentes: sem multiplicar joins.
    campaigns = []
    campaign_events = {}
    for row in current.filter(promotion__isnull=False).values('promotion_id', 'kind').annotate(n=Count('id')):
        campaign_events.setdefault(row['promotion_id'], {})[row['kind']] = row['n']
    redemption_counts = {row['promotion_id']: row['n'] for row in PromotionRedemption.objects.filter(
        restaurant_id=restaurant_pk, created_at__gte=start, created_at__lt=end,
    ).values('promotion_id').annotate(n=Count('id'))}
    accepted = {row['promotion_id']: row['n'] for row in deliveries.filter(status='sent').values('promotion_id').annotate(n=Count('id'))}
    for p in Promotion.all_objects.filter(restaurant_id=restaurant_pk).order_by('-created_at')[:30]:
        counts = {key: 0 for key in AnalyticsEvent.Kind.values}
        counts.update(campaign_events.get(p.pk, {}))
        campaigns.append({'id': p.pk, 'title': p.title, 'coupon_code': p.coupon_code, 'status': p.status,
                          'events': counts, 'redemptions': redemption_counts.get(p.pk, 0),
                          'accepted': accepted.get(p.pk, 0)})
    redemptions = PromotionRedemption.objects.filter(restaurant_id=restaurant_pk, created_at__gte=start, created_at__lt=end)
    values = redemptions.aggregate(total=Sum('amount'), informed=Count('amount'))
    return {
        'window': {'days': days, 'start': start.isoformat(), 'end': end.isoformat()},
        'observed_since': observed_since.isoformat() if observed_since else None,
        'comparison_available': bool(observed_since and observed_since <= previous_start),
        'totals': event_counts(current), 'previous': event_counts(previous),
        'series': [{'date': (first_day + timedelta(days=i)).isoformat(), 'views': daily.get(first_day + timedelta(days=i), 0)} for i in range((last_day-first_day).days+1)],
        'redemptions': redemptions.count(), 'redemption_value': str(values['total']) if values['informed'] else None,
        'redemptions_with_value': values['informed'], 'campaigns': campaigns,
        'notice': 'Eventos observados, não pessoas únicas. Cliques não comprovam vendas. Valores de resgate são informados pelo restaurante.',
    }


class AnalyticsView(APIView):
    permission_classes = [IsRestaurantManager]

    @extend_schema(responses=inline_serializer('RestaurantAnalyticsReport', {
        'window': serializers.DictField(), 'observed_since': serializers.DateTimeField(allow_null=True),
        'comparison_available': serializers.BooleanField(), 'totals': serializers.DictField(),
        'previous': serializers.DictField(), 'series': serializers.ListField(), 'redemptions': serializers.IntegerField(),
        'redemption_value': serializers.CharField(allow_null=True), 'redemptions_with_value': serializers.IntegerField(),
        'campaigns': serializers.ListField(), 'notice': serializers.CharField(),
    }))
    def get(self, request, restaurant_pk):
        try:
            days = int(request.query_params.get('days', '30'))
            if days not in (7, 30, 90):
                raise ValueError
        except (TypeError, ValueError):
            raise serializers.ValidationError({'days': 'Use 7, 30 ou 90 dias.'})
        data = report(restaurant_pk, days)
        if request.query_params.get('export') == 'csv':
            import csv
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="datafood-metrics.csv"'
            writer = csv.writer(response)
            writer.writerow(['Data', 'Aberturas de detalhe'])
            for row in data['series']:
                writer.writerow([row['date'], row['views']])
            return response
        return Response(data)
