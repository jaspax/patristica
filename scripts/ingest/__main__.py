"""
Entry point for running a specific ingestor via ``python -m scripts.ingest.NAME``.

Each ingestor module can be invoked directly:

    python -m scripts.ingest.oshb [--output-dir data/raw] [--force]
    python -m scripts.ingest.kjv  [--output-dir data/raw] [--force]

This ``__main__.py`` is the fallback for ``python -m scripts.ingest`` (with no
sub-module); for running all ingestors use ``scripts.ingest.all``.
"""

from scripts.ingest.all import main

main()
