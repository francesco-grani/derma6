/** Pure helpers + timings for the product-finder loading state's rotating
 * stage-phrase line. Kept out of `ProductFinderPopover.tsx` so that file only
 * exports React components (React Fast Refresh requirement). */

/** Collapses the pending sources' stage phrases into the distinct set to
 * rotate through: a `null` (a source that hasn't emitted a stage event yet)
 * becomes the generic "Searching..." fallback, and a `Set` drops duplicates
 * while preserving first-seen order — so two sources reporting the same phrase
 * show as one line rather than the same text twice. */
export function dedupeStagePhrases(stagePhrases: (string | null)[]): string[] {
  return Array.from(new Set(stagePhrases.map((p) => p ?? 'Searching...')))
}

/** Default rotation timings; overridable (mainly so unit tests can drive the
 * rotation deterministically without waiting real seconds). */
export const STAGE_PHRASE_ROTATE_MS = 2500
export const STAGE_PHRASE_FADE_MS = 300
