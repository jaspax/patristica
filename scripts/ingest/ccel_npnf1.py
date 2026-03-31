"""
Ingestor for CCEL Nicene & Post-Nicene Fathers Series 1 (NPNF1), 14 volumes.

Source: https://ccel.org/ccel/s/schaff/npnf1{01-14}.xml
License: Public domain (19th-century English translations)
Language: English (eng)

Each volume is downloaded as ThML XML and split into one Work per <div1>.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._ccel_common import download_volume, parse_thml_volume

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/ccel-npnf1"

# NPNF Series 1 volumes 1–14
_VOLUMES = [f"npnf1{i:02d}" for i in range(1, 15)]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and ingest all NPNF1 volumes.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      Re-download and re-parse even if output already exists.
    """
    cache_dir = output_dir / "patristic" / "ccel-npnf1"
    cache_dir.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []

    for volume_id in tqdm(_VOLUMES, desc="CCEL NPNF1 volumes"):
        vol_num = int(volume_id[5:])
        volume_label = f"NPNF Series 1 Vol. {vol_num}"

        xml_path = download_volume(volume_id, cache_dir, force=force)

        for work, paragraphs in parse_thml_volume(
            xml_path,
            source_id=SOURCE_ID,
            volume_id=volume_id,
            volume_label=volume_label,
        ):
            out_path = cache_dir / volume_id / f"{work.work_id.split('/')[-1]}.json"

            if out_path.exists() and not force:
                try:
                    saved = json.loads(out_path.read_text(encoding="utf-8"))
                    works.append(Work(**saved["work"]))
                except Exception:
                    pass
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"work": work.model_dump(), "paragraphs": paragraphs}
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            works.append(work)

    log.info("CCEL NPNF1 ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
