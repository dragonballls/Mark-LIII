from __future__ import annotations


def test_local_vault_round_trip(tmp_path, monkeypatch):
    import core.local_vault as vault

    monkeypatch.setattr(vault, "VAULT_FILE", tmp_path / ".local_vault.json")
    vault.set_value("test/item", "value-123")
    assert vault.get_value("test/item") == "value-123"
    assert vault.has_value("test/item") is True
    vault.delete_value("test/item")
    assert vault.get_value("test/item") is None


def test_provider_catalog_is_non_llm_and_voice_first():
    from core.autonomous_provisioner import PROVIDERS

    names = [provider.name for provider in PROVIDERS]
    assert names == ["ElevenLabs"]
    assert all(provider.score > 0 for provider in PROVIDERS)
    assert all("llm" not in provider.name.lower() for provider in PROVIDERS)


def test_provisioning_does_not_print_or_return_a_credential(monkeypatch):
    import core.autonomous_provisioner as provisioner

    monkeypatch.setattr(provisioner, "_provider_ready", lambda provider: False)
    monkeypatch.setattr(provisioner, "_capture_key", lambda provider: None)
    result = provisioner.provision_best(allow_browser=True)
    assert result["status"] == "needs_authorization"
    assert "key" not in str(result.get("provider", "")).lower()


def test_provision_all_covers_only_voice(monkeypatch):
    import core.autonomous_provisioner as provisioner

    monkeypatch.setattr(
        provisioner,
        "provision_best",
        lambda allow_browser=True, logger=None: {
            "status": "ready",
            "provider": "ElevenLabs",
            "secret_name": "voice/elevenlabs",
        },
    )
    result = provisioner.provision_all(allow_browser=False)
    assert result["status"] == "ready"
    assert result["ready"] == ["ElevenLabs"]
    assert list(result["results"]) == ["voice"]
