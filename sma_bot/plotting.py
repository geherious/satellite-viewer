import tempfile
import os
from datetime import timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from sma_bot.db import Satellite, SmaHistoryEntry

EARTH_RADIUS_KM = 6378.137


def generate_pdf(
    entities: dict[int, tuple[Satellite, list[SmaHistoryEntry]]],
    output_path: str,
    id_order: list[int],
) -> str | None:
    tmp_path = os.path.join(tempfile.gettempdir(), output_path)
    pdf = PdfPages(tmp_path)
    successful = 0

    for nid in id_order:
        sat, entries = entities.get(nid, (Satellite(norad_cat_id=nid), []))
        if not entries:
            continue

        epochs = [e.epoch for e in entries]
        altitudes = [e.semimajor_axis - EARTH_RADIUS_KM for e in entries]
        name = sat.object_name or str(nid)

        fig, ax = plt.subplots(figsize=(12, 5))
        if len(epochs) == 1:
            ax.plot(epochs, altitudes, marker="o", linewidth=1.5, color="black")
            ax.set_xlim(epochs[0] - timedelta(days=1), epochs[0] + timedelta(days=1))
        else:
            ax.plot(epochs, altitudes, linewidth=1.5, color="black")
        ax.set_title(f"{name} — Altitude over Time", fontsize=14)
        ax.set_xlabel("Date (UTC)")
        ax.set_ylabel("Altitude (km)")
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.grid(True, linestyle="--", alpha=0.7)
        fig.autofmt_xdate()
        plt.tight_layout()
        pdf.savefig()
        plt.close()
        successful += 1

    pdf.close()
    if successful == 0:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return None
    return tmp_path
