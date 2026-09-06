"""Tests for the demo call server."""

import json

from fastapi.testclient import TestClient

from app import config
from app.main import app, build_call_record

client = TestClient(app)


def test_index_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Robot Dispatch" in response.text


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_live_config_declares_both_tools():
    live_config = config.build_live_config()
    assert live_config["response_modalities"] == ["AUDIO"]
    names = {
        declaration["name"]
        for tool in live_config["tools"]
        for declaration in tool["function_declarations"]
    }
    assert names == {"record_pickup_response", "end_call"}


def test_build_call_record_is_json_serialisable():
    record = build_call_record(
        "call-1",
        "2026-01-01T00:00:00+00:00",
        {
            "accepted": True,
            "reason": "I have room in the van",
            "verbatim_answer": "Yes, I can take one more pickup.",
        },
    )
    assert record["status"] == "accepted"
    assert record["call_id"] == "call-1"
    assert record["available_time_window"] is None
    json.dumps(record)


def test_build_call_record_declined():
    record = build_call_record("call-2", "2026-01-01T00:00:00+00:00",
                               {"accepted": False})
    assert record["status"] == "declined"
    assert record["verbatim_answer"] is None


def test_websocket_reports_missing_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with client.websocket_connect("/ws/call") as websocket:
        message = websocket.receive_json()
    assert message["type"] == "error"
    assert "GOOGLE_API_KEY" in message["message"]
