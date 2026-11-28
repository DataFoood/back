"""Subconjunto conservador de opening_hours do OSM; expressões desconhecidas
permanecem na fonte, sem virar um falso 'aberto agora'."""
import re

DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']


def parse_hours(raw):
    if not raw or raw == '24/7':
        # O modelo atual não representa com fidelidade intervalos de 24 horas.
        return {}
    result = {}
    for clause in raw.split(';'):
        match = re.fullmatch(r'\s*((?:Mo|Tu|We|Th|Fr|Sa|Su)(?:[-,](?:Mo|Tu|We|Th|Fr|Sa|Su))*)\s+(off|\d\d:\d\d-\d\d:\d\d(?:,\d\d:\d\d-\d\d:\d\d)*)\s*', clause)
        if not match:
            return {}
        days, times = match.groups()
        intervals = {}
        if times != 'off':
            for i, window in enumerate(times.split(',')):
                start, end = window.split('-')
                if not ('00:00' <= start < end <= '23:59') or any(int(t.split(':')[1]) > 59 or int(t.split(':')[0]) > 23 for t in (start, end)):
                    return {}
                intervals[f'interval_{i}'] = [start + ':00', end + ':00']
        for group in days.split(','):
            bounds = group.split('-')
            first, last = DAYS.index(bounds[0]), DAYS.index(bounds[-1])
            for day in range(first, (last if last >= first else last + 7) + 1):
                result[day % 7] = intervals
    # Dias ausentes não são presumidos fechados; sem semana completa, o
    # calendário bruto ainda aparece no detalhe para confirmação.
    return result if len(result) == 7 else {}
