"""
Ingestor for CCEL Ante-Nicene Fathers (ANF), 10 volumes.

Source: https://ccel.org/ccel/s/schaff/anf{01-10}.xml
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

SOURCE_ID = "patristic/ccel-anf"

# ANF volumes 1–10
_VOLUMES = [f"anf{i:02d}" for i in range(1, 11)]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and ingest all ANF volumes.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      Re-download and re-parse even if output already exists.
    """
    cache_dir = output_dir / "patristic" / "ccel-anf"
    cache_dir.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []

    for volume_id in tqdm(_VOLUMES, desc="CCEL ANF volumes"):
        vol_num = int(volume_id[3:])
        volume_label = f"ANF Vol. {vol_num}"

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

    log.info("CCEL ANF ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
