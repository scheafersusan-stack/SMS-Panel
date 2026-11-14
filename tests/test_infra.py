"""Static checks of the compose stack (no Docker here): it parses and wires what the docs say."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())


def test_services_and_dependencies() -> None:
    services = COMPOSE["services"]
    assert set(services) == {"postgres", "redis", "migrate", "api", "worker", "caddy"}
    for name in ("api", "worker"):
        assert (
            services[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
        )
    assert services["migrate"]["command"][-1] == "migrate"
    assert services["worker"]["command"][-1] == "worker"
    published = [name for name, s in services.items() if s.get("ports")]
    assert published == ["caddy"]


def test_trusted_proxies_cover_only_the_compose_network() -> None:
    subnet = COMPOSE["networks"]["edge"]["ipam"]["config"][0]["subnet"]
    env = COMPOSE["x-api-env"]["PAYAMAKYAR_TRUSTED_PROXIES"]
    assert env == "${PAYAMAKYAR_TRUSTED_PROXIES:-" + subnet + "}"
    example = (ROOT / "infra/env/.env.example").read_text()
    assert f"PAYAMAKYAR_TRUSTED_PROXIES={subnet}" in example


def test_caddyfile_security_headers() -> None:
    text = (ROOT / "infra/Caddyfile").read_text()
    for needle in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "strict-origin-when-cross-origin",
        "frame-ancestors 'none'",
        "reverse_proxy api:8000",
        "try_files {path} {path}/ /index.html",
    ):
        assert needle in text, needle
