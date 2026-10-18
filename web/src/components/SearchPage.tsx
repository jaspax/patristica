"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { libraryFacets } from "@/lib/filter";
import { LICENSES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";
import { loadLibrary } from "@/lib/library";
import {
  DEFAULT_SEARCH,
  fetchSearch,
  formatRange,
  parseSearchState,
  resultHref,
  searchStateToParams,
  SearchError,
  type SearchResponse,
  type SearchResult,
  type SearchState,
} from "@/lib/search";
import { useLoaded } from "@/lib/useLoaded";

import AuthorLinks from "./AuthorLinks";
import FilterFields, { type FacetValues } from "./FilterFields";
import filterStyles from "./Filters.module.css";
import styles from "./SearchPage.module.css";

/** The pages of results loaded so far, and the state of the latest request. */
type Pages =
  | { status: "loading" | "ready"; pages: SearchResponse[] }
  | { status: "error"; pages: SearchResponse[]; error: SearchError };

export default function SearchPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const query = params.toString();
  const state = useMemo(() => parseSearchState(new URLSearchParams(query)), [query]);
  const key = searchStateToParams(state).toString();

  // Every change is a new history entry, so the back button returns to the previous search.
  const go = (changes: Partial<SearchState>) => {
    const next = searchStateToParams({ ...state, ...changes }).toString();
    router.push(next ? `${pathname}?${next}` : pathname, { scroll: false });
  };

  // Announced to screen readers. It lives here, outside the per-search
  // Results, so the live region exists before its text changes.
  const [status, setStatus] = useState("");
  const searching = state.q.trim() !== "";

  return (
    <div>
      {/* Keyed by the query, so the field shows it after back/forward navigation. */}
      <SearchForm key={state.q} state={state} onChange={go} />
      <p role="status" className="visually-hidden">
        {searching ? status : ""}
      </p>
      {searching ? <Results key={key} state={state} onStatus={setStatus} /> : <Intro />}
    </div>
  );
}

/** What the status region says about the latest request. */
function statusText(pages: Pages): string {
  if (pages.status === "loading") return "Searching…";
  if (pages.status === "error") return ""; // the error is an alert
  const shown = pages.pages.reduce((n, p) => n + p.results.length, 0);
  if (shown === 0) return "No passages found.";
  const more = pages.pages[pages.pages.length - 1]?.next_offset != null;
  return `${shown} ${shown === 1 ? "passage" : "passages"} shown${more ? ", more available" : ""}.`;
}

function SearchForm({ state, onChange }: { state: SearchState; onChange: (c: Partial<SearchState>) => void }) {
  const [draft, setDraft] = useState(state.q);
  const library = useLoaded(loadLibrary);
  const facets = useMemo(
    () => (library.status === "ready" ? libraryFacets(library.data.index, library.data.authors) : null),
    [library],
  );
  const filtered = searchStateToParams({ ...state, q: "" }).toString() !== "";

  return (
    <form
      className={filterStyles.filters}
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onChange({ q: draft.trim() });
      }}
    >
      <label className={filterStyles.query}>
        <span>Search the texts</span>
        <span className={styles.queryRow}>
          <input
            type="search"
            name="q"
            value={draft}
            maxLength={500}
            placeholder="e.g. the soul's ascent to God, grace and free will"
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className={styles.submit}>
            Search
          </button>
        </span>
      </label>
      {facets && (
        <FilterFields value={state} facets={facets} onChange={(c: Partial<FacetValues>) => onChange(c)} />
      )}
      {filtered && (
        <button
          type="button"
          className={styles.reset}
          onClick={() => onChange({ ...DEFAULT_SEARCH, q: state.q })}
        >
          Clear filters
        </button>
      )}
    </form>
  );
}

function Intro() {
  return (
    <div className={styles.intro}>
      <p>
        Search by meaning across Scripture and the Fathers in every language of the collection. Ask in
        English; results come in the original Greek, Latin, Hebrew, Syriac, Coptic, Ge&lsquo;ez, Armenian or
        Gothic, with an English machine translation where the original is in a rarer language.
      </p>
      <p>
        Describe an idea rather than quoting words: <em>Christ as physician of the soul</em>,{" "}
        <em>baptism of desire</em>, <em>the light of Tabor</em>.
      </p>
    </div>
  );
}

