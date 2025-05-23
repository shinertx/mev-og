import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
pytest.importorskip("httpx")
from fastapi.testclient import TestClient
import monitoring_dashboard as md

client = TestClient(md.app)


def login(username="admin", password="adminpass"):
    response = client.post("/token", data={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_login_and_metrics():
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/metrics", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "pnl" in body


def test_execute_trade(monkeypatch):
    token = login()
    headers = {"Authorization": f"Bearer {token}"}

    def fake_rationale(trade):
        return "mock rationale"

    monkeypatch.setattr(md, "generate_ai_rationale", fake_rationale)
    monkeypatch.setattr(md.alert_manager, "send_email_alert", lambda *a, **kw: None)
    monkeypatch.setattr(md.alert_manager, "send_slack_alert", lambda *a, **kw: None)

    r = client.post("/trades", params={"asset": "BTC", "quantity": 1, "price": 10}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rationale"] == "mock rationale"
