from __future__ import annotations


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
    assert names == ["OpenRouter", "Groq", "Google Gemini", "ElevenLabs"]
    assert all(provider.score > 0 for provider in PROVIDERS)
    assert {provider.capability for provider in PROVIDERS} == {"llm", "voice"}


def test_provisioning_does_not_print_or_return_a_credential(monkeypatch):
    import core.autonomous_provisioner as provisioner

    monkeypatch.setattr(provisioner, "_existing_provider", lambda capability=None: None)
    monkeypatch.setattr(provisioner, "_capture_key", lambda provider: None)
    result = provisioner.provision_best(allow_browser=True, capability="llm")
    assert result["status"] == "needs_authorization"
    assert "key" not in str(result.get("provider", "")).lower()


def test_provision_all_covers_both_capabilities(monkeypatch):
    import core.autonomous_provisioner as provisioner

    monkeypatch.setattr(
        provisioner,
        "provision_best",
        lambda allow_browser=True, capability="llm", logger=None: {
            "status": "ready",
            "provider": "Test " + capability,
            "secret_name": capability,
        },
    )
    result = provisioner.provision_all(allow_browser=False)
    assert result["status"] == "ready"
    assert result["ready"] == ["Test llm", "Test voice"]
