from cyber_catgirl.agent.persona import (
    CATGIRL_PROFILE,
    required_miao_count,
    route_scene,
)
from cyber_catgirl.agent.prompts import build_persona_system_prompt
from cyber_catgirl.schemas import PersonaScene


def test_profile_contains_confirmed_identity_and_style_rules():
    assert CATGIRL_PROFILE.version == "catgirl-v2"
    assert CATGIRL_PROFILE.default_address == "小伙伴"
    assert CATGIRL_PROFILE.emotional_dependency == 0
    assert "(｡•̀ᴗ-)✧" in CATGIRL_PROFILE.emoticons


def test_scene_router_keeps_serious_and_dangerous_requests_non_playful():
    assert route_scene("账号密码泄露了怎么办") is PersonaScene.SAFETY
    assert route_scene("这个接口为什么返回401") is PersonaScene.TECHNICAL
    assert route_scene("这是怎么接入的") is PersonaScene.TECHNICAL
    assert route_scene("你好，小喵好可爱") is PersonaScene.PRAISE


def test_miao_budget_increases_with_reply_length():
    assert required_miao_count("你好呀") == 1
    assert required_miao_count("这是一段需要认真解释的中等长度回复" * 3) == 2
    assert required_miao_count("这是更长的解释" * 30) == 3
    assert required_miao_count("互动日报" * 40, long_form=True) == 2


def test_shared_prompt_contains_identity_address_and_correction_rules():
    prompt = build_persona_system_prompt(
        task="reply",
        scene=PersonaScene.TECHNICAL,
        history_hint="最近使用过：(≧▽≦)",
        correction_reasons=("persona_missing_miao",),
    )

    assert "catgirl-v2" in prompt
    assert "小伙伴" in prompt
    assert "每条对外内容必须自然包含“喵”" in prompt
    assert "技术讨论" in prompt
    assert "persona_missing_miao" in prompt
    assert "最近使用过：(≧▽≦)" in prompt
