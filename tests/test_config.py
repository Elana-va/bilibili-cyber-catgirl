from cyber_catgirl.config import RunMode, Settings


def test_settings_defaults_are_conservative(monkeypatch):
    monkeypatch.delenv("CATGIRL_RUN_MODE", raising=False)
    monkeypatch.delenv("CATGIRL_KILL_SWITCH", raising=False)
    monkeypatch.delenv("CATGIRL_POLL_SECONDS", raising=False)

    settings = Settings.from_env()

    assert settings.run_mode is RunMode.MANUAL_ONLY
    assert settings.kill_switch is False
    assert settings.poll_seconds == 60
