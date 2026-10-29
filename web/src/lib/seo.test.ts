import { describe, expect, it } from "vitest";

import { authorMap, type LibraryIndex, type WorkRow } from "./library";
import {
  authorDescription,
  authorJsonLd,
  ROBOTS,
  sitemapEntries,
  workDescription,
  workJsonLd,
  worksOf,
  workTitle,
} from "./seo";
import { person, workRow } from "./testFixtures";

const augustine = person({
  id: "augustine-of-hippo",
  name: "Augustine of Hippo",
  aliases: ["Augustinus", "Aurelius Augustinus"],
  birth: { low: 354, high: 354, confidence: "established" },
  death: { low: 430, high: 430, confidence: "established" },
});
const nobody = person({ id: "nobody", name: "Nobody" });
const authors = authorMap({ authors: [augustine, nobody] });

const conf = workRow({
  id: "first1k/stoa0040.stoa001/conf",
  title: "Confessiones",
  author_ids: ["augustine-of-hippo"],
  language: "lat",
  date: 397,
  date_confidence: "approximate",
  source_id: "first1k",
  license: "cc-by-sa-4.0",
  version_group: "g1",
});
const confEng = workRow({
  id: "npnf1/conf",
  title: "The Confessions",
  author_ids: ["augustine-of-hippo"],
  language: "eng",
  source_id: "npnf1",
  translation_of: conf.id,
  version_group: "g1",
});
const anon = workRow({ id: "x/anon", title: "Anonymous homily", language: "grc", source_id: "x" });

// Scripture: no translation_of links, so the Hebrew is the original.
const book = (source: string, language: string): WorkRow =>
  workRow({ id: `${source}/gen`, title: "Genesis", language, source_id: source, genre: "scripture", version_group: "book:gen" });
const oshb = book("oshb", "hbo");
const kjv = book("kjv", "eng");
const webGen = book("web", "eng");

const index: LibraryIndex = {
  version: "v",
  sources: { first1k: "First1KGreek", npnf1: "NPNF Series 1", oshb: "OSHB", kjv: "KJV", web: "WEB" },
  works: [conf, confEng, anon, oshb, kjv, webGen],
};

describe("workTitle", () => {
  it("names the authors and the language", () => {
    expect(workTitle(conf, authors, index)).toBe("Augustine of Hippo, Confessiones (Latin)");
    expect(workTitle(anon, authors, index)).toBe("Anonymous homily (Greek)");
  });

  it("adds the collection where another version has the same language", () => {
    expect(workTitle(kjv, authors, index)).toBe("Genesis (English, KJV)");
    expect(workTitle(oshb, authors, index)).toBe("Genesis (Hebrew)");
  });
});

describe("workDescription", () => {
  it("says what, by whom, when, from where, and in which other languages", () => {
    expect(workDescription(conf, authors, index)).toBe(
      "Read Confessiones by Augustine of Hippo in Latin (c. 397), from First1KGreek, free on Patristica. Also in English.",
    );
  });

  it("names the language a translation is from", () => {
    expect(workDescription(confEng, authors, index)).toBe(
      "Read The Confessions by Augustine of Hippo in English (translated from the Latin), from NPNF Series 1, " +
        "free on Patristica. Also in Latin.",
    );
  });

  it("lists other languages before another edition in the same one", () => {
    expect(workDescription(kjv, authors, index)).toBe(
      "Read Genesis in English, from KJV, free on Patristica. Also in Hebrew and another English version.",
    );
  });
});

