"""Results of per-work checks kept while their input files are unchanged (#782).

A no-op ``scripts.anchor`` or ``scripts.embed`` pass reads and hashes the
whole corpus to find nothing to do, and the pipeline and ``scripts.status``
each run such a pass several times. A :class:`StatCache` keeps one value per
key (a work id) with the stat of each file it was computed from and a
caller-supplied *head* (the code and settings that decided it); while both
match, the value is reused without reading the files.

The rules are build_index's input-hash cache (#607): a file's stamp is its
size, mtime, ctime and inode, so a rewrite or rename is seen even when a tool
puts the old mtime back; a file changed within the last :data:`RACY_SECONDS`
isn't cached, since timestamps are coarse; the cache is local (``data/cache/``,
gitignored), saved atomically, and never fails a run. Take the stamps
*before* reading the files, so a file changed while it was read is seen as
changed next time.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: A file changed this recently isn't cached (ext4 timestamps tick every few ms).
RACY_SECONDS = 2.0

Stamps = list[list[int] | None]


def file_stamps(files: Iterable[Path]) -> Stamps:
    """``[size, mtime_ns, ctime_ns, inode]`` per file, ``None`` for a missing one."""
    stamps: Stamps = []
    for path in files:
        try:
            st = path.stat()
        except FileNotFoundError:
            stamps.append(None)
            continue
        stamps.append([st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino])
    return stamps


def cache_dir(data_dir: Path) -> Path:
    """The cache directory beside a data directory (``data/normalized`` → ``data/cache``)."""
    return data_dir.parent / "cache"


class StatCache:
    """``key → value`` while the key's file stamps and the cache's *head* match.

    A *path* of ``None`` caches nothing. A cache written under another *head*
    (other code or settings) starts empty.
    """

    VERSION = 1

    def __init__(self, path: Path | None, head: str) -> None:
        self.path = path
        self.head = head
        self.entries: dict[str, dict[str, Any]] = {}
        self.dirty = False
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("%s: unreadable cache, starting afresh (%s)", path, e)
            return
        if (not isinstance(data, dict) or data.get("version") != self.VERSION
                or data.get("head") != head):
            return
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            return
        self.entries = {
            key: entry for key, entry in entries.items()
            if isinstance(entry, dict) and "value" in entry
            and isinstance(entry.get("files"), list)
            and all(stamp is None or (
                isinstance(stamp, list) and len(stamp) == 4
                and all(type(value) is int for value in stamp)
            ) for stamp in entry["files"])
        }

    def get(self, key: str, stamps: Stamps, tag: object = None) -> Any | None:
        """The value stored for *key* with these *stamps* and *tag*, else None."""
        e = self.entries.get(key)
        if e is not None and e["files"] == stamps and e.get("tag") == tag:
            return e["value"]
        return None

    def put(self, key: str, stamps: Stamps, value: Any, tag: object = None) -> None:
        """Store *value* (JSON data) for *key*; dropped when a file changed too recently."""
        if self.path is None:
            return
        racy = time.time_ns() - int(RACY_SECONDS * 1e9)
        if any(s is not None and max(s[1], s[2]) > racy for s in stamps):
            self.forget(key)
            return
        self.entries[key] = {"files": stamps, "tag": tag, "value": value}
        self.dirty = True

    def forget(self, key: str) -> None:
        if self.entries.pop(key, None) is not None:
            self.dirty = True

    def save(self) -> None:
        """Write the cache atomically; a failure is logged, never raised.

        Concurrent runs each rename their own temporary file into place: the
        last one wins, and the other's new entries are computed again next time.
        """
        if self.path is None or not self.dirty:
            return
        tmp: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.",
                                       suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": self.VERSION, "head": self.head, "entries": self.entries},
                          f, separators=(",", ":"))
            os.replace(tmp, self.path)
            tmp = None
            self.dirty = False
        except OSError as e:
            log.warning("%s: could not save the cache (%s)", self.path, e)
        finally:
            if tmp is not None:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except OSError:
                    pass
