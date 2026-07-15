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
    assert settings.comment_monitor_enabled is False
    assert settings.comment_auto_reply_enabled is False
    assert settings.comment_backfill_days == 30
    assert settings.comment_backfill_limit == 500
    assert settings.auto_reply_user_daily_limit == 10
    assert settings.auto_reply_account_hourly_limit == 60
    assert settings.auto_reply_account_daily_limit == 300
    assert settings.auto_reply_min_delay_seconds == 8
    assert settings.auto_reply_max_delay_seconds == 20


def test_allowlist_is_parsed_from_comma_separated_actor_ids(monkeypatch):
    monkeypatch.setenv("CATGIRL_AUTO_REPLY_ALLOWLIST", " 1001,1002,1001 ")

    settings = Settings.from_env()

    assert settings.auto_reply_allowlist == {"1001", "1002"}
