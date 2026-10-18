import type { Facets, ViewState } from "@/lib/filter";
import { GENRES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";

import styles from "./Filters.module.css";

export type FacetValues = Pick<ViewState, "author" | "language" | "genre" | "source" | "from" | "to">;

interface Props {
  value: FacetValues;
  facets: Facets;
  onChange: (changes: Partial<FacetValues>) => void;
}

/**
 * The author, language, genre, collection and date fields shared by the
 * library index and the search page. Render inside a form styled with
 * `Filters.module.css` (`filters`).
 */
export default function FilterFields({ value, facets, onChange }: Props) {
  return (
    <>
      <label>
        <span>Author</span>
        <select value={value.author} onChange={(e) => onChange({ author: e.target.value })}>
          <option value="">All</option>
          {facets.authors.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.count.toLocaleString()})
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Language</span>
        <select value={value.language} onChange={(e) => onChange({ language: e.target.value })}>
          <option value="">All</option>
          {facets.languages.map((code) => (
            <option key={code} value={code}>
              {languageInfo(code).name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Genre</span>
        <select value={value.genre} onChange={(e) => onChange({ genre: e.target.value })}>
          <option value="">All</option>
          {facets.genres.map((g) => (
            <option key={g} value={g}>
              {GENRES[g] ?? g}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Collection</span>
        <select value={value.source} onChange={(e) => onChange({ source: e.target.value })}>
          <option value="">All</option>
          {facets.sources.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <fieldset className={styles.years}>
        <legend>Date (negative = BC)</legend>
        <input
          type="number"
          inputMode="numeric"
          aria-label="From year"
          placeholder="From"
          value={value.from ?? ""}
          onChange={(e) => onChange({ from: e.target.value === "" ? null : Number(e.target.value) })}
        />
        <span aria-hidden="true">–</span>
        <input
          type="number"
          inputMode="numeric"
          aria-label="To year"
          placeholder="To"
          value={value.to ?? ""}
          onChange={(e) => onChange({ to: e.target.value === "" ? null : Number(e.target.value) })}
        />
      </fieldset>
    </>
  );
}
