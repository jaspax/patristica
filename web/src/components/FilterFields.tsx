import type { Facets, ViewState } from "@/lib/filter";
import { GENRES } from "@/lib/format";
import { languageInfo } from "@/lib/lang";

import styles from "./Filters.module.css";
import MultiSelect from "./MultiSelect";

export type FacetValues = Pick<ViewState, "author" | "language" | "genre" | "source" | "from" | "to">;

interface Props {
  value: FacetValues;
  facets: Facets;
  onChange: (changes: Partial<FacetValues>) => void;
  /** Offer the author facet (false on an author's own page). */
  withAuthor?: boolean;
}

/**
 * The author, language, genre, collection and date fields shared by the
 * library index and the search page; author, language and genre take several
 * values (MultiSelect). Render inside a form styled with `Filters.module.css`
 * (`filters`).
 */
export default function FilterFields({ value, facets, onChange, withAuthor = true }: Props) {
  return (
    <>
      {withAuthor && (
        <MultiSelect
          label="Author"
          options={facets.authors.map((a) => ({ value: a.id, label: a.name, count: a.count }))}
          selected={value.author}
          onChange={(author) => onChange({ author })}
          searchable
        />
      )}
      <MultiSelect
        label="Language"
        options={facets.languages.map((code) => ({ value: code, label: languageInfo(code).name }))}
        selected={value.language}
        onChange={(language) => onChange({ language })}
      />
      <MultiSelect
        label="Genre"
        options={facets.genres.map((g) => ({ value: g, label: GENRES[g] ?? g }))}
        selected={value.genre}
        onChange={(genre) => onChange({ genre })}
      />
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
