"""
Double-encoded UTF-8 ("mojibake"): UTF-8 bytes read as Latin-1 and encoded again.

Some Perseus Tertullian files (``stoa0275``, #124) have their Greek words, and
a few Latin diaereses, stored this way upstream: ``Î»á½¹Î³Î¿Î½`` for ``λόγον``,
``IsraÃ«l`` for ``Israël``.  Each original character became a run of two to
four characters in U+0080–U+00FF: a UTF-8 lead byte (U+00C2–U+00F4) followed
by its continuation bytes (U+0080–U+00BF).

:func:`repair_double_utf8` decodes such runs back, and only those that are
*provably* double-encoded: a run is replaced only when its Latin-1 bytes are
well-formed UTF-8 as a whole, so ordinary accented text (``é``, ``«``, ``·``)
is left alone.  :data:`MOJIBAKE_RE` is the same pattern, for ``validate.py``.
"""

from __future__ import annotations

import re

#: One or more UTF-8 sequences spelt in Latin-1 characters.
MOJIBAKE_RE = re.compile(
    "(?:"
    "[Â-ß][\u0080-¿]"
    "|[à-ï][\u0080-¿]{2}"
    "|[ð-ô][\u0080-¿]{3}"
    ")+"
)


def _decode(run: str) -> str | None:
    try:
        return run.encode("latin-1").decode("utf-8")
    except UnicodeDecodeError:
        return None


def mojibake_runs(text: str) -> list[str]:
    """The runs of *text* that are double-encoded UTF-8."""
    return [m.group() for m in MOJIBAKE_RE.finditer(text) if _decode(m.group()) is not None]


def repair_double_utf8(text: str) -> str:
    """Decode every double-encoded UTF-8 run in *text*; leave the rest as is."""
    def fix(m: re.Match[str]) -> str:
        decoded = _decode(m.group())
        return m.group() if decoded is None else decoded

    return MOJIBAKE_RE.sub(fix, text)
