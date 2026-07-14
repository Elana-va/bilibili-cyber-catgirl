from pathlib import Path

from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app


def make_client():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    return TestClient(create_app(Settings(), session_factory=sessions))


def test_dashboard_has_navigation_safety_controls_and_real_counts():
    response = make_client().get("/")

    assert 'aria-label="主导航"' in response.text
    assert 'data-action="kill-switch"' in response.text
    assert 'href="/reviews"' in response.text
    assert 'data-metric="pending-reviews"' in response.text
    assert "catgirl-mascot.png" in response.text


def test_html_has_no_inline_credential_values(monkeypatch):
    monkeypatch.setenv("BILI_SESSDATA", "secret-cookie-value")

    assert "secret-cookie-value" not in make_client().get("/").text


def test_mascot_is_a_project_bound_png_asset():
    path = Path("src/cyber_catgirl/web/static/catgirl-mascot.png")

    assert path.is_file()
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

