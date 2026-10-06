# Repository instructions

Read README.md, CONTRIBUTING.md and docs/ARCHITEKTUR.md before structural changes.
Domain modules live in vereinswertung; root Python files are stable entrypoints.
Keep moves/formatting separate from behavior changes. Do not replace established
Flask/SQLite architecture during unrelated tasks.
Run the development interpreter with tools/check.py after relevant changes.
Use mocked external services and synthetic data. Preserve licenses and reference
source bytes. Maintain the explicit public-source allowlist in app.py when adding
release files. Never commit runtime data, private rosters or credentials.
Production deployment is separate from repository maintenance; do not deploy
without a deployment request. Explain limitations and failed checks honestly.
