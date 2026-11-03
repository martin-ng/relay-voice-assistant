# Roadmap

## Implemented locally

- Independent scheduling app with persistent SQLite state and a browser dashboard.
- Availability, explicitly confirmed booking, cancellation and atomic rescheduling.
- Conflict prevention, request receipts, session capability authorization and operator token support.
- Session transcript review, event history, handoff queue and server-turn latency metric.
- Browser dictation/read-aloud and an optional OpenAI language adapter.
- Unit/API/concurrency tests, conversation evaluations, container/CI configuration and backup tooling.

## Next meaningful increments

1. Verify live speech and the optional language adapter with a real configured account; build a labeled intent evaluation set and measure accuracy.
2. Add customer identity, expiring sessions, quotas and a documented transcript retention/deletion policy.
3. Integrate one external calendar using a reconciliation design and provider-specific contract tests.
4. Migrate to PostgreSQL with schema migrations and resource interval constraints when multi-instance deployment is actually needed.
5. Add telephony or a true full-duplex voice transport, with measured interruption and disconnect behavior.
6. Validate a hosted deployment, restore drill, browser compatibility matrix and realistic load profile.

These are remaining work, not claims about implemented features or time spent.
