from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import json
import logging

from spacetrack import SpaceTrackClient
import spacetrack.operators as op

from sma_bot.config import SPACETRACK_IDENTITY, SPACETRACK_PASSWORD

logger = logging.getLogger(__name__)


@dataclass
class SpaceTrackRecord:
    norad_cat_id: int
    object_name: str | None
    epoch: datetime
    semimajor_axis: float


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize(results) -> list[SpaceTrackRecord]:
    if not results:
        return []
    if isinstance(results, str):
        results = json.loads(results)
    if isinstance(results, dict):
        results = [results]
    return [
        SpaceTrackRecord(
            norad_cat_id=int(r["NORAD_CAT_ID"]),
            object_name=r.get("OBJECT_NAME"),
            epoch=_parse_iso(r["EPOCH"]),
            semimajor_axis=float(r["SEMIMAJOR_AXIS"]),
        )
        for r in results
    ]


def _get_client() -> SpaceTrackClient:
    return SpaceTrackClient(SPACETRACK_IDENTITY, SPACETRACK_PASSWORD)


def fetch_history(norad_ids: list[int], months: int = 3) -> list[SpaceTrackRecord]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    client = _get_client()
    try:
        results = client.gp_history(
            norad_cat_id=norad_ids,
            epoch=op.greater_than(cutoff),
            orderby="norad_cat_id,epoch",
        )
        records = _normalize(results)
        logger.info("gp_history returned %d records for %d IDs", len(records), len(norad_ids))
        return records
    except Exception:
        logger.exception("gp_history request failed for %s", norad_ids)
        return []
    finally:
        client.close()


def fetch_current(norad_ids: list[int]) -> list[SpaceTrackRecord]:
    client = _get_client()
    try:
        results = client.gp(
            norad_cat_id=norad_ids,
        )
        records = _normalize(results)
        logger.info("gp returned %d records for %d IDs", len(records), len(norad_ids))
        return records
    except Exception:
        logger.exception("gp request failed for %s", norad_ids)
        return []
    finally:
        client.close()
