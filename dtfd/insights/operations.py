"""Snapshot opcional do contêiner da API; ausência não significa recurso livre."""
from pathlib import Path
from time import monotonic

_last_cpu = None


def resource_snapshot():
    global _last_cpu
    try:
        root = Path('/sys/fs/cgroup')
        used = int((root/'memory.current').read_text())
        memory_max = (root/'memory.max').read_text().strip()
        quota, period = (root/'cpu.max').read_text().split()
        stats = dict(line.split() for line in (root/'cpu.stat').read_text().splitlines())
        usage = int(stats['usage_usec'])
        cores = int(quota)/int(period) if quota != 'max' else None
        now = monotonic()
        utilization = None
        if cores and _last_cpu and now > _last_cpu[0]:
            utilization = max(0, (usage-_last_cpu[1])/((now-_last_cpu[0])*1_000_000*cores))
        _last_cpu = (now, usage)
        return {'available': True, 'scope': 'api_container', 'memory_used_bytes': used,
                'memory_limit_bytes': int(memory_max) if memory_max != 'max' else None,
                'cpu_limit_cores': cores, 'cpu_fraction_since_previous_observation': utilization}
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return {'available': False, 'scope': 'api_container'}
