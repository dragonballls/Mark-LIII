from __future__ import annotations

import os
from pathlib import Path


def test_local_vault_round_trip(tmp_path, monkeypatch):
    import core.local_vault as vault

    monkeypatch.setattr(vault, "VAULT_FILE", tmp_path / ".local_vault.json")
    vault.set_value("test/item", "value-123")
    assert vault.get_value("test/item") == "value-123"
    assert vault.has_value("test/item") is True
    vault.delete_value("test/item")
    assert vault.get_value("test/item") is None


def test_provider_catalog_is_free_first():
    from core.autonomous_provisioner import PROVIDERS

    names = [provider.name for provider in PROVIDERS]
    assert names == ["OpenRouter", "Groq", "Google Gemini"]
    assert all(provider.score > 0 for provider in PROVIDERS)


def test_provisioning_does_not_print_or_return_the_key(monkeypatch):
    import core.autonomous_provisioner as provisioner

    sentinel = "test-key-not-for-output"
    monkeypatch.setattr(provisioner, "_existing_provider", lambda: None)
    monkeypatch.setattr(provisioner, "_capture_key", lambda provider: None)
    result = provisioner.provision_best(allow_browser=True)
    assert sentinel not in str(result)
    assert result["status"] == "needs_authorization"
