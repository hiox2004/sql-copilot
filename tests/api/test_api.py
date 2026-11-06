"""The HTTP API, tested with a fake model (`ask`), so no model server is needed.

Tests marked `integration` need the Docker database. They skip cleanly when it is down.
"""

import json
from dataclasses import replace

import psycopg
import pytest
from api.main import create_app
from fastapi.testclient import TestClient

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.generation.client import Completion, ModelServerError
from t2sql.validation.redteam import load_redteam

SETTINGS = Settings.from_env()
REDTEAM_GUARD_ITEMS = load_redteam(REPO_ROOT / "data" / "eval" / "redteam.yaml").blocked_by(
    "guard_parser"
)
COUNTED_TABLES = ("users", "payments", "orders", "subscriptions", "organizations")


def fake_model(sql: str | None = None, text: str | None = None):
    """A stand-in for the model: always answers with the given SQL (or raw text)."""

    def ask(messages):
        body = (
            text
            if text is not None
            else json.dumps({"sql": sql, "tables_used": [], "assumptions": []})
        )
        return Completion(text=body, seconds=0.1, prompt_tokens=1, completion_tokens=1)

    return ask


@pytest.fixture
def db_up():
    try:
        with psycopg.connect(SETTINGS.ro_dsn):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")


def _snapshot() -> dict:
    with psycopg.connect(SETTINGS.ro_dsn) as conn:
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in COUNTED_TABLES
        }
        counts["_tables"] = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]
    return counts


def test_health_shape_even_without_a_model():
    # Points at a model URL that is not running: /health must still answer, with model false.
    app = create_app(ask=fake_model(sql="SELECT 1"), settings=_with_model_url("http://127.0.0.1:9"))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["db"], bool)
    assert body["model"] is False


@pytest.mark.integration
def test_good_query_is_answered(db_up):
    app = create_app(ask=fake_model(sql="SELECT count(*) FROM organizations"))
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "How many customers are there?"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True, body
    assert body["rows"], "expected one row back"
    assert "LIMIT" in body["sql"].upper()
    assert body["error"] is None


@pytest.mark.parametrize("question", ["", "   ", "ab", "x" * 501])
def test_bad_question_is_422(question):
    app = create_app(ask=fake_model(sql="SELECT 1"))
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": question})
    assert response.status_code == 422


def test_missing_question_is_422():
    app = create_app(ask=fake_model(sql="SELECT 1"))
    with TestClient(app) as client:
        assert client.post("/ask", json={}).status_code == 422


def test_model_down_is_503_without_stack_trace():
    def down(messages):
        raise ModelServerError("connection refused at 10.0.0.1:8080 (internal detail)")

    app = create_app(ask=down)
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "How many customers are there?"})
    assert response.status_code == 503
    assert "internal detail" not in response.text


@pytest.mark.integration
def test_non_json_model_reply_is_a_clean_failure(db_up):
    app = create_app(ask=fake_model(text="Sure! Here is the answer in prose, no JSON."))
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "How many customers are there?"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["rows"] == []
    assert isinstance(body["error"], str) and body["error"]


@pytest.mark.integration
@pytest.mark.parametrize("item", REDTEAM_GUARD_ITEMS, ids=lambda item: item.id)
def test_redteam_attack_is_blocked(db_up, item):
    """Every parser-layer attack, returned by a tricked model on every try, must be refused."""
    before = _snapshot()
    app = create_app(ask=fake_model(sql=item.sql))
    question = item.question or "Show me the data"
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": question})
    after = _snapshot()
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False, f"{item.id}: attack was answered: {body}"
    assert body["rows"] == [], f"{item.id}: attack returned rows"
    assert before == after, f"{item.id}: database changed"


def test_redteam_guard_set_is_big_enough():
    assert len(REDTEAM_GUARD_ITEMS) >= 15


def _with_model_url(url: str) -> Settings:
    return replace(SETTINGS, llm_base_url=url)
