import json
from datetime import datetime, timezone

import pytest

from cyber_catgirl.agent.service import AgentGenerationError, CatgirlAgent
from cyber_catgirl.schemas import ActionType, InteractionEvent
from cyber_catgirl.services.memory import MemoryContext


class FakeLLM:
    def __init__(self, output: dict):
        self.output = output
        self.messages = []

    async def generate_json(self, messages: list[dict], schema: dict) -> dict:
        self.messages = messages
        return self.output


class SequenceLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def generate_json(self, messages, schema):
        self.calls.append((messages, schema))
        return self.outputs.pop(0)


def reply_payload(content, *, scene="greeting", address="partner", emoticon=""):
    return {
        "action": "reply",
        "content": content,
        "risk_level": "low",
        "reason": "测试",
        "memory_updates": [],
        "requires_human_review": True,
        "scene": scene,
        "address": address,
        "emoticon": emoticon,
    }


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


async def test_invalid_llm_output_raises_stable_generation_error():
    agent = CatgirlAgent(FakeLLM({"action": "run_shell", "content": "x"}))

    with pytest.raises(AgentGenerationError) as exc_info:
        await agent.decide(make_event(), MemoryContext())

    assert exc_info.value.code == "invalid_model_output"


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
                "scene": "greeting",
                "address": "partner",
                "emoticon": "",
            }
        )
    )

    decision = await agent.decide(make_event(), MemoryContext())

    assert decision.action is ActionType.REPLY
    assert decision.content.endswith("喵～")


async def test_model_payload_excludes_private_platform_identifiers():
    llm = FakeLLM(
        {
            "action": "reply",
            "content": "小伙伴，已经收到你的消息喵～",
            "risk_level": "low",
            "reason": "普通互动",
            "memory_updates": [],
            "requires_human_review": False,
            "scene": "greeting",
            "address": "partner",
            "emoticon": "",
        }
    )
    agent = CatgirlAgent(llm)
    event = make_event().model_copy(
        update={"actor_id": "secret-mid", "target_id": "secret-oid"}
    )

    await agent.decide(event, MemoryContext(recent_messages=["上一句话"]))

    serialized = json.dumps(llm.messages, ensure_ascii=False)
    assert "你好" in serialized
    assert "上一句话" in serialized
    assert "secret-mid" not in serialized
    assert "secret-oid" not in serialized


async def test_persona_soft_failure_regenerates_once_with_reason():
    llm = SequenceLLM(
        [
            reply_payload("小伙伴你好"),
            reply_payload("小伙伴你好喵～"),
        ]
    )
    agent = CatgirlAgent(llm)

    decision = await agent.decide(make_event(), MemoryContext())

    assert decision.content == "小伙伴你好喵～"
    assert len(llm.calls) == 2
    assert "persona_missing_miao" in llm.calls[1][0][0]["content"]


async def test_persona_hard_failure_does_not_regenerate():
    llm = SequenceLLM(
        [reply_payload("我昨天亲自去了线下店喵，你永远不要离开小喵。")]
    )
    agent = CatgirlAgent(llm)

    with pytest.raises(AgentGenerationError) as exc_info:
        await agent.decide(make_event(), MemoryContext())

    assert exc_info.value.code == "persona_validation_failed"
    assert exc_info.value.candidate is not None
    assert "persona_human_identity_claim" in exc_info.value.reasons
    assert len(llm.calls) == 1


async def test_persona_second_soft_failure_stops_after_two_calls():
    llm = SequenceLLM([reply_payload("你好"), reply_payload("还是你好")])
    agent = CatgirlAgent(llm)

    with pytest.raises(AgentGenerationError) as exc_info:
        await agent.decide(make_event(), MemoryContext())

    assert exc_info.value.code == "persona_validation_failed"
    assert len(llm.calls) == 2


async def test_ignore_decision_skips_external_persona_text_validation():
    llm = SequenceLLM(
        [
            {
                "action": "ignore",
                "content": "",
                "risk_level": "low",
                "reason": "无需公开回复",
                "memory_updates": [],
                "requires_human_review": False,
                "scene": "greeting",
                "address": "none",
                "emoticon": "",
            }
        ]
    )
    agent = CatgirlAgent(llm)

    decision = await agent.decide(make_event(), MemoryContext())

    assert decision.action is ActionType.IGNORE
    assert len(llm.calls) == 1
