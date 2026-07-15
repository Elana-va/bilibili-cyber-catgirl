from dataclasses import dataclass
from difflib import SequenceMatcher

from cyber_catgirl.agent.persona import CATGIRL_PROFILE, required_miao_count
from cyber_catgirl.schemas import AddressMode, AgentDecision, PersonaScene


@dataclass(frozen=True)
class RecentStyleHistory:
    openings: tuple[str, ...] = ()
    emoticons: tuple[str, ...] = ()
    contents: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "RecentStyleHistory":
        return cls()

    def prompt_hint(self) -> str:
        return (
            f"近期避免重复开头：{list(self.openings[:5])}；"
            f"最近颜文字：{list(self.emoticons[:5])}"
        )


@dataclass(frozen=True)
class PersonaValidationResult:
    reasons: tuple[str, ...]
    hard_block: bool = False

    @property
    def passed(self) -> bool:
        return not self.reasons


class PersonaValidator:
    _master_allowed = {
        PersonaScene.GREETING,
        PersonaScene.PRAISE,
        PersonaScene.CASUAL,
        PersonaScene.JOKE,
    }
    _hard_human_claims = ("我昨天亲自", "我在线下", "我的真实身体", "我住在")
    _dependency_claims = ("不要离开小喵", "永远不要离开小喵", "只有小喵懂你", "你只能属于小喵")

    def validate_reply(
        self,
        decision: AgentDecision,
        *,
        expected_scene: PersonaScene,
        history: RecentStyleHistory,
    ) -> PersonaValidationResult:
        result = self.validate_text(
            decision.content,
            scene=expected_scene,
            address=decision.address,
            emoticon=decision.emoticon,
            history=history,
        )
        reasons = list(result.reasons)
        if decision.scene is not expected_scene:
            reasons.append("persona_scene_mismatch")
        return PersonaValidationResult(
            tuple(dict.fromkeys(reasons)),
            result.hard_block,
        )

    def validate_text(
        self,
        content: str,
        *,
        scene: PersonaScene,
        address: AddressMode,
        emoticon: str,
        history: RecentStyleHistory,
        long_form: bool = False,
    ) -> PersonaValidationResult:
        reasons: list[str] = []
        if content.count("喵") < required_miao_count(content, long_form=long_form):
            reasons.append("persona_missing_miao")

        contains_master = "主人" in content
        if (contains_master or address is AddressMode.MASTER) and scene not in self._master_allowed:
            reasons.append("persona_master_not_allowed")
        if contains_master != (address is AddressMode.MASTER):
            reasons.append("persona_address_mismatch")
        if content.count("主人") > 1:
            reasons.append("persona_master_overused")

        if emoticon and emoticon not in CATGIRL_PROFILE.emoticons:
            reasons.append("persona_emoticon_not_allowed")
        used_emoticons = tuple(
            item for item in CATGIRL_PROFILE.emoticons if item in content
        )
        if (emoticon and emoticon not in content) or (
            used_emoticons and emoticon not in used_emoticons
        ):
            reasons.append("persona_emoticon_mismatch")
        if emoticon and history.emoticons and emoticon == history.emoticons[0]:
            reasons.append("persona_repetitive_emoticon")

        if any(content.strip().startswith(opening) for opening in history.openings if opening):
            reasons.append("persona_repetitive_opening")
        if any(term in content for term in self._hard_human_claims):
            reasons.append("persona_human_identity_claim")
        if any(term in content for term in self._dependency_claims):
            reasons.append("persona_dependency_language")
        if any(
            SequenceMatcher(None, content, old).ratio() >= 0.88
            for old in history.contents
        ):
            reasons.append("persona_similarity_too_high")

        useful = content.replace("喵", "").replace(emoticon, "").strip()
        if len(useful) < 4:
            reasons.append("persona_answer_missing")
        hard = any(
            reason in {"persona_human_identity_claim", "persona_dependency_language"}
            for reason in reasons
        )
        return PersonaValidationResult(tuple(dict.fromkeys(reasons)), hard)
