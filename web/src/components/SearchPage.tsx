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
  highlight,
  parseSearchState,
  resultHref,
  searchStateToParams,
  SearchError,
  type SearchResponse,
  type SearchResult,
  type SearchState,
  versionLanguages,
  withoutQuotes,
} from "@/lib/search";
import { useLoaded } from "@/lib/useLoaded";

import AuthorLinks from "./AuthorLinks";
import FilterFields, { type FacetValues } from "./FilterFields";
import filterStyles from "./Filters.module.css";
import Landing, { Hero } from "./Landing";
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
  // Lives here, not in the remounted SearchForm, so it survives a new query.
  // A link that sets filters opens the panel so they are visible.
  const [showFilters, setShowFilters] = useState(() => activeFilters(state) > 0);
  // The first page of results is loading: the Search button shows it.
  const [busy, setBusy] = useState(false);

  return (
    <div>
      {/* The landing page leads with what Patristica is; a search leads with the box. */}
      {searching ? <h1 className="visually-hidden">Search</h1> : <Hero />}
      {/* Keyed by the query, so the field shows it after back/forward navigation. */}
      <SearchForm
        key={state.q}
        state={state}
        onChange={go}
        showFilters={showFilters}
        onToggleFilters={setShowFilters}
        busy={searching && busy}
      />
      <p role="status" className="visually-hidden">
        {searching ? status : ""}
      </p>
      {searching ? (
        <Results key={key} state={state} onStatus={setStatus} onBusy={setBusy} onSearch={(q) => go({ q })} />
      ) : (
        <Landing />
      )}
    </div>
  );
}

/** What the status region says about the latest request. */
function statusText(pages: Pages): string {
  if (pages.status === "loading") return "Searching…";
  if (pages.status === "error") return ""; // the error is an alert
  const shown = pages.pages.reduce((n, p) => n + p.results.length, 0);
  if (shown === 0) return "No passages found.";
  const last = pages.pages[pages.pages.length - 1];
  const more = last?.next_offset != null;
  const of = last?.total != null && last.total > shown ? ` of ${last.total}` : "";
  const noun = (last?.total ?? shown) === 1 ? "passage" : "passages";
  return `${shown}${of} ${noun} shown${more ? ", more available" : ""}.`;
}

/** How many filters are set; a date range counts once. */
function activeFilters(state: SearchState): number {
  const keys = new Set([...searchStateToParams({ ...state, q: "" }).keys()].map((k) => (k === "to" ? "from" : k)));
  return keys.size;
}

interface SearchFormProps {
  state: SearchState;
  onChange: (c: Partial<SearchState>) => void;
  showFilters: boolean;
  onToggleFilters: (open: boolean) => void;
  busy: boolean;
}

function SearchForm({ state, onChange, showFilters, onToggleFilters, busy }: SearchFormProps) {
  const [draft, setDraft] = useState(state.q);
  const library = useLoaded(loadLibrary);
  const facets = useMemo(
    () => (library.status === "ready" ? libraryFacets(library.data.index, library.data.authors) : null),
    [library],
  );
  const active = activeFilters(state);

  return (
    <form
      className={styles.form}
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onChange({ q: draft.trim() });
      }}
    >
      <div className={styles.queryBox}>
        {/* Only the caption is the label: the button would otherwise join the box's name. */}
        <label htmlFor="search-q" className="visually-hidden">
          Search the texts
        </label>
        <span className={styles.queryRow}>
          <input
            id="search-q"
            type="search"
            name="q"
            value={draft}
            maxLength={500}
            aria-describedby="search-hint"
            placeholder="e.g. the soul's ascent to God, grace and free will"
            onChange={(e) => setDraft(e.target.value)}
          />
          {/* The label stays (hidden) under the spinner, so the button keeps its name and width. */}
          <button type="submit" className={styles.submit} aria-busy={busy}>
            <span className={busy ? styles.busyLabel : undefined}>Search</span>
            {busy && <span className={styles.spinner} aria-hidden="true" />}
          </button>
        </span>
        <div className={styles.hint}>
          <span id="search-hint">
            Put words in quotes for an exact phrase: <q>&quot;in principio erat verbum&quot;</q>.
          </span>{" "}
          <SearchHelp />
        </div>
      </div>
      {/* Not a <details>: "Clear filters" sits beside the toggle, so it works while the panel is closed. */}
      <div className={styles.filterBar}>
        <button
          type="button"
          className={styles.filterToggle}
          aria-expanded={showFilters}
          aria-controls="search-filters"
          onClick={() => onToggleFilters(!showFilters)}
        >
          Filters{active > 0 && ` (${active})`}
        </button>
        {active > 0 && (
          <button
            type="button"
            className={styles.reset}
            onClick={() => onChange({ ...DEFAULT_SEARCH, q: state.q })}
          >
            Clear filters
          </button>
        )}
      </div>
      <div id="search-filters" className={`${filterStyles.filters} ${styles.filterPanel}`} hidden={!showFilters}>
        {facets ? (
          <FilterFields value={state} facets={facets} onChange={(c: Partial<FacetValues>) => onChange(c)} />
        ) : (
          <p className={styles.status}>Loading filters…</p>
        )}
      </div>
    </form>
  );
}

