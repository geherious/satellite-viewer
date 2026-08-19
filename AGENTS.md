# AGENTS.md

## What this is

Telegram bot (`sma_bot`) that fetches satellite orbital data from SpaceTrack, stores semi-major-axis history in SQLite, and sends altitude-over-time PDF plots to authorized users.

## Running locally

Requires a `.env` file at repo root (gitignored) with these variables:

```
TELEGRAM_BOT_TOKEN=...
SPACETRACK_IDENTITY=...
SPACETRACK_PASSWORD=...
ALLOWED_PHONES=+7...,+7...
SMA_DB_PATH=./sma_bot.db
```

All are mandatory except `SMA_DB_PATH` (defaults to `./sma_bot.db`). Missing vars raise `ValueError` at import time via `config.py`.

Run with: `python -m sma_bot`

## Architecture

- `sma_bot/config.py` — env loading, fails fast on missing vars
- `sma_bot/bot.py` — Telegram handlers, main entrypoint (`main()`). Presentation-only; delegates to service. Registers cron jobs.
- `sma_bot/service.py` — `SatelliteService.actualize()` encapsulates fetch/classify/persist logic. Returns `list[ActualizeResult]` with `ActualizeStatus` enum (`Cached`, `Refreshed`, `New`, `NotFound`).
- `sma_bot/cron.py` — `actualize_all()` scheduled job, runs at 00:03 and 12:03 via `JobQueue.run_daily`. Calls `actualize()` per satellite with `CRON_DELAY_SECONDS` delay between calls.
- `sma_bot/db.py` — SQLite via stdlib `sqlite3`, WAL mode, manual connection management (no ORM)
- `sma_bot/spacetrack_client.py` — SpaceTrack API wrapper (`spacetrack` package). Returns typed `SpaceTrackRecord` dataclasses, not dicts.
- `sma_bot/plotting.py` — matplotlib PDF generation into `tempfile`, then served to user

## Gotchas

- **No tests, no linter, no type checker** configured in this repo.
- **SQLite schema changes** require manual migration — `init_db()` uses `CREATE TABLE IF NOT EXISTS` and catches `ALTER TABLE` errors. There are no migration files.
- **PDF generation** writes to `tempfile.gettempdir()`, not the working directory.
- **Authorization** is in-memory only (`authorized_users` set in `bot.py`). Lost on restart.
- **Deploy** is SSH-based on push to `main` (`.github/workflows/deploy.yml`). No containerization.
- `spacetrack` API calls can be slow; each creates a new `SpaceTrackClient` and closes it.
- `FRESHNESS_HOURS` lives in `service.py`; `PLOT_WINDOW_DAYS` lives in `bot.py` (controls PDF query window).
