import asyncio
import logging

from sma_bot import db, spacetrack_client as stc
from sma_bot.service import SatelliteService, ActualizeStatus

logger = logging.getLogger(__name__)

CRON_DELAY_SECONDS = 2


async def actualize_all(context):
    service = SatelliteService(db, stc)
    sat_ids = service.get_all_sat_ids()
    if not sat_ids:
        logger.info("Cron: no satellites in DB to actualize")
        return

    logger.info("Cron: starting actualization of %d satellite(s)", len(sat_ids))
    counts = {s: 0 for s in ActualizeStatus}

    loop = asyncio.get_event_loop()
    for i, sat_id in enumerate(sat_ids):
        results = await loop.run_in_executor(None, service.actualize, [sat_id])
        for r in results:
            counts[r.status] += 1
        if i < len(sat_ids) - 1:
            await asyncio.sleep(CRON_DELAY_SECONDS)

    logger.info(
        "Cron: done — %d new, %d refreshed, %d cached, %d not found (total %d)",
        counts[ActualizeStatus.New],
        counts[ActualizeStatus.Refreshed],
        counts[ActualizeStatus.Cached],
        counts[ActualizeStatus.NotFound],
        len(sat_ids),
    )
