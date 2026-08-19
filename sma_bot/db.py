import sqlite3
from datetime import datetime
from dataclasses import dataclass
from sma_bot.config import SMA_DB_PATH


@dataclass
class Satellite:
    norad_cat_id: int
    history_backfilled: bool = False
    last_fetch_at: datetime | None = None
    object_name: str | None = None


@dataclass
class SmaHistoryEntry:
    epoch: datetime
    semimajor_axis: float


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SMA_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS satellites (
            norad_cat_id INTEGER PRIMARY KEY,
            history_backfilled BOOLEAN NOT NULL DEFAULT 0,
            last_fetch_at DATETIME,
            object_name TEXT
        );

        CREATE TABLE IF NOT EXISTS sma_history (
            norad_cat_id INTEGER NOT NULL,
            epoch DATETIME NOT NULL,
            semimajor_axis REAL NOT NULL,
            PRIMARY KEY (norad_cat_id, epoch),
            FOREIGN KEY (norad_cat_id) REFERENCES satellites(norad_cat_id)
        );
    """)
    try:
        conn.execute("ALTER TABLE satellites ADD COLUMN object_name TEXT")
    except sqlite3.OperationalError:
        pass
    conn.close()


def get_all_satellite_ids() -> list[int]:
    conn = _connect()
    rows = conn.execute("SELECT norad_cat_id FROM satellites").fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_satellite(norad_id: int) -> Satellite | None:
    conn = _connect()
    row = conn.execute(
        "SELECT norad_cat_id, history_backfilled, last_fetch_at, object_name FROM satellites WHERE norad_cat_id = ?",
        (norad_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return Satellite(
        norad_cat_id=row[0],
        history_backfilled=bool(row[1]),
        last_fetch_at=datetime.fromisoformat(row[2]) if row[2] else None,
        object_name=row[3],
    )


def insert_satellite(sat: Satellite):
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO satellites (norad_cat_id, history_backfilled, last_fetch_at, object_name) VALUES (?, ?, ?, ?)",
        (sat.norad_cat_id, sat.history_backfilled, sat.last_fetch_at.isoformat() if sat.last_fetch_at else None, sat.object_name),
    )
    conn.commit()
    conn.close()


def insert_sma_points(norad_id: int, points: list[SmaHistoryEntry]):
    conn = _connect()
    conn.executemany(
        "INSERT OR IGNORE INTO sma_history (norad_cat_id, epoch, semimajor_axis) VALUES (?, ?, ?)",
        [(norad_id, p.epoch.isoformat(), p.semimajor_axis) for p in points],
    )
    conn.commit()
    conn.close()


def get_sma_history(norad_ids: list[int], since: datetime) -> dict[int, list[SmaHistoryEntry]]:
    conn = _connect()
    result: dict[int, list[SmaHistoryEntry]] = {}
    for nid in norad_ids:
        rows = conn.execute(
            "SELECT epoch, semimajor_axis FROM sma_history WHERE norad_cat_id = ? AND epoch >= ? ORDER BY epoch",
            (nid, since.isoformat()),
        ).fetchall()
        result[nid] = [SmaHistoryEntry(epoch=datetime.fromisoformat(r[0]), semimajor_axis=r[1]) for r in rows]
    conn.close()
    return result
