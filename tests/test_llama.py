import os
import json
import requests
import pytest
from app import config

SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://localhost:8000")

def _is_server_available():
    try:
        return requests.get(SERVER_URL + "/health", timeout=1).ok
    except Exception:
        return False

@pytest.mark.skipif(
    not _is_server_available(),
    reason="LLAMA server not running, skipping tests",
)
def test_health_endpoint():
    """Verify that the llama-server health endpoint is reachable."""
    resp = requests.get(f"{SERVER_URL}/health")
    assert resp.status_code == 200

@pytest.mark.skipif(
    not _is_server_available(),
    reason="LLAMA server not running, skipping tests",
)
def test_chat_completion_basic():
    """Send a minimal chat completion request and ensure a response is returned."""
    payload = {
        "model": config.MODEL_NAME,
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0,
    }
    resp = requests.post(f"{SERVER_URL}/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert len(data["choices"]) > 0
    assert "message" in data["choices"][0]
    assert "content" in data["choices"][0]["message"]