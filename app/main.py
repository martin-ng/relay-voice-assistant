import json
import logging
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .store import Store, DomainError, SERVICES, TZ
from .language import direct_command, OpenAILanguage

logger = logging.getLogger("relay")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


class Turn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    request_id: uuid.UUID


def create_app(db_path=None, admin_token=None, mode=None, language=None):
    mode = mode or os.getenv("APP_MODE", "local")
    admin_token = admin_token if admin_token is not None else os.getenv("ADMIN_TOKEN", "")
    if mode not in {"local", "production"}:
        raise RuntimeError("APP_MODE must be local or production")
    if mode == "production" and len(admin_token) < 32:
        raise RuntimeError("Production mode requires ADMIN_TOKEN of at least 32 characters")
    language_mode = os.getenv("LANGUAGE_MODE", "guided")
    if language_mode not in {"guided", "openai"}:
        raise RuntimeError("LANGUAGE_MODE must be guided or openai")
    if language is None and language_mode == "openai":
        language = OpenAILanguage(os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL"))
    store = Store(db_path or os.getenv("DATABASE_PATH", "data/relay.db"))
    app = FastAPI(title="Relay Voice Scheduling", version="0.2.0")
    app.state.store = store

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        # Local mode is deliberately loopback-only, not an unauthenticated hosted service.
        if mode == "local" and request.client and request.client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            return JSONResponse({"error": "local_only", "message": "Local mode only accepts loopback clients."}, status_code=403)
        if mode == "local" and request.url.hostname not in {"127.0.0.1", "::1", "localhost", "testserver"}:
            return JSONResponse({"error": "host_denied"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": "origin_denied", "message": "Cross-origin requests are disabled."}, status_code=403)
        if request.method in {"POST", "PATCH", "DELETE"} and request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "json_required"}, status_code=415)
        if request.method in {"POST", "PATCH", "DELETE"}:
            total = 0
            chunks = []
            async for chunk in request.stream():
                total += len(chunk)
                if total > 8192:
                    return JSONResponse({"error": "body_too_large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        # Swagger's generated page uses its own CDN assets and inline bootstrap.
        if request.url.path not in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        logger.info(json.dumps({"request_id": request_id, "method": request.method, "status": response.status_code, "latency_ms": round((time.perf_counter()-started)*1000, 2)}))
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"error": exc.code, "message": str(exc)}, status_code=exc.status)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        logger.error("database_unavailable")
        return JSONResponse({"error": "database_unavailable", "message": "Storage is temporarily unavailable. Retry the same request."}, status_code=503)

    def operator(authorization):
        if admin_token and not secrets.compare_digest(authorization or "", "Bearer " + admin_token):
            raise DomainError("Enter the operator token to view this dashboard.", "unauthorized", 401)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        with store.connect() as db:
            db.execute("SELECT version FROM schema_version").fetchone()
        return {"status": "ready", "storage": "sqlite"}

    @app.get("/api/config")
    def config():
        return {"mode": mode, "engine": "openai" if language else "guided", "timezone": "America/New_York", "services": SERVICES, "operator_auth": bool(admin_token)}

    @app.post("/api/sessions", status_code=201)
    def create_session():
        return store.create_session()

    @app.get("/api/sessions/{sid}")
    def session(sid: uuid.UUID, x_session_token: str = Header(default="")):
        with store.connect() as db:
            store.authorize(db, str(sid), x_session_token)
            return store.snapshot(db, str(sid))

    @app.post("/api/sessions/{sid}/messages")
    def turn(sid: uuid.UUID, body: Turn, x_session_token: str = Header(default="")):
        if not body.text.strip():
            raise DomainError("Please enter a message.")
        text = body.text.strip()
        command, expected_state, failed = None, None, False
        if language and not direct_command(text):
            # Network work happens outside the database write transaction.
            with store.connect() as db:
                session = store.authorize(db, str(sid), x_session_token)
                receipt = db.execute("SELECT 1 FROM receipts WHERE session_id=? AND request_id=?", (str(sid), str(body.request_id))).fetchone()
                expected_state = session["state"]
            if not receipt:
                try:
                    command = language.normalize(text, json.loads(expected_state), store.clock().astimezone(TZ).date().isoformat())
                except Exception:
                    logger.warning("language_provider_unavailable")
                    command, failed = "help", True
        return store.turn(str(sid), x_session_token, str(body.request_id), text, command, expected_state, failed)

    @app.get("/api/operator/dashboard")
    def dashboard(authorization: str = Header(default="")):
        operator(authorization)
        return store.dashboard()

    @app.get("/api/operator/sessions/{sid}")
    def inspect_session(sid: uuid.UUID, authorization: str = Header(default="")):
        operator(authorization)
        with store.connect() as db:
            if not db.execute("SELECT 1 FROM sessions WHERE id=?", (str(sid),)).fetchone():
                raise DomainError("Session not found.", "not_found", 404)
            return store.snapshot(db, str(sid))

    @app.post("/api/operator/handoffs/{hid}/resolve")
    def resolve(hid: uuid.UUID, authorization: str = Header(default="")):
        operator(authorization)
        with store.connect(True) as db:
            row = db.execute("SELECT * FROM handoffs WHERE id=?", (str(hid),)).fetchone()
            if not row:
                raise DomainError("Handoff not found.", "not_found", 404)
            db.execute("UPDATE handoffs SET status='resolved' WHERE id=?", (str(hid),))
            db.execute("UPDATE sessions SET status='active' WHERE id=?", (row["session_id"],))
            if row["status"] != "resolved":
                store.event(db, row["session_id"], "handoff.resolved")
        return {"status": "resolved"}

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
    return app
