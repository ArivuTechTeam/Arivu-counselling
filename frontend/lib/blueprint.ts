// Extraction blueprint — pure selection math (no React, fully unit-testable).
//
// The teacher says how many of each paper type they want; we pick that many at
// RANDOM from the extracted pool. Everything not picked is simply left out (never
// rejected/deleted). The randomness uses an injected RNG so the UI can re-roll
// ("Shuffle again") and tests can seed it for deterministic assertions.

export type PaperTypeKey = "pyq" | "mtp" | "rtp" | "untyped";

export const PAPER_TYPE_KEYS: PaperTypeKey[] = ["pyq", "mtp", "rtp", "untyped"];

export type BlueprintQuestion = {
  id: string;
  paper_type?: "pyq" | "mtp" | "rtp" | null;
};

export type TypeCounts = Record<PaperTypeKey, number>;

// A source of randomness in [0, 1). Injected so it can be seeded/replayed.
export type Rng = () => number;

export function emptyCounts(): TypeCounts {
  return { pyq: 0, mtp: 0, rtp: 0, untyped: 0 };
}

export function typeKey(paperType: BlueprintQuestion["paper_type"]): PaperTypeKey {
  return paperType ?? "untyped";
}

/** How many of each type exist in the document. */
export function countByType(questions: BlueprintQuestion[]): TypeCounts {
  const counts = emptyCounts();
  for (const q of questions) counts[typeKey(q.paper_type)] += 1;
  return counts;
}

export function groupByType(
  questions: BlueprintQuestion[],
): Record<PaperTypeKey, BlueprintQuestion[]> {
  const groups: Record<PaperTypeKey, BlueprintQuestion[]> = {
    pyq: [], mtp: [], rtp: [], untyped: [],
  };
  for (const q of questions) groups[typeKey(q.paper_type)].push(q);
  return groups;
}

/** True when any question carries a PYQ/MTP/RTP tag. */
export function hasClassification(questions: BlueprintQuestion[]): boolean {
  return questions.some(
    (q) => q.paper_type === "pyq" || q.paper_type === "mtp" || q.paper_type === "rtp",
  );
}

/** Small deterministic PRNG (mulberry32). Same seed => same sequence, so a given
 *  "shuffle nonce" always reproduces the same pick within a render. */
export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Fisher-Yates shuffle into a NEW array, using the injected RNG. */
export function shuffle<T>(items: T[], rng: Rng): T[] {
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * Randomly pick `counts[type]` questions of each type from the pool. A count is
 * clamped to what's available; missing/zero counts pick nothing of that type.
 * Returns the chosen ids.
 */
export function pickRandomByType(
  questions: BlueprintQuestion[],
  counts: Partial<TypeCounts>,
  rng: Rng,
): string[] {
  const groups = groupByType(questions);
  const ids: string[] = [];
  for (const key of PAPER_TYPE_KEYS) {
    const want = Math.min(Math.max(0, Math.floor(counts[key] ?? 0)), groups[key].length);
    if (want <= 0) continue;
    ids.push(...shuffle(groups[key], rng).slice(0, want).map((q) => q.id));
  }
  return ids;
}
