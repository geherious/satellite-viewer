from datetime import datetime, timezone, timedelta
import json
import logging

from spacetrack import SpaceTrackClient
import spacetrack.operators as op

from sma_bot.config import SPACETRACK_IDENTITY, SPACETRACK_PASSWORD

logger = logging.getLogger(__name__)


def _normalize(results) -> list[dict]:
    if not results:
        return []
    if isinstance(results, str):
        results = json.loads(results)
    if isinstance(results, dict):
        results = [results]
    return results


def _get_client() -> SpaceTrackClient:
    return SpaceTrackClient(SPACETRACK_IDENTITY, SPACETRACK_PASSWORD)


def fetch_history(norad_ids: list[int], months: int = 3) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    client = _get_client()
    try:
        results = client.gp_history(
            norad_cat_id=norad_ids,
            epoch=op.greater_than(cutoff),
            orderby="norad_cat_id,epoch",
        )
        results = _normalize(results)
        logger.info("gp_history returned %d records for %d IDs", len(results), len(norad_ids))
        return results
    except Exception:
        logger.exception("gp_history request failed for %s", norad_ids)
        return []
    finally:
        client.close()


def fetch_current(norad_ids: list[int]) -> list[dict]:
    client = _get_client()
    try:
        results = client.gp(
            norad_cat_id=norad_ids,
        )
        results = _normalize(results)
        logger.info("gp returned %d records for %d IDs", len(results), len(norad_ids))
        return results
    except Exception:
        logger.exception("gp request failed for %s", norad_ids)
        return []
    finally:
        client.close()
