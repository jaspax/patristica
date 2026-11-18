# OCR eval set: Patrologia Graeca (#718)

Ground truth for the OCR pipeline of #705: every engine and stage is scored
against it with `python -m scripts.ocr.eval score`.

- `manifest.csv`: one row per page.
  - `page_id`, `set`, `pg_volume`.
  - `source`: where the transcription came from.
  - `image`: the image's name in the source.
  - `lines`, `chars`.
  - `columns`: Migne column numbers of the running heads, `|`-separated, where known.
  - `status`: `checked`, or `draft` while it awaits checking. `score` uses only `checked` pages.
  - `ogl_scan` / `ogl_stem` / `ogl_containment`: the OGL page found by `baseline`.
  - `note`.
- `gt/{page_id}.txt`: the page's Greek main text, one printed line per line, diplomatic: as printed, with line-end hyphens, Migne's accents and his misprints.

Images and engine outputs aren't tracked. They are in `data/cache/ocr_eval/` (`images/`, `hyp/{engine}/`). `build` rewrites the Calfa rows, their files and their images from the Zenodo download (cached in `data/cache/ocr_eval/zenodo/`).

## Calfa (`calfa-v2`, 266 pages)

The pages are hand-checked transcriptions of PG pages by Calfa (Chahan Vidal-Gorène et al.), from *Patrologia Graeca (OCR ground truth)*, [Zenodo 20008699](https://zenodo.org/records/20008699), `data-v2.zip`, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The text is taken from the transcribed regions, with Latin columns and empty layout regions left out.

Columns by volume:
- PG 35: Gregory Nazianzen, *Orationes* 1–4, columns 396–719 (158 pages).
- PG 145: 68 pages.
- PG 2, 17, 87, 89, 98, 99, 114 and 127: 40 pages between them.

The archive's `data.zip` (v1) repeats these transcriptions. Its 34 full-page `PG…` files, and v1's `task1`, have layout regions but no text, so they aren't used here.

Each image is a column crop. It has no running head, so these pages have no `columns`.

## Our own pages (`ours`)

Our own pages are ~30 hole pages of PG 75 and two volumes of other print quality, with running heads. They are added by hand once their images can be fetched (#719); tracked on #739.

For each page:
- add a manifest row (`set` `ours`, `status` `draft`, `columns`, and the IA image URL in `source`);
- add its `gt/ours-….txt` file;
- set `status` to `checked` after a line-by-line check against the image.