function Results({ state, onStatus }: { state: SearchState; onStatus: (text: string) => void }) {
  const [pages, setPages] = useState<Pages>({ status: "loading", pages: [] });
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => onStatus(statusText(pages)), [pages, onStatus]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSearch(state, offset, controller.signal).then(
      (page) => setPages((p) => ({ status: "ready", pages: offset ? [...p.pages, page] : [page] })),
      (err: unknown) => {
        if (controller.signal.aborted) return;
        const error = err instanceof SearchError ? err : new SearchError("failed", String(err));
        setPages((p) => ({ status: "error", pages: p.pages, error }));
      },
    );
    return () => controller.abort();
    // `state` is the key of this component, so it is fixed for its lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, attempt]);

  const loaded = pages.pages;
  const results = loaded.flatMap((p) => p.results);
  const last = loaded[loaded.length - 1];
  const more = () => {
    if (last?.next_offset == null) return;
    setPages({ status: "loading", pages: loaded });
    setOffset(last.next_offset);
  };
  const retry = () => {
    setPages({ status: "loading", pages: loaded });
    setAttempt((n) => n + 1);
  };

  return (
    <section aria-label="Search results" aria-busy={pages.status === "loading"}>
      {last?.requested_mode === "phrase" && (
        <p className={styles.notice}>
          Exact-phrase search isn&rsquo;t available yet, so these are passages similar in meaning to{" "}
          <q>{last.query}</q>.
        </p>
      )}
      {results.length > 0 && (
        <ol className={styles.results}>
          {results.map((r) => (
            <ResultItem key={r.chunk_id} result={r} />
          ))}
        </ol>
      )}
      {pages.status === "ready" && results.length === 0 && (
        <p className={styles.status}>No passages found. Try other words, or clear the filters.</p>
      )}
      {pages.status === "loading" && <p className={styles.status}>Searching…</p>}
      {pages.status === "error" && <ErrorMessage error={pages.error} onRetry={retry} />}
      {pages.status === "ready" && last?.next_offset != null && (
        <button type="button" className={styles.more} onClick={more}>
          More results
        </button>
      )}
    </section>
  );
}

function ErrorMessage({ error, onRetry }: { error: SearchError; onRetry: () => void }) {
  const text = {
    "rate-limited": `Too many searches in a short time. Wait ${error.retryAfter ?? "a few"} seconds and try again.`,
    unavailable: `Search is unavailable right now (${error.message.replace(/\.$/, "")}). Please try again later.`,
    invalid: error.message,
    timeout: "The search took too long.",
    failed: error.message,
  }[error.kind];
  return (
    <p className={styles.error} role="alert">
      {text}{" "}
      {error.kind !== "invalid" && (
        <button type="button" className={styles.reset} onClick={onRetry}>
          Try again
        </button>
      )}
    </p>
  );
}

export function ResultItem({ result }: { result: SearchResult }) {
  const lang = languageInfo(result.language);
  const { work } = result;
  const license = LICENSES[work.license] ?? { label: work.license };
  const date = formatRange(result.date_range, result.date_composed);
  const authors = work.authors.map((a) => ({ id: a.id, name: a.name }));
  // The edition often names the collection already ("King James Version (1769 …)").
  const collection =
    work.edition && !work.edition.includes(work.source_label)
      ? `${work.source_label}, ${work.edition}`
      : (work.edition ?? work.source_label);

  return (
    <li className={styles.result}>
      <p className={styles.citation}>
        {authors.length > 0 && (
          <>
            <AuthorLinks authors={authors} />
            {", "}
          </>
        )}
        <Link href={resultHref(result)}>
          <cite lang={lang.lang} dir="auto">
            {work.title}
          </cite>{" "}
          <span className={styles.ref}>{result.canonical_ref}</span>
        </Link>
      </p>
      <p className={styles.text} lang={lang.lang} dir={lang.dir}>
        {result.text}
        {result.text_truncated && "…"}
      </p>
      {result.translation && (
        <div className={styles.translation}>
          <p className={styles.label}>Machine translation (English)</p>
          <p lang="en">{result.translation.text}</p>
        </div>
      )}
      <p className={styles.meta}>
        {[lang.name, date, collection].filter(Boolean).join(" · ")}
        {" · "}
        {license.url ? <a href={license.url}>{license.label}</a> : license.label}
        {work.provenance_url && (
          <>
            {" · "}
            <a href={work.provenance_url}>Source</a>
          </>
        )}
        {result.out_of_period && <> · after the collection period</>}
      </p>
    </li>
  );
}
