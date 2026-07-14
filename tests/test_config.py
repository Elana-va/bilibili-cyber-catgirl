from cyber_catgirl.config import RunMode, Settings


def test_settings_defaults_are_conservative(monkeypatch):
    monkeypatch.delenv("CATGIRL_RUN_MODE", raising=False)
    monkeypatch.delenv("CATGIRL_KILL_SWITCH", raising=False)
    monkeypatch.delenv("CATGIRL_POLL_SECONDS", raising=False)
    monkeypatch.delenv("CATGIRL_AUTO_REPLY_ALLOWLIST", raising=False)

    settings = Settings.from_env()

    assert settings.run_mode is RunMode.MANUAL_ONLY
    assert settings.kill_switch is False
    assert settings.poll_seconds == 60
    assert settings.auto_reply_allowlist == set()


def test_allowlist_is_parsed_from_comma_separated_actor_ids(monkeypatch):
    monkeypatch.setenv("CATGIRL_AUTO_REPLY_ALLOWLIST", " 1001,1002,1001 ")

    settings = Settings.from_env()

    assert settings.auto_reply_allowlist == {"1001", "1002"}
