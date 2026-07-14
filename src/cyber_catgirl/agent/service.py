import json

from cyber_catgirl.agent.client import LLMPort
from cyber_catgirl.agent.prompts import CATGIRL_SYSTEM_PROMPT
from cyber_catgirl.schemas import ActionType, AgentDecision, InteractionEvent, RiskLevel
from cyber_catgirl.services.memory import MemoryContext


class CatgirlAgent:
    def __init__(self, llm: LLMPort) -> None:
        self.llm = llm

    async def decide(
        self, event: InteractionEvent, context: MemoryContext
    ) -> AgentDecision:
        user_payload = {
            "event": event.model_dump(mode="json"),
            "recent_messages": context.recent_messages,
            "relevant_memories": context.long_term,
        }
        messages = [
            {"role": "system", "content": CATGIRL_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        try:
            raw = await self.llm.generate_json(messages, AgentDecision.model_json_schema())
            return AgentDecision.model_validate(raw)
        except Exception:
            return AgentDecision(
                action=ActionType.ESCALATE,
                content="",
                risk_level=RiskLevel.HIGH,
                reason="模型输出无效或调用失败",
                memory_updates=[],
                requires_human_review=True,
            )