describe("workJsonLd", () => {
  it("links a translation to its original, both ways", () => {
    const original = workJsonLd(conf, authors, index);
    expect(original).toMatchObject({
      "@type": "CreativeWork",
      url: "https://patristica.app/works/first1k/stoa0040.stoa001/conf",
      name: "Confessiones",
      inLanguage: "la",
      author: [{ "@type": "Person", name: "Augustine of Hippo", url: "https://patristica.app/authors/augustine-of-hippo" }],
      license: "https://creativecommons.org/licenses/by-sa/4.0/",
      workTranslation: [{ "@id": "https://patristica.app/works/npnf1/conf", inLanguage: "en" }],
    });
    expect(original).not.toHaveProperty("translationOfWork");
    expect(workJsonLd(confEng, authors, index)).toMatchObject({
      translationOfWork: [{ "@id": "https://patristica.app/works/first1k/stoa0040.stoa001/conf" }],
    });
  });

  it("takes the group's original where there are no links (Scripture)", () => {
    expect(workJsonLd(kjv, authors, index).translationOfWork).toEqual([
      expect.objectContaining({ "@id": "https://patristica.app/works/oshb/gen" }),
    ]);
    const hebrew = workJsonLd(oshb, authors, index);
    expect(hebrew).not.toHaveProperty("translationOfWork");
    expect((hebrew.workTranslation as { name: string }[]).length).toBe(2);
  });

  it("leaves out what a work doesn't have", () => {
    const ld = workJsonLd(anon, authors, index);
    expect(ld.author).toEqual([]);
    expect(ld).not.toHaveProperty("license");
    expect(ld).not.toHaveProperty("workTranslation");
  });
});

describe("authors", () => {
  it("describes an author by dates, works and languages", () => {
    expect(authorDescription(augustine, worksOf(index, augustine.id), "354 – 430")).toBe(
      "Augustine of Hippo (354 – 430): 2 works in Latin and English, free to read on Patristica. " +
        "Also known as Augustinus, Aurelius Augustinus.",
    );
    expect(authorDescription(nobody, [], "")).toBe("Nobody: in the author index of Patristica.");
  });

  it("gives exact years only as JSON-LD dates", () => {
    expect(authorJsonLd(augustine, "d")).toMatchObject({ "@type": "Person", birthDate: "0354", deathDate: "0430" });
    const approximate = person({ id: "a", name: "A", birth: { low: 347, high: 347, confidence: "approximate" } });
    expect(authorJsonLd(approximate, "d")).not.toHaveProperty("birthDate");
  });
});

describe("sitemapEntries", () => {
  it("lists the top-level pages, every work and every author with works", () => {
    const urls = sitemapEntries(index, authors).map((e) => e.url);
    expect(urls.slice(0, 4)).toEqual([
      "https://patristica.app/",
      "https://patristica.app/works",
      "https://patristica.app/authors",
      "https://patristica.app/sources",
    ]);
    expect(urls).toContain("https://patristica.app/works/first1k/stoa0040.stoa001/conf");
    expect(urls).toContain("https://patristica.app/authors/augustine-of-hippo");
    expect(urls).not.toContain("https://patristica.app/authors/nobody");
    expect(urls).toHaveLength(4 + index.works.length + 1);
  });

  it("encodes work ids as the reader's URLs do", () => {
    const odd = workRow({ id: "oglt-pl/anonymus/pl11_0_(cl ρ" });
    const urls = sitemapEntries({ ...index, works: [odd] }, authors).map((e) => e.url);
    expect(urls).toContain("https://patristica.app/works/oglt-pl/anonymus/pl11_0_(cl%20%CF%81");
  });
});

describe("ROBOTS", () => {
  it("keeps crawlers off the API and query strings, and points to the sitemap", () => {
    expect(ROBOTS.rules).toMatchObject({ disallow: ["/api/", "/*?"] });
    expect(ROBOTS.sitemap).toBe("https://patristica.app/sitemap.xml");
  });
});

describe("workDescription of a machine translation (#422)", () => {
  it("says it was machine-translated", () => {
    const mt = workRow({
      id: "mt-eng/conf",
      title: "Confessions",
      author_ids: ["augustine-of-hippo"],
      language: "eng",
      source_id: "mt-eng",
      translation_of: conf.id,
      version_group: "g1",
      machine_translation: true,
    });
    const withMt: LibraryIndex = { ...index, sources: { ...index.sources, "mt-eng": "MT" }, works: [...index.works, mt] };
    expect(workDescription(mt, authors, withMt)).toContain("(machine-translated from the Latin)");
  });
});
