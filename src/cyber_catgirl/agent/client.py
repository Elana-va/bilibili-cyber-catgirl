from typing import Protocol

import httpx

from cyber_catgirl.services.deepseek_connection import DEFAULT_MODEL


class LLMPort(Protocol):
    async def generate_json(self, messages: list[dict], schema: dict) -> dict: ...


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_json(self, messages: list[dict], schema: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.6,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return AgentJsonParser.parse(content)


class AgentJsonParser:
    @staticmethod
    def parse(content: str) -> dict:
        import json

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("model response must be a JSON object")
        return parsed
