"""Tests for scripts.ingest._common utilities."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts.ingest._common import (
    clean_html,
    download_file,
    parse_osis,
    parse_tei,
    parse_usfm,
    slugify_ref,
)


# ---------------------------------------------------------------------------
# slugify_ref
# ---------------------------------------------------------------------------

class TestSlugifyRef:
    def test_passthrough_clean(self):
        assert slugify_ref("Gen.1.1") == "Gen.1.1"
        assert slugify_ref("Aug.Conf.1.1.1") == "Aug.Conf.1.1.1"
        assert slugify_ref("Nicaea1.Canon.7") == "Nicaea1.Canon.7"

    def test_strips_whitespace(self):
        assert slugify_ref("  Gen.1.1  ") == "Gen.1.1"

    def test_collapses_spaces_around_dots(self):
        assert slugify_ref("Gen . 1 . 1") == "Gen.1.1"

    def test_strips_invalid_characters(self):
        assert slugify_ref("Gen!1@1") == "Gen11"

    def test_collapses_double_dots(self):
        assert slugify_ref("Gen..1..1") == "Gen.1.1"

    def test_strips_leading_trailing_dots(self):
        assert slugify_ref(".Gen.1.1.") == "Gen.1.1"

    def test_empty_string(self):
        assert slugify_ref("") == ""


# ---------------------------------------------------------------------------
# clean_html
# ---------------------------------------------------------------------------

class TestCleanHtml:
    def test_strips_tags(self):
        result = clean_html("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_normalizes_whitespace(self):
        result = clean_html("<p>Hello\n\n\nworld</p>")
        assert "\n" not in result
        assert "  " not in result

    def test_removes_script(self):
        result = clean_html("<p>text</p><script>evil()</script>")
        assert "evil" not in result
        assert "text" in result

    def test_removes_style(self):
        result = clean_html("<style>body{color:red}</style><p>text</p>")
        assert "color" not in result
        assert "text" in result

    def test_plain_text_passthrough(self):
        result = clean_html("plain text")
        assert result == "plain text"

    def test_entities_decoded(self):
        result = clean_html("<p>Conf&eacute;rence</p>")
        assert "Confé" in result or "Conference" in result  # lxml decodes entities


# ---------------------------------------------------------------------------
# parse_usfm
# ---------------------------------------------------------------------------

SAMPLE_USFM = textwrap.dedent("""\
    \\id GEN
    \\h Genesis
    \\mt Genesis
    \\c 1
    \\v 1 In the beginning God created the heavens and the earth.
    \\v 2 The earth was formless and empty.
    \\c 2
    \\v 1 Thus the heavens and the earth were completed.
""")


class TestParseUsfm:
    def test_book_id(self, tmp_path):
        f = tmp_path / "gen.usfm"
        f.write_text(SAMPLE_USFM)
        meta, verses = parse_usfm(f)
        assert meta["book_id"] == "GEN"

    def test_title(self, tmp_path):
        f = tmp_path / "gen.usfm"
        f.write_text(SAMPLE_USFM)
        meta, verses = parse_usfm(f)
        assert meta["title"] == "Genesis"

    def test_verse_count(self, tmp_path):
        f = tmp_path / "gen.usfm"
        f.write_text(SAMPLE_USFM)
        _, verses = parse_usfm(f)
        assert len(verses) == 3

    def test_verse_refs(self, tmp_path):
        f = tmp_path / "gen.usfm"
        f.write_text(SAMPLE_USFM)
        _, verses = parse_usfm(f)
        refs = [r for r, _ in verses]
        assert refs == ["GEN.1.1", "GEN.1.2", "GEN.2.1"]

    def test_verse_text(self, tmp_path):
        f = tmp_path / "gen.usfm"
        f.write_text(SAMPLE_USFM)
        _, verses = parse_usfm(f)
        assert verses[0][1] == "In the beginning God created the heavens and the earth."

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.usfm"
        f.write_text("")
        meta, verses = parse_usfm(f)
        assert verses == []


# ---------------------------------------------------------------------------
# parse_tei
# ---------------------------------------------------------------------------

SAMPLE_TEI = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title>Confessions</title>
            <author>Augustine of Hippo</author>
          </titleStmt>
          <publicationStmt>
            <publisher>CCEL</publisher>
            <date>2000</date>
          </publicationStmt>
        </fileDesc>
        <profileDesc>
          <langUsage>
            <language ident="lat">Latin</language>
          </langUsage>
        </profileDesc>
      </teiHeader>
      <text>
        <body>
          <div type="book" n="1">
            <p>Fecisti nos ad te et inquietum est cor nostrum.</p>
            <p>Magnus es domine et laudabilis valde.</p>
          </div>
        </body>
      </text>
    </TEI>
""")


