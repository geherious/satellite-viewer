# Telegram SMA Plotting Bot — Build Specification

## 1. Purpose

A Telegram bot that accepts a list of NORAD catalog IDs plus an output file
name, and returns a single PDF containing a semi-major-axis (SMA) vs. epoch
plot for each requested satellite, covering the last 90 days of available
data.

Data source: [Space-Track.org](https://www.space-track.org) REST API
(`gp` and `gp_history` classes).

---

## 2. Tech Stack

- **Language:** Python 3.11+
- **Space-Track client:** `spacetrack` (python-spacetrack)
- **Storage:** SQLite (single file, no server)
- **Plotting:** `matplotlib`, export via `matplotlib.backends.backend_pdf.PdfPages`
- **Telegram bot framework:** `python-telegram-bot` (async, v20+)
- **Scheduling / freshness checks:** no external cron needed — freshness is
  checked on-demand at request time (see §5)

---

## 3. Space-Track API Rules (must be respected)

These are hard constraints from Space-Track's terms of use, not
suggestions:

| Rule | Detail |
|---|---|
| `gp_history` rate limit | **1 request per object, per lifetime.** Never re-query history for an ID once it has been backfilled. Treat as a one-time seed operation only. |
| `gp` class | Used for *current* elements only. Safe to poll repeatedly (normal rate limits apply — batch requests, don't loop per-ID). |
| Batching | Always batch multiple NORAD IDs into a single request using a comma-separated `NORAD_CAT_ID` list. Never issue one HTTP request per ID. |
| Bulk / large historical downloads | Not needed for this app (per-request ID lists are small), but if ever required, use Space-Track's yearly bulk zip files instead of `gp_history`. |
| Storage | Once fetched, history must be cached locally (SQLite) and never re-fetched. This app's entire local-cache design exists to satisfy this requirement. |
| Auth | Session/cookie-based login (`identity` + `password`), handled by the `spacetrack` library. Store credentials in environment variables, never in code. |

---

## 4. Data Model (SQLite)

### Table: `satellites`
| column | type | notes |
|---|---|---|
| `norad_cat_id` | INTEGER PRIMARY KEY | |
| `history_backfilled` | BOOLEAN | set `TRUE` once `gp_history` has been called for this ID — enforces the 1/lifetime rule |
| `last_fetch_at` | DATETIME | UTC timestamp of the last successful `gp` (current data) fetch for this ID |

### Table: `sma_history`
| column | type | notes |
|---|---|---|
| `norad_cat_id` | INTEGER | FK → satellites |
| `epoch` | DATETIME | UTC, from Space-Track `EPOCH` field |
| `semimajor_axis` | REAL | km, from Space-Track `SEMIMAJOR_AXIS` field |
| — | | `PRIMARY KEY (norad_cat_id, epoch)` — naturally deduplicates repeated epochs |

---

## 5. Main Bot Activity Flow

**Trigger:** user sends a message/command containing a list of NORAD
catalog IDs and a desired output file name (e.g.
`/plot 25544,43013,48274 my_report`).

For each requested ID, apply this per-ID logic, then batch the resulting
API calls:

1. **Look up `norad_cat_id` in `satellites` table.**

2. **Case A — no row exists (never seen this ID before):**
   - Mark it for a **history backfill**: fetch last 3 months via `gp_history`.
   - After fetching, insert a row into `satellites` with
     `history_backfilled = TRUE` and `last_fetch_at = now()`.
   - Insert all returned epochs into `sma_history`.

3. **Case B — row exists, `last_fetch_at` is more than 1 hour ago:**
   - Mark it for a **current-data fetch** via `gp` (not `gp_history` —
     the lifetime limit forbids re-calling history for an ID already
     backfilled).
   - After fetching, upsert the new epoch into `sma_history` (ignore if the
     epoch already exists — `INSERT OR IGNORE` due to the composite PK).
   - Update `last_fetch_at = now()`.

4. **Case C — row exists, `last_fetch_at` is within the last hour:**
   - No fetch needed. Use cached data as-is.

5. **Batching:**
   - Group all IDs falling into Case A into a single `gp_history` request
     (comma-separated `NORAD_CAT_ID` list, `orderby=NORAD_CAT_ID,EPOCH asc`).
   - Group all IDs falling into Case B into a single `gp` request
     (comma-separated `NORAD_CAT_ID` list).
   - Case C IDs require no request at all.
   - This means **at most 2 Space-Track API calls per user request**,
     regardless of how many IDs were submitted.

6. **Build the plot:**
   - Query `sma_history` for all requested IDs, epochs within the last 90
     days.
   - For each ID, plot SMA (km) vs. epoch as a line/scatter chart, one
     subplot (or one page) per satellite, in the order the user supplied
     the IDs.
   - Label each subplot with the NORAD ID (and satellite name if available
     from the API response).
   - Export all subplots into a single multi-page PDF using
     `PdfPages(filename)`.

7. **Respond in Telegram:**
   - Send the generated PDF back to the user using the file name they
     provided (sanitize it: strip path separators, enforce `.pdf`
     extension).
   - If any requested ID returned no data at all (invalid ID, or
     Space-Track has nothing for it), note this in a text reply alongside
     the PDF rather than failing the whole request.

---

## 6. Module Layout

```
sma_bot/
├── bot.py                 # Telegram handlers, entry point
├── spacetrack_client.py   # gp / gp_history wrappers, batching logic
├── db.py                  # SQLite schema + queries (satellites, sma_history)
├── plotting.py            # SMA plot generation → PDF
├── config.py               # env var loading (credentials, DB path, bot token)
└── requirements.txt
```

### `spacetrack_client.py` — required functions
- `fetch_history(norad_ids: list[int], months: int = 3) -> list[dict]`
  Calls `gp_history` once for the given batch. Caller is responsible for
  only passing IDs that have never been backfilled.
- `fetch_current(norad_ids: list[int]) -> list[dict]`
  Calls `gp` once for the given batch.

### `db.py` — required functions
- `get_satellite_status(norad_id: int) -> SatelliteStatus | None`
- `mark_backfilled(norad_id: int, fetched_at: datetime)`
- `update_last_fetch(norad_id: int, fetched_at: datetime)`
- `insert_sma_points(norad_id: int, points: list[(epoch, sma)])`
- `get_sma_history(norad_ids: list[int], since: datetime) -> dict[int, list[(epoch, sma)]]`

### `plotting.py` — required functions
- `generate_pdf(data: dict[int, list[(epoch, sma)]], output_path: str, id_order: list[int])`

---

## 7. Configuration / Secrets

Load from environment variables (e.g. via `.env` + `python-dotenv`):

| variable | purpose |
|---|---|
| `SPACETRACK_IDENTITY` | Space-Track account email |
| `SPACETRACK_PASSWORD` | Space-Track account password |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token |
| `SMA_DB_PATH` | path to SQLite file (default `./sma_bot.db`) |

---

## 8. Non-Goals / Explicit Constraints

- Do **not** implement a background/cron job that polls `gp_history`
  repeatedly — history is fetched exactly once per ID, on first sighting.
- Do **not** issue per-ID HTTP requests in a loop — always batch.
- Do **not** re-fetch `gp` data more than once per hour per ID, even if the
  same ID appears in multiple simultaneous user requests — check
  `last_fetch_at` before adding an ID to the batch.
- Plot window is fixed at the **last 90 days** of cached data, regardless
  of how far back the local history extends.
- Invalid/unknown NORAD IDs should be skipped and logged.
- There will be only one user for bot
- Max number of IDs per request - 50
