import json

import httpx
from pydantic import ValidationError

from cyber_catgirl.agent.client import LLMPort
from cyber_catgirl.agent.persona import route_scene
from cyber_catgirl.agent.persona_validation import PersonaValidator, RecentStyleHistory
from cyber_catgirl.agent.prompts import build_persona_system_prompt
from cyber_catgirl.schemas import ActionType, AgentDecision, InteractionEvent
from cyber_catgirl.services.memory import MemoryContext


class AgentGenerationError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        reasons: tuple[str, ...] = (),
        candidate: AgentDecision | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.reasons = reasons
        self.candidate = candidate


class CatgirlAgent:
    def __init__(self, llm: LLMPort, style_history=None, validator=None) -> None:
        self.llm = llm
        self.style_history = style_history
        self.validator = validator or PersonaValidator()

    async def decide(
        self, event: InteractionEvent, context: MemoryContext
    ) -> AgentDecision:
        scene = route_scene(event.content)
        history = (
            self.style_history.for_draft_type("reply")
            if self.style_history is not None
            else RecentStyleHistory.empty()
        )
        reasons: tuple[str, ...] = ()
        candidate: AgentDecision | None = None
        for _ in range(2):
            prompt = build_persona_system_prompt(
                task="reply",
                scene=scene,
                history_hint=history.prompt_hint(),
                correction_reasons=reasons,
            )
            candidate = await self._generate(prompt, event, context)
            if candidate.action is not ActionType.REPLY:
                return candidate
            result = self.validator.validate_reply(
                candidate,
                expected_scene=scene,
                history=history,
            )
            if result.passed:
                return candidate
            reasons = result.reasons
            if result.hard_block:
                break
        raise AgentGenerationError(
            "persona_validation_failed",
            reasons=reasons,
            candidate=candidate,
        )

    async def _generate(
        self,
        prompt: str,
        event: InteractionEvent,
        context: MemoryContext,
    ) -> AgentDecision:
        messages = [
            {"role": "system", "content": prompt},
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