class TestParseTei:
    def test_title(self, tmp_path):
        f = tmp_path / "conf.xml"
        f.write_text(SAMPLE_TEI)
        meta, _ = parse_tei(f)
        assert meta["title"] == "Confessions"

    def test_author(self, tmp_path):
        f = tmp_path / "conf.xml"
        f.write_text(SAMPLE_TEI)
        meta, _ = parse_tei(f)
        assert meta["author"] == "Augustine of Hippo"

    def test_publisher(self, tmp_path):
        f = tmp_path / "conf.xml"
        f.write_text(SAMPLE_TEI)
        meta, _ = parse_tei(f)
        assert meta["publisher"] == "CCEL"

    def test_paragraph_count(self, tmp_path):
        f = tmp_path / "conf.xml"
        f.write_text(SAMPLE_TEI)
        _, paragraphs = parse_tei(f)
        assert len(paragraphs) == 2

    def test_paragraph_text(self, tmp_path):
        f = tmp_path / "conf.xml"
        f.write_text(SAMPLE_TEI)
        _, paragraphs = parse_tei(f)
        assert "Fecisti nos" in paragraphs[0]

    def test_missing_optional_fields(self, tmp_path):
        minimal = textwrap.dedent("""\
            <?xml version="1.0"?>
            <TEI xmlns="http://www.tei-c.org/ns/1.0">
              <teiHeader><fileDesc><titleStmt><title>X</title></titleStmt>
              <publicationStmt><p>pub</p></publicationStmt></fileDesc></teiHeader>
              <text><body><p>Hello</p></body></text>
            </TEI>
        """)
        f = tmp_path / "min.xml"
        f.write_text(minimal)
        meta, paragraphs = parse_tei(f)
        assert meta["author"] is None
        assert paragraphs == ["Hello"]


# ---------------------------------------------------------------------------
# parse_osis
# ---------------------------------------------------------------------------

SAMPLE_OSIS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
      <osisText osisIDWork="Gen">
        <header>
          <work osisWork="Gen">
            <title>Genesis</title>
            <language>hbo</language>
            <description>Open Scriptures Hebrew Bible</description>
          </work>
        </header>
        <div type="book" osisID="Gen">
          <chapter osisID="Gen.1">
            <verse osisID="Gen.1.1">בְּרֵאשִׁית בָּרָא אֱלֹהִים</verse>
            <verse osisID="Gen.1.2">וְהָאָרֶץ הָיְתָה תֹהוּ</verse>
          </chapter>
        </div>
      </osisText>
    </osis>
