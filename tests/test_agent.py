from datetime import datetime, timezone

from cyber_catgirl.agent.service import CatgirlAgent
from cyber_catgirl.schemas import ActionType, InteractionEvent
from cyber_catgirl.services.memory import MemoryContext


class FakeLLM:
    def __init__(self, output: dict):
        self.output = output
        self.messages = []

    async def generate_json(self, messages: list[dict], schema: dict) -> dict:
        self.messages = messages
        return self.output


def make_event() -> InteractionEvent:
    return InteractionEvent(
        event_id="comment_1",
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="dynamic",
        target_id="d1",
        platform_created_at=datetime.now(timezone.utc),
    )


async def test_invalid_llm_output_escalates():
    agent = CatgirlAgent(FakeLLM({"action": "run_shell", "content": "x"}))

    decision = await agent.decide(make_event(), MemoryContext())

    assert decision.action is ActionType.ESCALATE
    assert decision.requires_human_review is True


async def test_valid_low_risk_reply_is_preserved():
    agent = CatgirlAgent(
        FakeLLM(
            {
                "action": "reply",
                "content": "你好呀，今天也要开心喵～",
                "risk_level": "low",
                "reason": "普通问候",
                "memory_updates": [],
                "requires_human_review": False,
            }
        )
    )

    decision = await agent.decide(make_event(), MemoryContext())

    assert decision.action is ActionType.REPLY
    assert decision.content.endswith("喵～")
