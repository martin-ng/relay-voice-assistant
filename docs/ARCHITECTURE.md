# Architecture and decisions

## Request flow

Browser text or reviewed speech → FastAPI → optional intent extraction → durable conversation state machine → transactional scheduling → persisted messages and action events → operator dashboard.

The browser gets a random session identifier and a 256-bit capability token. Only its hash is stored. The token authorizes access to that session; a different capability is required for operator access when configured. This is deliberately simpler than account identity and cannot support customer account recovery.

## Decisions

**SQLite for the local version.** WAL mode, bounded lock waits and `BEGIN IMMEDIATE` serialize writers. Interval overlap checks and the booking mutation happen in the same transaction, so two sessions cannot both claim overlapping intervals. SQLite is appropriate for this single-process portfolio demo, not horizontally distributed writes. A PostgreSQL migration should add a range exclusion constraint per resource, rather than rely only on application checks.

**One business and one service bay.** Service duration determines the occupied interval. Slots advance in 15-minute increments. Intervals use strict overlap (adjacent appointments are allowed). All timestamps are normalized to UTC; availability is generated in America/New_York so DST changes affect UTC offsets correctly. Holidays, multiple staff members and arbitrary resource capacity are not modeled.

**Two-phase conversation, one-phase database mutation.** Selecting a slot saves a proposed action, not a reservation. Exact confirmation causes a fresh conflict check and commit. Rescheduling updates the same appointment row atomically, keeping the original slot if validation or persistence fails. A five-minute timeout bounds stale proposals.

**Receipts, not optimistic client promises.** Each user message has a UUID request ID. Session + ID uniquely identifies a receipt containing an input hash and exact response. A matching retry replays the receipt; different text under the same ID is rejected. The response and booking are committed together, so loss of the HTTP response does not require another mutation. Different request IDs are distinct user intentions.

**Model proposes; deterministic code controls mutations.** Optional OpenAI interpretation maps utterances to a small schema. Model-produced confirmation becomes help, never a write. Only an exact user confirmation command can commit the server's pending action. All dates and references are validated again by application logic. Provider work happens outside the write lock; changed conversation state rejects stale results. A duplicate request can occasionally incur redundant parallel model calls, but only one durable mutation is committed.

**Browser speech as a replaceable input adapter.** Dictation produces editable text. Read-aloud uses browser synthesis. Neither can bypass confirmation or session access controls. The default engine is labeled guided; it does not pretend to understand unrestricted natural language.

**Standalone application.** This repository contains only Relay’s scheduling application and its tests. Earlier interview starter files and their dependencies are excluded; see `PROVENANCE.md`.

## Failure semantics

- Slot taken after selection: explain conflict, clear proposal, preserve existing appointments.
- Expired proposal: require a new selection.
- Known tool failure: roll back the action savepoint, record a safe error code and response.
- Unexpected exception: roll back the entire turn; caller may retry the same request ID.
- Storage unavailable/locked beyond deadline: return 503 without exposing database details.
- Language provider timeout/refusal: keep guided commands usable; no model-authorized mutation.
- Browser timeout after commit: retry the same request ID and replay the receipt.
- Human request: durable queue entry, no claim of an actual phone transfer or notification.

## Limits to address before public operation

No external calendar, telephony, full-duplex audio, multi-user account system, distributed rate limiter, automated retention or load-test capacity claim. The operator token is a single role, not a complete authorization system. Session transcripts contain raw user text in the local database even though HTTP logs avoid it. Readiness checks DB readability, not a complete write or disk-capacity guarantee. Schema version 1 is initialized idempotently; future schema changes need explicit versioned migrations.
