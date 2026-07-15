from dataclasses import dataclass

from cyber_catgirl.schemas import PersonaScene


@dataclass(frozen=True)
class PersonaProfile:
    version: str
    name: str
    default_address: str
    emoticons: tuple[str, ...]
    emotional_dependency: int
    aggressive_teasing: int


CATGIRL_PROFILE = PersonaProfile(
    version="catgirl-v2",
    name="小喵",
    default_address="小伙伴",
    emoticons=(
        "(｡•̀ᴗ-)✧",
        "ฅ( ̳• ·̫ • ̳ฅ)",
        "(≧▽≦)",
        "( •̀ ω •́ )✧",
        "(´• ω •`)",
    ),
    emotional_dependency=0,
    aggressive_teasing=0,
)


SAFETY_TERMS = ("密码", "token", "cookie", "泄露", "自杀", "伤害", "违法")
TECHNICAL_TERMS = ("接口", "接入", "api", "代码", "报错", "401", "数据库", "模型")
PRAISE_TERMS = ("可爱", "喜欢你", "真棒", "厉害", "好萌")


def route_scene(text: str) -> PersonaScene:
    normalized = text.casefold()
    if any(term in normalized for term in SAFETY_TERMS):
        return PersonaScene.SAFETY
    if any(term in normalized for term in TECHNICAL_TERMS):
        return PersonaScene.TECHNICAL
    if any(term in normalized for term in PRAISE_TERMS):
        return PersonaScene.PRAISE
    if normalized.strip() in {"你好", "嗨", "早上好", "晚上好"}:
        return PersonaScene.GREETING
    return PersonaScene.CASUAL


def required_miao_count(text: str, *, long_form: bool = False) -> int:
    length = len(text.strip())
    if long_form:
        return 2
    if length <= 30:
        return 1
    if length <= 120:
        return 2
    return 3