function SearchHelp() {
  return (
    <details className={styles.help}>
      <summary>How search works</summary>
      <div>
        <p>
          <strong>By meaning</strong> (no quotes): describe an idea in any language, and the closest passages
          come first, whatever words they use. <em>the soul&rsquo;s ascent to God</em>
        </p>
        <p>
          <strong>Exact phrase</strong> (in quotes): passages containing those words in that order. Accents,
          breathings, vowel points and capitals don&rsquo;t matter, nor do Latin spellings like <em>u/v</em>,{" "}
          <em>i/j</em> or <em>ae/e</em>. Scripture comes first, then the earliest texts.{" "}
          <q>&quot;ἐν ἀρχῇ ἦν ὁ λόγος&quot;</q>
        </p>
        <p>
          <strong>Both</strong>: several quoted phrases must all occur; words outside the quotes rank those
          passages by meaning. <q>&quot;in principio&quot; creation of light</q>
        </p>
      </div>
    </details>
  );
}

interface ResultsProps {
  state: SearchState;
  onStatus: (text: string) => void;
  /** Whether the first page is loading (later pages have their own "More results" button). */
  onBusy: (busy: boolean) => void;
  /** Run another query (the no-results fallback). */
  onSearch: (q: string) => void;
}

function Results({ state, onStatus, onBusy, onSearch }: ResultsProps) {
  const [pages, setPages] = useState<Pages>({ status: "loading", pages: [] });
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => onStatus(statusText(pages)), [pages, onStatus]);
  const firstPage = pages.status === "loading" && pages.pages.length === 0;
  useEffect(() => onBusy(firstPage), [firstPage, onBusy]);
  useEffect(() => () => onBusy(false), [onBusy]);

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
      {last && <ModeLine response={last} />}
      {results.length > 0 && (
        <ol className={styles.results}>
          {results.map((r) => (
            <ResultItem key={r.chunk_id} result={r} />
          ))}
        </ol>
      )}
      {pages.status === "ready" && results.length === 0 && last?.mode === "keyword" && (
        <p className={styles.status}>
          No passages contain {last.phrases.length > 1 ? "these phrases" : "this phrase"}.{" "}
          <button type="button" className={styles.reset} onClick={() => onSearch(withoutQuotes(state.q))}>
            Search by meaning instead
          </button>
        </p>
      )}
      {pages.status === "ready" && results.length === 0 && last?.mode !== "keyword" && (
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

/** Which search ran: "Exact phrase" (quoted) or "Semantic". */
function ModeLine({ response }: { response: SearchResponse }) {
  if (response.mode === "vector") {
    return (
      <p className={styles.mode}>
        <strong>Semantic</strong> · passages closest in meaning
      </p>
    );
  }
  const phrases = response.phrases.map((p, i) => (
    <span key={i}>
      {i > 0 && " and "}
      <q>{p}</q>
    </span>
  ));
  return (
    <p className={styles.mode}>
      <strong>Exact phrase</strong> · passages containing {phrases}
      {response.text ? (
        <>
          , closest in meaning to <q>{response.text}</q> first
        </>
      ) : (
        ", Scripture first, then the earliest"
      )}
      {response.total ? ` · ${response.total.toLocaleString()} found` : ""}
    </p>
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
        {result.text_start > 0 && "…"}
        {highlight(result.text, result.matches).map((s, i) => (s.match ? <mark key={i}>{s.text}</mark> : s.text))}
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
      <OtherVersions result={result} />
    </li>
  );
}

/** "Also in: Latin: Clementine Vulgate · English: …", each linking to the passage in that version (#180). */
function OtherVersions({ result }: { result: SearchResult }) {
  const languages = versionLanguages(result);
  if (languages.length === 0) return null;
  const id = `versions-${result.chunk_id}`;
  return (
    <div className={styles.versions}>
      <span id={id} className={styles.label}>
        Also in:
      </span>{" "}
      <ul aria-labelledby={id}>
        {languages.map((l) => (
          <li key={l.language}>
            {l.name}:{" "}
            {l.versions.map((v, i) => (
              <span key={v.href}>
                {i > 0 && ", "}
                <Link href={v.href}>
                  {v.label}
                  {v.ref && (
                    <>
                      {" "}
                      <span className={styles.ref}>{v.ref}</span>
                    </>
                  )}
                </Link>
              </span>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}
