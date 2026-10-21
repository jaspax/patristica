/**
 * The Patristica mark: a chi-rho in a ring, the monogram of Christ in early
 * Christian inscriptions. Decorative; the wordmark beside it carries the name.
 */
export default function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="16" cy="16" r="14.5" strokeWidth="1.2" />
      <path d="M16 6.5v19" />
      <path d="M16 6.5h3.2a3.6 3.6 0 0 1 0 7.2H16" />
      <path d="M9.5 11.5 22.5 22M22.5 11.5 9.5 22" />
    </svg>
  );
}