""")


class TestParseOsis:
    def test_title(self, tmp_path):
        f = tmp_path / "gen.xml"
        f.write_text(SAMPLE_OSIS)
        meta, _ = parse_osis(f)
        assert meta["title"] == "Genesis"

    def test_language(self, tmp_path):
        f = tmp_path / "gen.xml"
        f.write_text(SAMPLE_OSIS)
        meta, _ = parse_osis(f)
        assert meta["language"] == "hbo"

    def test_verse_count(self, tmp_path):
        f = tmp_path / "gen.xml"
        f.write_text(SAMPLE_OSIS)
        _, verses = parse_osis(f)
        assert len(verses) == 2

    def test_verse_refs(self, tmp_path):
        f = tmp_path / "gen.xml"
        f.write_text(SAMPLE_OSIS)
        _, verses = parse_osis(f)
        assert verses[0][0] == "Gen.1.1"
        assert verses[1][0] == "Gen.1.2"

    def test_verse_text(self, tmp_path):
        f = tmp_path / "gen.xml"
        f.write_text(SAMPLE_OSIS)
        _, verses = parse_osis(f)
        assert "בְּרֵאשִׁית" in verses[0][1]


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------

class TestDownloadFile:
    def _make_response(self, content: bytes, status: int = 200, etag: str | None = None) -> httpx.Response:
        headers = {}
        if etag:
            headers["etag"] = etag
        request = httpx.Request("GET", "https://example.com/file.txt")
        return httpx.Response(status_code=status, content=content, headers=headers, request=request)

    def test_downloads_new_file(self, tmp_path, mocker):
        dest = tmp_path / "file.txt"
        mock_get = mocker.patch("httpx.Client.get", return_value=self._make_response(b"hello"))
        result = download_file("https://example.com/file.txt", dest)
        assert result == dest
        assert dest.read_bytes() == b"hello"
        mock_get.assert_called_once()

    def test_skips_existing_file_no_etag(self, tmp_path, mocker):
        dest = tmp_path / "file.txt"
        dest.write_bytes(b"cached")
        mock_get = mocker.patch("httpx.Client.get")
        result = download_file("https://example.com/file.txt", dest, etag_cache=False)
        assert result == dest
        assert dest.read_bytes() == b"cached"
        mock_get.assert_not_called()

    def test_saves_etag_sidecar(self, tmp_path, mocker):
        dest = tmp_path / "file.txt"
        mocker.patch("httpx.Client.get", return_value=self._make_response(b"data", etag='"abc123"'))
        download_file("https://example.com/file.txt", dest)
        etag_path = dest.with_suffix(dest.suffix + ".etag")
        assert etag_path.exists()
        assert etag_path.read_text() == '"abc123"'

    def test_sends_if_none_match_when_etag_cached(self, tmp_path, mocker):
        dest = tmp_path / "file.txt"
        dest.write_bytes(b"old content")
        etag_path = dest.with_suffix(dest.suffix + ".etag")
        etag_path.write_text('"old-etag"')
        mock_get = mocker.patch("httpx.Client.get", return_value=self._make_response(b"new content", etag='"new-etag"'))
        download_file("https://example.com/file.txt", dest)
        call_headers = mock_get.call_args[1].get("headers") or mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else mock_get.call_args.kwargs.get("headers", {})
        assert call_headers.get("If-None-Match") == '"old-etag"'

    def test_304_keeps_cached_file(self, tmp_path, mocker):
        dest = tmp_path / "file.txt"
        dest.write_bytes(b"cached content")
        etag_path = dest.with_suffix(dest.suffix + ".etag")
        etag_path.write_text('"etag"')
        mocker.patch("httpx.Client.get", return_value=httpx.Response(status_code=304))
        result = download_file("https://example.com/file.txt", dest)
        assert dest.read_bytes() == b"cached content"

    def test_force_redownloads_existing(self, tmp_path, mocker):
        dest = tmp_path / "file.txt"
        dest.write_bytes(b"old")
        mock_get = mocker.patch("httpx.Client.get", return_value=self._make_response(b"new"))
        download_file("https://example.com/file.txt", dest, force=True)
        assert dest.read_bytes() == b"new"
        mock_get.assert_called_once()

    def test_creates_parent_directories(self, tmp_path, mocker):
        dest = tmp_path / "deep" / "nested" / "file.txt"
        mocker.patch("httpx.Client.get", return_value=self._make_response(b"data"))
        download_file("https://example.com/file.txt", dest)
        assert dest.exists()
