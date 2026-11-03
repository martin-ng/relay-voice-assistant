# Operations runbook

## Start and inspect

Run `make setup` then `make run` from the project root. Open port 8765 on localhost. `/health/live` checks process availability; `/health/ready` checks schema readability. `/docs` exposes the OpenAPI explorer (Swagger uses external assets). Neither probe calls OpenAI.

The operator dashboard auto-refreshes every 15 seconds while visible. Appointment display is bounded to 200 records, sessions and events to 100, and p95 scheduling latency to the last 1,000 completed turns. Totals are computed separately; these are not a full analytics warehouse.

## Back up

```sh
uv run --frozen python scripts/backup.py backups/relay-2026-11-03.db
```

The utility uses SQLite's online backup API so WAL writes are included consistently. It refuses to overwrite an existing destination. Backups contain transcripts and capability hashes; handle them as application data. To restore, stop the server, preserve the current database and its WAL/SHM companions in a separate directory, and place the backup at the configured database path. Never restore by overwriting an actively open database.

## Troubleshoot

- **401:** restore the correct session tab or enter the configured operator token. Tokens are not printed in logs.
- **403:** local mode blocks non-loopback clients, unexpected Host values and cross-origin requests. For container use, Compose sets production mode and requires operator credentials.
- **409 slot conflict:** another appointment won the slot; request availability again. Do not blindly retry with a new booking intent.
- **409 stale turn:** conversation state changed while optional language interpretation was in flight; review the current state and send a new request.
- **503 storage:** check free disk space, DB permissions, and long-lived SQLite writers. Retry with the same request ID.
- **Language fallback:** check explicitly exported model/key configuration and provider access. Guided commands continue to work. Model accuracy and live availability are not established by mocked tests.
- **No microphone:** use text input. Browser speech support and OS permissions vary; it is not needed to use scheduling.

## Before public hosting

Put TLS and request/rate limits at the edge; add verified customer accounts, session expiration and recovery, per-user quotas, operator roles and audit access policies. Implement transcript retention and deletion including receipt snapshots/backups. Validate full deployment, restore, outage and load behavior in the target environment. Public session creation is currently unauthenticated; an operator token alone does not prevent abuse or model spend. Bind to localhost until those controls are implemented.

External calendar synchronization needs provider idempotency, reconciliation and a deliberate source-of-truth decision. Do not add an HTTP calendar call inside the SQLite transaction and assume that makes both systems atomic.
