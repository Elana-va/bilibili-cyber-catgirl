from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app


def test_all_admin_pages_are_registered():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    client = TestClient(create_app(Settings(), session_factory=sessions))

    for path in ["/", "/reviews", "/content", "/analytics", "/logs", "/settings"]:
        response = client.get(path)
        assert response.status_code == 200, path

