from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import build_router
from main import AgentOrchestrator


def make_client():
    orchestrator = AgentOrchestrator(
        ledger_path=":memory:", initial_cash="100", max_book_age_ms=1000
    )
    app = FastAPI()
    app.include_router(build_router(orchestrator), prefix="/api")
    return TestClient(app), orchestrator


def test_status_reports_truthful_paper_mode_and_ledger_state():
    client, orchestrator = make_client()
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False
    assert body["paper_trading"] is True
    assert body["feed_healthy"] is False
    assert body["kill_switch_active"] is False
    assert body["risk_stats"]["cash"] == "100"
    assert body["open_positions"] == 0
    orchestrator.ledger.close()


def test_local_kill_and_resume_use_public_risk_controls():
    client, orchestrator = make_client()
    killed = client.post("/api/kill")
    assert killed.status_code == 200
    assert killed.json()["success"] is True
    assert orchestrator.risk.is_killed is True

    resumed = client.post("/api/resume")
    assert resumed.status_code == 200
    assert resumed.json()["success"] is True
    assert orchestrator.risk.is_killed is False
    orchestrator.ledger.close()
