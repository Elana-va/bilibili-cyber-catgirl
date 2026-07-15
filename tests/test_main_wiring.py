from cyber_catgirl.main import _build_catgirl_agent
from cyber_catgirl.services.style_history import StyleHistoryService


class FakeLlm:
    async def generate_json(self, messages, schema):
        raise AssertionError("generation is not part of this wiring test")


def test_default_catgirl_agent_receives_database_style_history():
    sessions = object()

    agent = _build_catgirl_agent(FakeLlm(), sessions)

    assert isinstance(agent.style_history, StyleHistoryService)
    assert agent.style_history.session_factory is sessions
