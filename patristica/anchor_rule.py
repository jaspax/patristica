"""Which works get anchored derived verses, and on what (#638).

A rule, not a list (``docs/anchored-derived-verses.md``): ``scripts.anchor``
anchors every work :func:`anchors` names (and that normalize cut as prose),
records the outcome in the work's cut file (``patristica.anchor_store``), also
when the anchored cut didn't win and the work keeps its provisional cut, so
each decision is made once. No numpy, and not part of normalize's code:
normalize applies whatever cut files exist.
"""

from __future__ import annotations

from patristica.sources import OCR_SOURCES


def recorded_anchors(anchors_dir: object) -> dict[str, str]:
    """``{work id: anchor}`` from the cut files in *anchors_dir*."""
    from patristica import anchor_store

    return {cut.work_id: cut.anchor for _, cut in anchor_store.iter_store(anchors_dir)}


def anchors(works: dict[str, dict], recorded: dict[str, str]) -> dict[str, str]:
    """``{work id: anchor}`` for every work the rule anchors (#638).

    *works* maps work ids to their manifest records (``work``), *recorded*
    work ids to the anchor in their cut file.

    - **The preferred edition of a text** (:func:`preferred_edition`): among
      the members of a version group in one language that aren't translations,
      a critical text before OCR'd Migne (``sources.OCR_SOURCES``).
    - **A translation** (``translation_of`` in another language) is anchored on
      its ``translation_of``; when that is an OCR'd edition and the text has a
      critical one, on the preferred edition instead.
    - **Another edition** (no ``translation_of``) that isn't the preferred
      edition of its language in its version group is anchored on it.
    - **A decision on record wins**: a work whose cut file names another
      edition of the text the rule would anchor it on keeps that anchor, and an
      edition already anchored on a member of its group makes that member the
      preferred edition, so a published cut is never re-decided by a
      tie-break (the cut files of #200 were chosen by text similarity).
    """
    from patristica.versions import derive_version_groups

    groups = derive_version_groups(
        {w: rec.get("translation_of") for w, rec in works.items()},
        external_ids={w: rec.get("external_ids", []) for w, rec in works.items()})
    links: dict[str, int] = {}
    for rec in works.values():
        t = rec.get("translation_of")
        if t:
            links[t] = links.get(t, 0) + 1

    def editions(work_id: str, language: str) -> list[str]:
        group = groups.group_of.get(work_id)
        members = groups.members.get(group, (work_id,)) if group else (work_id,)
        return [m for m in members
                if works[m]["language"] == language and not works[m].get("translation_of")]

    out: dict[str, str] = {}
    for wid, rec in works.items():
        target = rec.get("translation_of")
        if target:
            if target not in works or works[target]["language"] == rec["language"]:
                continue
            eds = editions(target, works[target]["language"])
            if recorded.get(wid) in eds:
                out[wid] = recorded[wid]
            elif works[target]["source_id"] in OCR_SOURCES and any(
                    works[m]["source_id"] not in OCR_SOURCES for m in eds):
                out[wid] = preferred_edition(eds, works, recorded, links)
            else:
                out[wid] = target
            continue
        eds = editions(wid, rec["language"])
        if len(eds) < 2:
            continue
        if recorded.get(wid) in eds:
            out[wid] = recorded[wid]
            continue
        pref = preferred_edition(eds, works, recorded, links)
        if pref != wid:
            out[wid] = pref
    return out


def preferred_edition(editions: list[str], works: dict[str, dict], recorded: dict[str, str],
                      links: dict[str, int]) -> str:
    """The edition of a text the others are anchored on: the one *recorded* cut
    files already anchor an edition on, else a critical text before OCR'd
    Migne, then the one most translations point at, then the work id."""
    on_record = {recorded[m] for m in editions if recorded.get(m) in editions}
    if len(on_record) == 1:
        return on_record.pop()
    return max(editions, key=lambda m: (works[m]["source_id"] not in OCR_SOURCES,
                                        links.get(m, 0), m))
