import json

import httpx
from pydantic import ValidationError

from cyber_catgirl.agent.client import LLMPort
from cyber_catgirl.agent.prompts import CATGIRL_SYSTEM_PROMPT
from cyber_catgirl.schemas import AgentDecision, InteractionEvent
from cyber_catgirl.services.memory import MemoryContext


class AgentGenerationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CatgirlAgent:
    def __init__(self, llm: LLMPort) -> None:
        self.llm = llm

    async def decide(
        self, event: InteractionEvent, context: MemoryContext
    ) -> AgentDecision:
        messages = [
            {"role": "system", "content": CATGIRL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    self._public_payload(event, context), ensure_ascii=False
                ),
            },
        ]
        try:
            raw = await self.llm.generate_json(
                messages, AgentDecision.model_json_schema()
            )
            return AgentDecision.model_validate(raw)
        except httpx.TimeoutException as exc:
            raise AgentGenerationError("deepseek_timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise AgentGenerationError(self._http_error_code(exc.response.status_code)) from exc
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise AgentGenerationError("invalid_model_output") from exc
        except AgentGenerationError:
            raise
        except Exception as exc:
            raise AgentGenerationError("deepseek_unavailable") from exc

    @staticmethod
    def _public_payload(event: InteractionEvent, context: MemoryContext) -> dict:
        return {
            "public_comment": {
                "author": event.actor_name,
                "content": event.content,
            },
            "source": {"type": event.target_type},
            "thread_context": context.recent_messages,
            "relevant_memories": context.long_term,
        }

    @staticmethod
    def _http_error_code(status_code: int) -> str:
        if status_code == 401:
            return "deepseek_unauthorized"
        if status_code == 402:
            return "deepseek_balance_required"
        if status_code == 429:
            return "deepseek_rate_limited"
        if status_code >= 500:
            return "deepseek_unavailable"
        return "deepseek_request_failed"
