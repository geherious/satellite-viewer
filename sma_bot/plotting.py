import tempfile
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from sma_bot.db import SmaHistoryEntry

EARTH_RADIUS_KM = 6378.137


def generate_pdf(
    data: dict[int, list[SmaHistoryEntry]],
    output_path: str,
    id_order: list[int],
    sat_names: dict[int, str] | None = None,
) -> str | None:
    tmp_path = os.path.join(tempfile.gettempdir(), output_path)
    pdf = PdfPages(tmp_path)
    successful = 0

    for nid in id_order:
        entries = data.get(nid, [])
        if not entries:
            continue

        epochs = [e.epoch for e in entries]
        altitudes = [e.semimajor_axis - EARTH_RADIUS_KM for e in entries]
        name = sat_names.get(nid, str(nid)) if sat_names else str(nid)

        fig, ax = plt.subplots(figsize=(12, 5))
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
