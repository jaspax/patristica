# Versification mappings

`eng.json`, `lxx.json` and `vul.json` are copied unmodified from the
Copenhagen Alliance versification specification (the standard mappings used
by Paratext):

- Source: https://github.com/Copenhagen-Alliance/versification-specification
  (`versification-mappings/standard-mappings/`, commit `5f3f82f3dc3cfd25fffc6ff04f3630763972258c`)
- Authors: Neil Rees, Reinier de Blois, Mike Lothers, Tim Steenwyk
- License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)

Each file's `mappedVerses` maps references in that scheme onto the "org"
scheme (BHS for the OT, UBS GNT / Nestle-Aland for the NT); unlisted verses
are identical in both.  Two upstream typos in `vul.json` are corrected at load
time in `patristica/versification.py` rather than edited here.
