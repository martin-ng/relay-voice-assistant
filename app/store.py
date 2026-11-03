"""Transactional scheduling and durable conversation state.

All times are stored as UTC ISO strings. Business hours use America/New_York.
SQLite's write lock serializes mutations; overlap checks and writes share the
same transaction. Request receipts make message retries safe across restarts.
"""
import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
SERVICES = {
    "consultation": {"name": "Consultation", "minutes": 30},
    "maintenance": {"name": "Routine maintenance", "minutes": 60},
    "inspection": {"name": "Vehicle inspection", "minutes": 45},
}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat()


def label(value):
    return datetime.fromisoformat(value).astimezone(TZ).strftime("%a, %b %d at %I:%M %p %Z")


class DomainError(Exception):
    def __init__(self, message, code="invalid_request", status=400):
        super().__init__(message)
        self.code, self.status = code, status


class Store:
    def __init__(self, path, clock=utcnow):
        self.path, self.clock = str(path), clock
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES (1);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    service TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('confirmed','cancelled')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS appointment_slots ON appointments(status, starts_at, ends_at);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    session_id TEXT NOT NULL REFERENCES sessions(id), request_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(session_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoffs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_handoff ON handoffs(session_id) WHERE status='open';
            """)

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_session(self):
        sid, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        now = stamp(self.clock())
        with self.connect(True) as db:
            db.execute("INSERT INTO sessions(id,token_hash,created_at,updated_at) VALUES (?,?,?,?)",
                       (sid, hashlib.sha256(token.encode()).hexdigest(), now, now))
            self.message(db, sid, "assistant", "Welcome to Relay Auto. I can help you book a consultation, maintenance, or inspection. What do you need?")
        return {"id": sid, "token": token}

    def authorize(self, db, sid, token):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row or not secrets.compare_digest(row["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise DomainError("Session access denied.", "unauthorized", 401)
        return row

    def message(self, db, sid, role, content):
        db.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES (?,?,?,?)",
                   (sid, role, content, stamp(self.clock())))

    def event(self, db, sid, kind, **detail):
        db.execute("INSERT INTO events(session_id,kind,detail,created_at) VALUES (?,?,?,?)",
                   (sid, kind, json.dumps(detail), stamp(self.clock())))

    def availability(self, db, service, day=None, exclude=None):
        if service not in SERVICES:
            raise DomainError("Choose consultation, maintenance, or inspection.")
        now = self.clock()
        first = now.astimezone(TZ).date()
        if day:
            try:
                first = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                raise DomainError("Use a date in YYYY-MM-DD format.")
            if first < now.astimezone(TZ).date() or first > now.astimezone(TZ).date() + timedelta(days=60):
                raise DomainError("Choose a date within the next 60 days.")
        slots = []
        for offset in range(1 if day else 14):
            date = first + timedelta(days=offset)
            if date.weekday() >= 5:
                continue
            start = datetime(date.year, date.month, date.day, 9, tzinfo=TZ)
            close = start.replace(hour=17)
            while start + timedelta(minutes=SERVICES[service]["minutes"]) <= close:
                end = start + timedelta(minutes=SERVICES[service]["minutes"])
                if start > now + timedelta(minutes=15) and not self.overlap(db, stamp(start), stamp(end), exclude):
                    slots.append({"starts_at": stamp(start), "ends_at": stamp(end), "label": label(stamp(start))})
                    if len(slots) >= 8:
                        return slots
                start += timedelta(minutes=15)
        return slots

    def overlap(self, db, start, end, exclude=None):
        return db.execute("""SELECT 1 FROM appointments WHERE status='confirmed'
            AND starts_at < ? AND ends_at > ? AND id != ? LIMIT 1""", (end, start, exclude or "")).fetchone()

    def appointment(self, db, sid, aid):
        row = db.execute("SELECT * FROM appointments WHERE id=? AND session_id=? AND status='confirmed'", (aid, sid)).fetchone()
        if not row:
            raise DomainError("That active appointment does not belong to this session.", "not_found", 404)
        return dict(row)

    def commit_booking(self, db, sid, pending):
        action = pending["action"]
        now = stamp(self.clock())
        if action == "cancel":
            old = self.appointment(db, sid, pending["appointment_id"])
            db.execute("UPDATE appointments SET status='cancelled',updated_at=? WHERE id=?", (now, old["id"]))
            self.event(db, sid, "booking.cancelled", appointment_id=old["id"])
            return "Your appointment has been cancelled."
        service, start = pending["service"], pending["starts_at"]
        old = self.appointment(db, sid, pending["appointment_id"]) if action == "reschedule" else None
        dt = datetime.fromisoformat(start).astimezone(TZ)
        end = stamp(dt + timedelta(minutes=SERVICES[service]["minutes"]))
        if dt <= self.clock() + timedelta(minutes=15):
            raise DomainError("That time is too close or has passed. Please choose another slot.", "slot_expired", 409)
        if self.overlap(db, start, end, old["id"] if old else None):
            raise DomainError("That slot was just taken. Please choose another time.", "slot_conflict", 409)
        aid = old["id"] if old else str(uuid.uuid4())
        if old:
            db.execute("UPDATE appointments SET starts_at=?,ends_at=?,updated_at=? WHERE id=?", (start, end, now, aid))
        else:
            db.execute("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?)", (aid, sid, service, start, end, "confirmed", now, now))
        self.event(db, sid, "booking.rescheduled" if old else "booking.created", appointment_id=aid)
        return f"Your {SERVICES[service]['name'].lower()} is {'rescheduled' if old else 'booked'} for {label(start)}. Reference {aid[:8]}."

    def snapshot(self, db, sid):
        session = db.execute("SELECT id,status,state FROM sessions WHERE id=?", (sid,)).fetchone()
        return {"id": sid, "status": session["status"], "state": json.loads(session["state"]),
                "messages": [dict(r) for r in db.execute("SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY id", (sid,))],
                "appointments": [dict(r) for r in db.execute("SELECT * FROM appointments WHERE session_id=? ORDER BY starts_at", (sid,))]}

    def turn(self, sid, token, request_id, text, command=None, expected_state=None, language_failed=False):
        from .conversation import respond
        started = time.perf_counter()
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.connect(True) as db:
            session = self.authorize(db, sid, token)
            receipt = db.execute("SELECT * FROM receipts WHERE session_id=? AND request_id=?", (sid, request_id)).fetchone()
            if receipt:
                if receipt["input_hash"] != digest:
                    raise DomainError("This request ID was already used for a different message.", "idempotency_conflict", 409)
                return json.loads(receipt["response"])
            if expected_state is not None and session["state"] != expected_state:
                raise DomainError("The conversation changed while processing. Please send your request again.", "stale_turn", 409)
            state = json.loads(session["state"])
            self.message(db, sid, "user", text)
            if language_failed:
                self.event(db, sid, "language.fallback", reason="provider_unavailable")
            # A savepoint ensures a handled tool error cannot leave a partial mutation.
            db.execute("SAVEPOINT action")
            try:
                reply, state = respond(self, db, sid, state, command if command is not None else text)
                if language_failed:
                    reply = "Natural-language mode is temporarily unavailable. Guided commands still work.\n\n" + reply
            except DomainError as exc:
                db.execute("ROLLBACK TO action")
                reply, state = str(exc), {}
                self.event(db, sid, "tool.failed", code=exc.code)
            db.execute("RELEASE action")
            self.message(db, sid, "assistant", reply)
            db.execute("UPDATE sessions SET state=?,updated_at=? WHERE id=?", (json.dumps(state), stamp(self.clock()), sid))
            self.event(db, sid, "turn.completed", latency_ms=round((time.perf_counter()-started)*1000, 2))
            result = self.snapshot(db, sid)
            db.execute("INSERT INTO receipts VALUES (?,?,?,?)", (sid, request_id, digest, json.dumps(result)))
            return result

    def dashboard(self):
        with self.connect() as db:
            appointments = [dict(r) for r in db.execute("SELECT * FROM appointments ORDER BY starts_at DESC LIMIT 200")]
            sessions = [dict(r) for r in db.execute("SELECT id,status,created_at,updated_at FROM sessions ORDER BY updated_at DESC LIMIT 100")]
            events = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100")]
            latencies = [json.loads(r[0])["latency_ms"] for r in db.execute("SELECT detail FROM events WHERE kind='turn.completed' ORDER BY id DESC LIMIT 1000")]
            latencies.sort()
            metrics = {"sessions": db.execute("SELECT count(*) FROM sessions").fetchone()[0],
                       "confirmed": db.execute("SELECT count(*) FROM appointments WHERE status='confirmed'").fetchone()[0],
                       "failures": db.execute("SELECT count(*) FROM events WHERE kind='tool.failed'").fetchone()[0],
                       "p95_ms": latencies[min(len(latencies)-1, int(len(latencies)*.95))] if latencies else None,
                       "turns": len(latencies)}
            return {"appointments": appointments, "sessions": sessions, "events": events, "metrics": metrics,
                    "handoffs": [dict(r) for r in db.execute("SELECT * FROM handoffs ORDER BY created_at DESC LIMIT 100")]}
