# Validation

## Standalone repository

This checkout has a dedicated 30-test suite and eight deterministic conversation scenarios. It excludes the original exercise and its 127 tests; those do not count toward Relay's test results.

Fresh-environment checks on 2026-11-03:

- All 30 tests passed with 93% statement coverage of `app/` (419 statements, 30 uncovered).
- All eight guided evaluation scenarios passed in isolated temporary databases.
- JavaScript syntax and local Markdown link checks passed.
- The reduced dependency lockfile resolved and installed into a fresh virtual environment.
- The standalone Docker image built successfully and passed disposable runtime checks for readiness, operator authentication, session creation and static serving.
- Credential-pattern scanning of the 29 repository candidates found no matches. This is a targeted scan, not a guarantee that every possible secret format is detected.
- Ignore rules were verified for environment files, databases, backups, generated artifacts and caches; `.env.example` remains included.
- Original exercise files and inherited tests are absent from this checkout.

## Earlier local application checks — 2026-11-03

Before extracting this standalone repository, the same application passed browser checks for availability selection, explicit confirmation, cancellation, confirmation expiry, handoff resolution and transcript inspection. Desktop and 390px layouts were inspected. The Docker image passed runtime smoke checks for readiness, operator authentication, session creation and static serving. SQLite online backup integrity returned `ok`.

These are historical application checks, not a claim that every target environment or hosted deployment has been verified.

## Limits

Live OpenAI account/model compatibility and intent accuracy, microphone/speaker behavior, speech-provider availability, telephony, external calendars, hosted CI execution, public-host security, load capacity and production recovery remain unverified or unimplemented.

Language tests use injected responses and failure cases. Guided evaluations are workflow checks, not AI accuracy benchmarks. No runtime database or transcript is included in this repository.
