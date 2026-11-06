"""FastAPI service: one plain-English question in, one guarded answer out.

This module only wires HTTP to `t2sql.graph.pipeline.answer_question`. All safety (Guard, EXPLAIN,
read-only role, timeout) happens inside the pipeline. Run it with:

    uvicorn api.main:app --port 8000

The one database connection is shared by all requests, so requests are served one at a time
(a lock). That is fine for a single-user laptop demo; a pool would come later.
"""

import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from api.serialize import answer_to_json
from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.dictionary_models import Dictionary
from t2sql.core.profile import load_profile
from t2sql.core.schema_models import SchemaInfo
from t2sql.dialects import get_dialect
from t2sql.dialects.base import Dialect
from t2sql.generation.client import Completion, ModelServerError, chat
from t2sql.graph.pipeline import answer_question
from t2sql.retrieval.dictionary import load_dictionary

Ask = Callable[[list[dict[str, str]]], Completion]
MODEL_CHECK_TIMEOUT_S = 2.0
log = logging.getLogger("api")

MSG_NO_MODEL = "The language model server is not reachable. Start it and try again."
MSG_NO_DB = "The database is not reachable. Start it and try again."


class AskBody(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class Copilot:
    """What one API process holds: profile, dictionary, dialect, and ONE read-only connection."""

    def __init__(self, settings: Settings, ask: Ask) -> None:
        self.settings = settings
        self.ask = ask
        self.profile = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
        self.dictionary: Dictionary = load_dictionary(REPO_ROOT / self.profile.dictionary)
        self.dialect: Dialect = get_dialect(self.profile.dialect)
        self.lock = threading.Lock()
        self._conn: psycopg.Connection | None = None
        self._schema: SchemaInfo | None = None

    def _open(self) -> psycopg.Connection:
        """Return the shared connection, (re)connecting and loading the schema when needed."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.settings.ro_dsn)
        if self._schema is None:
            self._schema = self.dialect.introspect(self._conn, self.profile.schema_name)
        return self._conn

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except psycopg.Error:
                pass
        self._conn = None

    def startup(self) -> None:
        """Connect once at start-up. If the database is down the API still starts; /ask retries."""
        with self.lock:
            try:
                self._open()
            except psycopg.Error as exc:
                log.warning(
                    "database not reachable at start-up (%s); will retry", exc.__class__.__name__
                )
                self._drop()

    def shutdown(self) -> None:
        with self.lock:
            self._drop()

    def db_ok(self) -> bool:
        """Health probe on its own short connection, so it never waits for a running question."""
        try:
            with psycopg.connect(self.settings.ro_dsn) as conn:
                conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False

    def answer(self, question: str) -> dict:
        with self.lock:
            # One reconnect: a dropped connection (server restart, idle timeout) should not fail
            # the request. The second failure is raised to the endpoint, which returns 503.
            for attempt in (1, 2):
                try:
                    conn = self._open()
                    conn.rollback()  # end any transaction left over from an earlier request
                    result = answer_question(
                        question,
                        conn=conn,
                        schema=self._schema,  # type: ignore[arg-type]  # set by _open()
                        dictionary=self.dictionary,
                        dialect=self.dialect,
                        today=self.settings.ref_now,
                        ask=self.ask,
                    )
                    return answer_to_json(result)
                except psycopg.OperationalError:
                    self._drop()
                    if attempt == 2:
                        raise
        raise AssertionError("unreachable")  # the loop either returns or raises


def _model_ok(base_url: str) -> bool:
    """True when the model server answers /models. Never raises: any failure means False."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=MODEL_CHECK_TIMEOUT_S)
        return response.status_code == 200
    except Exception:  # noqa: BLE001  # a health check must not crash on any network error
        return False


def create_app(ask: Ask | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass a fake `ask`; production uses the real model server."""
    settings = settings or Settings.from_env()
    copilot = Copilot(settings, ask or (lambda msgs: chat(settings.llm_base_url, msgs)))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        copilot.startup()
        yield
        copilot.shutdown()

    app = FastAPI(title="SQL Copilot API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "db": copilot.db_ok(),
            "model": _model_ok(settings.llm_base_url),
        }

    @app.post("/ask")
    def ask_question(body: AskBody) -> JSONResponse:
        try:
            payload = copilot.answer(body.question)
        except ModelServerError as exc:
            raise HTTPException(status_code=503, detail=MSG_NO_MODEL) from exc
        except psycopg.OperationalError as exc:
            raise HTTPException(status_code=503, detail=MSG_NO_DB) from exc
        return JSONResponse(payload)

    return app


app = create_app()
