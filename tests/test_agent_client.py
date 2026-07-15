from cyber_catgirl.agent.client import DeepSeekClient


def test_deepseek_client_defaults_to_v4_flash():
    client = DeepSeekClient("not-a-real-key")

    assert client.model == "deepseek-v4-flash"
