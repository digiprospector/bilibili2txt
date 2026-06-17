from __future__ import annotations

import logging
from pathlib import Path

from bilibili2txt.config import load_config
from bilibili2txt.services.ai import AIService


def test_ai_service_filters_disabled_providers(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "ai:",
                "  selected: provider1",
                "  providers:",
                "    - name: provider1",
                "      enable: false",
                "      api_key: key1",
                "      base_url: https://api.openai.com/v1",
                "    - name: provider2",
                "      enable: true",
                "      api_key: key2",
                "    - name: provider3",
                "      api_key: key3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(cfg_file)
    logger = logging.getLogger("test")
    service = AIService(config, logger)

    providers = service.providers()

    # provider1 should be excluded because it has enable: false
    # provider2 and provider3 should be kept
    assert len(providers) == 2
    names = [p.get("name") for p in providers]
    assert "provider1" not in names
    assert "provider2" in names
    assert "provider3" in names

    # selected_provider should fall back to the first enabled provider (provider2)
    # since provider1 is disabled
    selected = service.selected_provider()
    assert selected is not None
    assert selected.get("name") == "provider2"


def test_ai_service_test_and_filter_providers(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "ai:",
                "  selected: provider2",
                "  providers:",
                "    - name: provider2",
                "      api_key: key2",
                "    - name: provider3",
                "      api_key: key3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(cfg_file)
    logger = logging.getLogger("test")
    service = AIService(config, logger)

    # Mock test_provider: provider2 passes, provider3 fails
    def mock_test_provider(provider):
        name = provider.get("name")
        if name == "provider2":
            return True, "passed"
        return False, "failed"

    monkeypatch.setattr(service, "test_provider", mock_test_provider)

    service.test_and_filter_providers()

    # After testing and filtering, only provider2 should remain
    providers = service.providers()
    assert len(providers) == 1
    assert providers[0].get("name") == "provider2"

    selected = service.selected_provider()
    assert selected is not None
    assert selected.get("name") == "provider2"
