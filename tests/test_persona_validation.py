from cyber_catgirl.agent.persona_validation import (
    PersonaValidator,
    RecentStyleHistory,
)
from cyber_catgirl.schemas import AgentDecision, PersonaScene


def decision(content: str, **updates) -> AgentDecision:
    payload = {
        "action": "reply",
        "content": content,
        "risk_level": "low",
        "reason": "测试",
        "requires_human_review": True,
        "scene": "casual",
        "address": "partner",
        "emoticon": "(｡•̀ᴗ-)✧",
    }
    payload.update(updates)
    return AgentDecision.model_validate(payload)


def test_validator_requires_miao_budget_and_real_answer():
    result = PersonaValidator().validate_reply(
        decision("小伙伴你好", emoticon=""),
        expected_scene=PersonaScene.CASUAL,
        history=RecentStyleHistory.empty(),
    )

    assert "persona_missing_miao" in result.reasons


def test_validator_blocks_master_in_technical_scene():
    result = PersonaValidator().validate_reply(
        decision(
            "主人，这个接口需要先检查状态码喵，再检查请求头喵。",
            scene="technical",
            address="master",
            emoticon="",
        ),
        expected_scene=PersonaScene.TECHNICAL,
        history=RecentStyleHistory.empty(),
    )

    assert "persona_master_not_allowed" in result.reasons


def test_validator_cross_checks_declared_address_against_text():
    result = PersonaValidator().validate_reply(
        decision("主人，今天一起研究新东西喵～", address="partner", emoticon=""),
        expected_scene=PersonaScene.CASUAL,
        history=RecentStyleHistory.empty(),
    )

    assert "persona_address_mismatch" in result.reasons


def test_validator_hard_blocks_human_and_dependency_claims():
    result = PersonaValidator().validate_reply(
        decision(
            "我昨天亲自去了线下店喵，你永远不要离开小喵。",
            emoticon="",
        ),
        expected_scene=PersonaScene.CASUAL,
        history=RecentStyleHistory.empty(),
    )

    assert result.hard_block is True
    assert "persona_human_identity_claim" in result.reasons
    assert "persona_dependency_language" in result.reasons


def test_validator_rejects_consecutive_emoticon_and_similar_opening():
    history = RecentStyleHistory(
        openings=("小伙伴，这个问题",),
        emoticons=("(｡•̀ᴗ-)✧",),
        contents=("小伙伴，这个问题先检查接口喵，再检查日志喵。",),
    )
    result = PersonaValidator().validate_reply(
        decision("小伙伴，这个问题先检查接口喵，再看日志喵。(｡•̀ᴗ-)✧"),
        expected_scene=PersonaScene.CASUAL,
        history=history,
    )

    assert "persona_repetitive_emoticon" in result.reasons
    assert "persona_repetitive_opening" in result.reasons


def test_validator_cross_checks_declared_emoticon_against_text():
    result = PersonaValidator().validate_reply(
        decision("小伙伴，今天一起学习喵～", emoticon="(｡•̀ᴗ-)✧"),
        expected_scene=PersonaScene.CASUAL,
        history=RecentStyleHistory.empty(),
    )

    assert "persona_emoticon_mismatch" in result.reasons
