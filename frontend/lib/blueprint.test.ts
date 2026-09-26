import { describe, expect, it } from "vitest";

import {
  BlueprintQuestion,
  countByType,
  groupByType,
  hasClassification,
  mulberry32,
  pickRandomByType,
} from "./blueprint";

// A pool mirroring the user's example, scaled down:
//   6 PYQ, 4 MTP, 2 RTP  (12 total)
const POOL: BlueprintQuestion[] = [
  ...Array.from({ length: 6 }, (_, i) => ({ id: `pyq${i}`, paper_type: "pyq" as const })),
  ...Array.from({ length: 4 }, (_, i) => ({ id: `mtp${i}`, paper_type: "mtp" as const })),
  ...Array.from({ length: 2 }, (_, i) => ({ id: `rtp${i}`, paper_type: "rtp" as const })),
];

describe("countByType", () => {
  it("reports what the document contains", () => {
    expect(countByType(POOL)).toEqual({ pyq: 6, mtp: 4, rtp: 2, untyped: 0 });
  });
});

describe("pickRandomByType", () => {
  it("picks exactly the requested count of each type", () => {
    const ids = pickRandomByType(POOL, { pyq: 3, mtp: 2, rtp: 1 }, mulberry32(42));
    expect(ids).toHaveLength(6);
    expect(ids.filter((id) => id.startsWith("pyq"))).toHaveLength(3);
    expect(ids.filter((id) => id.startsWith("mtp"))).toHaveLength(2);
    expect(ids.filter((id) => id.startsWith("rtp"))).toHaveLength(1);
  });

  it("only ever picks real ids from the pool (no duplicates)", () => {
    const ids = pickRandomByType(POOL, { pyq: 6, mtp: 4, rtp: 2 }, mulberry32(1));
    expect(new Set(ids).size).toBe(ids.length);
    const known = new Set(POOL.map((q) => q.id));
    expect(ids.every((id) => known.has(id))).toBe(true);
  });

  it("clamps a request to what's available", () => {
    const ids = pickRandomByType(POOL, { pyq: 99, mtp: 0, rtp: 0 }, mulberry32(7));
    expect(ids).toHaveLength(6); // only 6 PYQ exist
  });

  it("is deterministic for a given seed and re-rolls with a new one", () => {
    const a = pickRandomByType(POOL, { pyq: 3, mtp: 0, rtp: 0 }, mulberry32(100));
    const aAgain = pickRandomByType(POOL, { pyq: 3, mtp: 0, rtp: 0 }, mulberry32(100));
    const b = pickRandomByType(POOL, { pyq: 3, mtp: 0, rtp: 0 }, mulberry32(101));
    expect(a).toEqual(aAgain); // same seed => same pick (stable within a render)
    expect(a).not.toEqual(b); // new seed ("Shuffle again") => different pick
  });

  it("actually randomizes which questions are chosen, not just the first N", () => {
    // Across many seeds, a PYQ other than the first should appear at least once.
    const seen = new Set<string>();
    for (let seed = 0; seed < 50; seed++) {
      for (const id of pickRandomByType(POOL, { pyq: 3, mtp: 0, rtp: 0 }, mulberry32(seed))) {
        seen.add(id);
      }
    }
    expect(seen.size).toBeGreaterThan(3); // not always the same 3
  });

  it("picks nothing for a zero/absent count", () => {
    expect(pickRandomByType(POOL, { pyq: 0 }, mulberry32(1))).toEqual([]);
    expect(pickRandomByType(POOL, {}, mulberry32(1))).toEqual([]);
  });
});

describe("groupByType / hasClassification", () => {
  it("groups by type", () => {
    const g = groupByType(POOL);
    expect(g.pyq).toHaveLength(6);
    expect(g.mtp).toHaveLength(4);
    expect(g.rtp).toHaveLength(2);
  });
  it("detects an unclassified set", () => {
    expect(hasClassification([{ id: "a" }, { id: "b", paper_type: null }])).toBe(false);
    expect(hasClassification(POOL)).toBe(true);
  });
});
