"""Execute the production shell command without touching a real database."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


@pytest.fixture
def startup(tmp_path):
    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text()
    )
    log = tmp_path / "commands.jsonl"
    for executable in ("python", "gunicorn"):
        stub = tmp_path / executable
        stub.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "name = pathlib.Path(sys.argv[0]).name\n"
            "with open(os.environ['STARTUP_LOG'], 'a') as log:\n"
            "    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
            "if name == 'python' and 'migrate' in sys.argv:\n"
            "    sys.exit(int(os.environ.get('MIGRATE_EXIT', '0')))\n"
        )
        stub.chmod(0o755)

    def run(workers=None, migrate_exit=0):
        env = {
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "STARTUP_LOG": str(log),
            "MIGRATE_EXIT": str(migrate_exit),
        }
        command = [
            part.replace("${WEB_WORKERS:-3}", str(workers or 3))
            for part in compose["services"]["web"]["command"]
        ]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls

    return run


@pytest.mark.parametrize("workers", [None, 7])
def test_startup_passes_all_options_to_gunicorn(startup, workers):
    result, calls = startup(workers=workers)
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["python", "manage.py", "migrate", "--noinput"],
        ["python", "manage.py", "collectstatic", "--noinput"],
        [
            "gunicorn", "dtfd.wsgi:application", "--bind", "0.0.0.0:8000",
            "--workers", str(workers or 3), "--timeout", "90", "--access-logfile", "-",
        ],
    ]


def test_failed_migration_prevents_server_startup(startup):
    result, calls = startup(migrate_exit=42)
    assert result.returncode == 42
    assert calls == [["python", "manage.py", "migrate", "--noinput"]]
