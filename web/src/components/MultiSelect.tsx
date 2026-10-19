import { useId, useMemo, useRef, useState } from "react";

import { fold } from "@/lib/filter";

import styles from "./Filters.module.css";

export interface MultiSelectOption {
  value: string;
  label: string;
  /** Shown after the label (e.g. works per author). */
  count?: number;
}

interface Props {
  label: string;
  options: MultiSelectOption[];
  /** Selected values; none means all. */
  selected: string[];
  onChange: (values: string[]) => void;
  /** Offer a text box that narrows a long list of options. */
  searchable?: boolean;
}

/**
 * A dropdown of checkboxes for a multi-valued facet. Ticking boxes changes a
 * draft; the selection is applied when the panel closes (Done, Escape, or
 * focus leaving it), so choosing three languages runs one search, not three.
 */
export default function MultiSelect({ label, options, selected, onChange, searchable = false }: Props) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>(selected);
  const [query, setQuery] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);

  const labels = useMemo(() => new Map(options.map((o) => [o.value, o.label])), [options]);
  const shown = open ? draft : selected;
  const summary = shown.length === 0 ? "All" : shown.map((v) => labels.get(v) ?? v).join(", ");
  const visible = useMemo(() => {
    const terms = fold(query).split(/\s+/).filter(Boolean);
    return terms.length ? options.filter((o) => terms.every((t) => fold(o.label).includes(t))) : options;
  }, [options, query]);

  const show = () => {
    setDraft(selected);
    setQuery("");
    setOpen(true);
  };
  const close = (refocus: boolean) => {
    setOpen(false);
    const changed = draft.length !== selected.length || draft.some((v) => !selected.includes(v));
    if (changed) onChange(draft);
    if (refocus) trigger.current?.focus();
  };
  const toggle = (value: string) =>
    setDraft((d) => (d.includes(value) ? d.filter((v) => v !== value) : [...d, value]));

  return (
    <div
      className={styles.multi}
      onKeyDown={(e) => {
        if (open && e.key === "Escape") {
          e.preventDefault();
          close(true);
        }
      }}
      onBlur={(e) => {
        // Focus moved outside the control (the panel itself takes focus on a click inside it).
        if (open && !e.currentTarget.contains(e.relatedTarget)) close(false);
      }}
    >
      <span id={`${id}-label`}>{label}</span>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        aria-labelledby={`${id}-label ${id}-value`}
        title={shown.length > 1 ? summary : undefined}
        onClick={() => (open ? close(false) : show())}
      >
        <span id={`${id}-value`}>{summary}</span>
      </button>
      {open && (
        <div id={`${id}-panel`} className={styles.panel} role="group" aria-label={label} tabIndex={-1}>
          {searchable && (
            <input
              type="search"
              aria-label={`Find ${label.toLowerCase()}`}
              placeholder="Find…"
              value={query}
              autoFocus
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
          <ul className={styles.options}>
            {visible.map((o) => (
              <li key={o.value}>
                <label className={styles.option}>
                  <input type="checkbox" checked={draft.includes(o.value)} onChange={() => toggle(o.value)} />
                  <span>{o.label}</span>
                  {o.count !== undefined && " "}
                  {o.count !== undefined && <span className={styles.count}>{o.count.toLocaleString()}</span>}
                </label>
              </li>
            ))}
          </ul>
          {visible.length === 0 && <p className={styles.none}>No matches.</p>}
          <div className={styles.panelActions}>
            <button type="button" disabled={draft.length === 0} onClick={() => setDraft([])}>
              Clear
            </button>
            <button type="button" onClick={() => close(true)}>
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
