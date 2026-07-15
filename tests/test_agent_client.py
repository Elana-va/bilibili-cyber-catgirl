import json

import httpx

from cyber_catgirl.agent.client import DeepSeekClient


def test_deepseek_client_defaults_to_v4_flash():
    client = DeepSeekClient("not-a-real-key")

    assert client.model == "deepseek-v4-flash"


async def test_deepseek_client_sends_the_requested_json_schema():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"action":"reply"}'}}
                ]
            },
        )

    schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
        "required": ["action"],
    }
    client = DeepSeekClient(
        "not-a-real-key",
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate_json(
        [{"role": "user", "content": "hello"}],
        schema,
    )

    assert result == {"action": "reply"}
    schema_message = captured["messages"][0]
    assert schema_message["role"] == "system"
    assert json.dumps(schema, separators=(",", ":")) in schema_message["content"]
