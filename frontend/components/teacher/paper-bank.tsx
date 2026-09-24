"use client";

import { useEffect, useState } from "react";

import { PaperBankSummary, getPaperBank } from "@/lib/api";

const chip = "rounded-lg border bg-card px-4 py-3 text-center shadow-sm";

export function PaperBank() {
  const [data, setData] = useState<PaperBankSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPaperBank()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load the paper bank."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Paper bank</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The PYQ / MTP / RTP questions your published papers have contributed to the student
          <strong> Mock Test &amp; PYQ</strong> practice. Questions are added when you tick
          &ldquo;contains PYQ/MTP/RTP&rdquo; on an import and then <strong>publish</strong>.
        </p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data ? null : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className={chip}>
              <p className="text-2xl font-bold text-primary">{data.totals.total}</p>
              <p className="text-xs text-muted-foreground">Total</p>
            </div>
            <div className={chip}>
              <p className="text-2xl font-bold">{data.totals.pyq}</p>
              <p className="text-xs text-muted-foreground">PYQ</p>
            </div>
            <div className={chip}>
              <p className="text-2xl font-bold">{data.totals.mtp}</p>
              <p className="text-xs text-muted-foreground">MTP</p>
            </div>
            <div className={chip}>
              <p className="text-2xl font-bold">{data.totals.rtp}</p>
              <p className="text-xs text-muted-foreground">RTP</p>
            </div>
          </div>

          {data.subjects.length === 0 ? (
            <p className="rounded-xl border border-dashed bg-card/60 p-6 text-center text-sm text-muted-foreground">
              Nothing in the paper bank yet. Import a paper with the &ldquo;contains PYQ/MTP/RTP&rdquo;
              box ticked, review it, and publish — the classified questions appear here and in the
              student Mock Test &amp; PYQ tab.
            </p>
          ) : (
            <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/40 text-left text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5">Subject</th>
                    <th className="px-4 py-2.5 text-right">PYQ</th>
                    <th className="px-4 py-2.5 text-right">MTP</th>
                    <th className="px-4 py-2.5 text-right">RTP</th>
                    <th className="px-4 py-2.5 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {data.subjects.map((s) => (
                    <tr key={s.subject_id} className="border-b last:border-0">
                      <td className="px-4 py-2.5 font-medium">{s.subject_name}</td>
                      <td className="px-4 py-2.5 text-right">{s.pyq}</td>
                      <td className="px-4 py-2.5 text-right">{s.mtp}</td>
                      <td className="px-4 py-2.5 text-right">{s.rtp}</td>
                      <td className="px-4 py-2.5 text-right font-semibold">{s.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
