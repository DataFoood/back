from pathlib import Path

import yaml


def test_small_stack_reserves_memory_for_the_host_and_uses_prebuilt_images():
    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.small.yml").read_text())
    services = compose["services"]
    # A one-off model pull must not exhaust the host even while apps start.
    maximum_mib = sum(int(service["mem_limit"].removesuffix("m")) for service in services.values())
    assert maximum_mib <= 1824
    assert all("build" not in service for service in services.values())
    assert all(not service.get("ports") for name, service in services.items() if name != "caddy")
    assert {"worker", "beat", "ollama", "shinzou"} <= services.keys()
    assert services["worker"]["depends_on"]["web"]["condition"] == "service_healthy"
