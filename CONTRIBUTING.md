# Development

Use Python 3.13+ and install the locked environment with `uv sync --frozen --extra test`. Node is needed only for the JavaScript syntax check; the frontend has no package installation or build step.

Before proposing a change:

```sh
make check
```

Format dashboard source with `npx --yes prettier@3.6.2 --write app/static/app.js app/static/style.css app/static/index.html` when editing it.

Keep scheduling mutations inside the database transaction boundary. Preserve explicit confirmation and session ownership checks. Network calls belong outside the write transaction. When changing booking behavior, cover a realistic failure or concurrency case in addition to the successful flow.

Use temporary databases for tests. Do not commit `.env` files, transcripts, databases, recordings, backups or generated reports. Update the architecture or operations notes when behavior changes. Documentation must distinguish verified behavior from planned work.

The CI configuration runs tests, the guided evaluation suite and a JavaScript syntax check. Live model calls are not required in CI.
