import styles from "./page.module.css";

export default function Home() {
  return (
    <main className={styles.main}>
      <h1>Patristica</h1>
      <p>
        A library of Scripture and patristic writings from the first thousand years of
        Christianity, in their original languages and in translation: Greek, Latin, Hebrew,
        Syriac, Coptic, Ge&apos;ez, Armenian, Gothic and English.
      </p>
      <p className={styles.note}>The library browser is coming soon.</p>
    </main>
  );
}
