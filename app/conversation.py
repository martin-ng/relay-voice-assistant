"""A deterministic conversation engine shared by text and browser speech.

The engine is deliberately not presented as an LLM. Pending actions are server
state, never executable arguments supplied by the browser.
"""
import re
import uuid
from datetime import timedelta
from .store import SERVICES, TZ, DomainError, label, stamp


def slot_reply(store, db, state):
    slots = store.availability(db, state["service"], state.get("day"), state.get("appointment_id"))
    if not slots:
        return "No openings on that date. Try another YYYY-MM-DD date; we are open Monday–Friday, 9am–5pm Eastern.", {**state, "slots": []}
    return ("Here are available times in Eastern time. Choose a number or tap a time:\n" +
            "\n".join(f"{i+1}. {s['label']}" for i, s in enumerate(slots))), {**state, "slots": slots}


def respond(store, db, sid, state, text):
    value = text.strip().lower().rstrip(".!?")
    if value in {"human", "agent", "help me", "handoff", "talk to a person"}:
        db.execute("INSERT OR IGNORE INTO handoffs(id,session_id,created_at) VALUES (?,?,?)", (str(uuid.uuid4()), sid, stamp(store.clock())))
        db.execute("UPDATE sessions SET status='handoff' WHERE id=?", (sid,))
        store.event(db, sid, "handoff.requested")
        return "I've added this session to the operator's handoff queue. This local demo does not call or notify anyone. You can continue booking here.", {}
    if value in {"no", "no thanks", "stop", "never mind", "nevermind", "start over"}:
        return "Okay, I haven't changed your appointments. What would you like to do next?", {}
    if value in {"yes", "confirm", "yes please", "confirm booking", "confirm cancellation", "confirm reschedule"}:
        if not state.get("pending"):
            return "There is nothing to confirm yet. Choose a service and an available time first.", state
        pending = state["pending"]
        if store.clock().timestamp() - pending["proposed_at"] > 300:
            return "That confirmation has expired. Ask for availability again so I can check the time.", {}
        return store.commit_booking(db, sid, pending), {}
    if value in {"appointments", "my appointments", "my bookings", "list"}:
        rows = db.execute("SELECT * FROM appointments WHERE session_id=? AND status='confirmed' ORDER BY starts_at", (sid,)).fetchall()
        if not rows:
            return "You have no active appointments in this session. Try 'book an inspection'.", {}
        return "Your appointments:\n" + "\n".join(f"{r['id'][:8]} · {SERVICES[r['service']]['name']} · {label(r['starts_at'])}" for r in rows), {}
    change = re.fullmatch(r"(cancel|reschedule)(?:\s+appointment)?(?:\s+([a-z0-9-]+))?", value)
    if change:
        action, ref = change.groups()
        rows = db.execute("SELECT * FROM appointments WHERE session_id=? AND status='confirmed' ORDER BY starts_at", (sid,)).fetchall()
        matches = [r for r in rows if not ref or r["id"].startswith(ref)]
        if len(matches) != 1:
            return "Please specify an active appointment reference, for example 'cancel abc12345'. Type 'my appointments' to see yours.", {}
        old = matches[0]
        if action == "cancel":
            return f"Cancel your {SERVICES[old['service']]['name'].lower()} on {label(old['starts_at'])}? Say confirm or no.", {"pending": {"action": action, "appointment_id": old["id"], "proposed_at": store.clock().timestamp()}}
        return slot_reply(store, db, {"action": action, "appointment_id": old["id"], "service": old["service"]})
    choice = re.fullmatch(r"(?:option |number |slot )?(\d+|one|two|three|four|five|six|seven|eight)", value)
    if choice and state.get("slots"):
        raw = choice.group(1)
        words = ["one", "two", "three", "four", "five", "six", "seven", "eight"]
        index = int(raw)-1 if raw.isdigit() else words.index(raw)
        if index < 0 or index >= len(state["slots"]):
            return "Choose one of the listed slot numbers.", state
        slot = state["slots"][index]
        pending = {"action": state.get("action", "book"), "service": state["service"], "starts_at": slot["starts_at"], "proposed_at": store.clock().timestamp()}
        if "appointment_id" in state:
            pending["appointment_id"] = state["appointment_id"]
        return f"Please confirm: {SERVICES[state['service']]['name']}, {label(slot['starts_at'])}, {SERVICES[state['service']]['minutes']} minutes. Say confirm to {pending['action']}, or no to go back.", {"pending": pending}
    service = next((s for s in SERVICES if re.search(r"\b"+s+r"\b", value)), None)
    day_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", value)
    day = day_match.group() if day_match else None
    if "tomorrow" in value:
        day = (store.clock().astimezone(TZ).date()+timedelta(days=1)).isoformat()
    elif "today" in value:
        day = store.clock().astimezone(TZ).date().isoformat()
    if service or (day and state.get("service")):
        next_state = {"service": service or state["service"], "action": "book"}
        if not service and state.get("action") == "reschedule":
            next_state.update(action="reschedule", appointment_id=state["appointment_id"])
        if day:
            next_state["day"] = day
        return slot_reply(store, db, next_state)
    if value in {"hours", "business hours"}:
        return "Relay Auto is open Monday–Friday, 9am–5pm America/New_York. Consultation: 30 min; maintenance: 60 min; inspection: 45 min.", state
    return "I can book a consultation, maintenance, or inspection. Try 'inspection tomorrow', choose a time, then confirm. You can also say 'my appointments', 'cancel', 'reschedule', or 'human'. For a specific date use YYYY-MM-DD.", state
