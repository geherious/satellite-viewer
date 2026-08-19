import logging
from enum import StrEnum
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sma_bot.db import Satellite

logger = logging.getLogger(__name__)

FRESHNESS_HOURS = 11


class ActualizeStatus(StrEnum):
    Cached = "cached"
    Refreshed = "refreshed"
    New = "new"
    NotFound = "not_found"


@dataclass
class ActualizeResult:
    sat_id: int
    status: ActualizeStatus


class SatelliteService:
    def __init__(self, db_module, spacetrack_module):
        self._db = db_module
        self._stc = spacetrack_module

    def get_all_sat_ids(self) -> list[int]:
        return self._db.get_all_satellite_ids()

    def actualize(self, sat_ids: list[int]) -> list[ActualizeResult]:
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=FRESHNESS_HOURS)

        new_ids: list[int] = []
        refresh_ids: list[int] = []
        cached_ids: list[int] = []

        for nid in sat_ids:
            sat = self._db.get_satellite(nid)
            if sat is None:
                new_ids.append(nid)
            elif sat.last_fetch_at is None or sat.last_fetch_at < one_hour_ago:
                refresh_ids.append(nid)
            else:
                cached_ids.append(nid)

        results: dict[int, ActualizeResult] = {}

        if new_ids:
            records = self._stc.fetch_history(new_ids)
            sats, points = self._extract_entities(records)
            for nid in new_ids:
                pts = points.get(nid, [])
                if pts:
                    sat = sats.get(nid, Satellite(norad_cat_id=nid))
                    sat.history_backfilled = True
                    sat.last_fetch_at = now
                    self._db.insert_satellite(sat)
                    self._db.insert_sma_points(nid, pts)
                    results[nid] = ActualizeResult(nid, ActualizeStatus.New)
                else:
                    results[nid] = ActualizeResult(nid, ActualizeStatus.NotFound)
                    logger.warning("No history data for ID %d", nid)

        if refresh_ids:
            records = self._stc.fetch_current(refresh_ids)
            sats, points = self._extract_entities(records)
            for nid in refresh_ids:
                pts = points.get(nid, [])
                if pts:
                    existing = self._db.get_satellite(nid) or Satellite(norad_cat_id=nid)
                    existing.last_fetch_at = now
                    if sats.get(nid) and sats[nid].object_name:
                        existing.object_name = sats[nid].object_name
                    self._db.insert_satellite(existing)
                    self._db.insert_sma_points(nid, pts)
                    results[nid] = ActualizeResult(nid, ActualizeStatus.Refreshed)
                else:
                    results[nid] = ActualizeResult(nid, ActualizeStatus.NotFound)
                    logger.warning("No current data for ID %d", nid)

        for nid in cached_ids:
            results[nid] = ActualizeResult(nid, ActualizeStatus.Cached)

        return [results[nid] for nid in sat_ids]

    @staticmethod
    def _extract_entities(records):
        from sma_bot.db import SmaHistoryEntry

        sats: dict[int, Satellite] = {}
        points: dict[int, list[SmaHistoryEntry]] = {}
        for rec in records:
            nid = rec.norad_cat_id
            if nid not in sats:
                sats[nid] = Satellite(norad_cat_id=nid)
            if rec.object_name:
                sats[nid].object_name = rec.object_name
            points.setdefault(nid, []).append(SmaHistoryEntry(
                epoch=rec.epoch,
                semimajor_axis=rec.semimajor_axis,
            ))
        return sats, points
