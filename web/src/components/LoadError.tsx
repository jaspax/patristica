import styles from "./LoadError.module.css";

/** Shown when the static library export can't be loaded. */
export default function LoadError({ error }: { error: string }) {
  return (
    <div className={styles.error} role="alert">
      <p>
        <strong>Couldn&apos;t load the library.</strong> {error}
      </p>
      <p>
        For local development, export the library and link it into the app: run{" "}
        <code>uv run python -m scripts.export_library</code> in the repo root, then{" "}
        <code>npm run link-data</code> in <code>web/</code>.
      </p>
    </div>
  );
}
