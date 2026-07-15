from pathlib import Path
import shutil
import subprocess

import pytest

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


def test_every_page_has_skip_link_landmark_and_dialog():
    client = make_client()
    for path in [
        "/",
        "/comment-monitor",
        "/reviews",
        "/content",
        "/analytics",
        "/logs",
        "/settings",
    ]:
        html = client.get(path).text
        assert 'href="#main-content"' in html
        assert 'id="main-content"' in html
        assert "<dialog" in html
        assert 'aria-live="polite"' in html


def test_styles_include_mobile_and_reduced_motion_contracts():
    css = Path("src/cyber_catgirl/web/static/app.css").read_text("utf-8")

    assert "@media (max-width: 720px)" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ":focus-visible" in css
    assert "[hidden]{display:none!important}" in css
    assert ".deepseek-connect-form{display:grid;grid-template-columns:1fr" in css


def test_settings_contains_accessible_bilibili_login_dialog():
    html = make_client().get("/settings").text

    assert "data-bilibili-connect" in html
    assert 'id="bilibili-login-dialog"' in html
    assert 'aria-labelledby="bilibili-login-title"' in html
    assert 'data-bilibili-account' in html
    assert "/static/bilibili-login.js" in html


def test_settings_contains_secure_deepseek_connection_card():
    html = make_client().get("/settings").text

    assert "data-deepseek-root" in html
    assert 'type="password"' in html
    assert 'autocomplete="new-password"' in html
    assert "data-deepseek-model" in html
    assert 'value="deepseek-v4-flash"' in html
    assert 'value="deepseek-v4-pro"' in html
    assert "data-deepseek-connect" in html
    assert "data-deepseek-verify" in html
    assert "data-deepseek-disconnect" in html
    assert "/static/deepseek-connection.js" in html


def test_javascript_files_have_valid_syntax():
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    )
    node = shutil.which("node") or (str(bundled) if bundled.is_file() else None)
    if node is None:
        pytest.skip("Node.js is unavailable for JavaScript syntax validation")

    for script in [
        "app.js",
        "bilibili-login.js",
        "deepseek-connection.js",
        "comment-monitor.js",
    ]:
        result = subprocess.run(
            [node, "--check", f"src/cyber_catgirl/web/static/{script}"],
            capture_output=True,
            text=False,
            check=False,
        )

        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
