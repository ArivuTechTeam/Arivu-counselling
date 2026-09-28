"use client";

import { useRef, useState } from "react";

import { safeCalc } from "@/lib/safe-calc";

const KEYS = ["7", "8", "9", "/", "4", "5", "6", "*", "1", "2", "3", "-", "0", ".", "(", ")", "+"];
const PENS = ["#0f172a", "#2563eb", "#16a34a", "#dc2626"];

/**
 * Rough-work companion, rendered INLINE in the quiz sidebar (under the question
 * palette) so it never covers the question navigation. Notes + a safe
 * Calculator + a freehand Draw pad. Notes live only in component memory and
 * disappear when the attempt page closes or submits; rough work is never
 * written to browser storage or sent to the API.
 */
export function ScratchPad() {
  const [tab, setTab] = useState<"notes" | "calc" | "draw">("notes");
  const [openPanel, setOpenPanel] = useState(true);
  const [notes, setNotes] = useState("");
  const [expr, setExpr] = useState("");

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawingRef = useRef(false);
  const [pen, setPen] = useState(PENS[0]);

  function saveNotes(v: string) {
    setNotes(v);
  }

  function canvasXY(e: React.PointerEvent<HTMLCanvasElement>) {
    const c = canvasRef.current!;
    const r = c.getBoundingClientRect();
    return { x: (e.clientX - r.left) * (c.width / r.width), y: (e.clientY - r.top) * (c.height / r.height) };
  }
  function penDown(e: React.PointerEvent<HTMLCanvasElement>) {
    const c = canvasRef.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    drawingRef.current = true;
    const { x, y } = canvasXY(e);
    ctx.strokeStyle = pen;
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(x, y);
    c.setPointerCapture(e.pointerId);
  }
  function penMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return;
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    const { x, y } = canvasXY(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  }
  function penUp() {
    drawingRef.current = false;
  }
  function clearCanvas() {
    const c = canvasRef.current;
    if (c) c.getContext("2d")?.clearRect(0, 0, c.width, c.height);
  }

  const calcResult = expr ? safeCalc(expr) : null;

  const tabBtn = (key: typeof tab, label: string) => (
    <button
      key={key}
      onClick={() => setTab(key)}
      className={`flex-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition-colors ${
        tab === key ? "border-primary/40 bg-primary/10 text-primary" : "border-input text-muted-foreground hover:bg-accent"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="rounded-lg border bg-card p-3 shadow-sm sm:p-4">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          <span aria-hidden>✏️</span> Rough work
        </p>
        <button
          onClick={() => setOpenPanel((o) => !o)}
          className="rounded-md border border-input px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-accent"
        >
          {openPanel ? "Hide" : "Open"}
        </button>
      </div>

      {openPanel && (
        <div className="mt-2">
          <div className="flex gap-1.5">
            {tabBtn("notes", "Notes")}
            {tabBtn("calc", "Calc")}
            {tabBtn("draw", "Draw")}
          </div>

          <div className="mt-2">
            {tab === "notes" && (
              <textarea
                value={notes}
                onChange={(e) => saveNotes(e.target.value)}
                placeholder="Rough work… (kept until you submit)"
                className="h-44 w-full resize-none overflow-auto rounded-md border border-input bg-background p-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            )}

            {tab === "calc" && (
              <div>
                <input
                  value={expr}
                  onChange={(e) => setExpr(e.target.value)}
                  placeholder="(1500*15)/100"
                  className="mb-1 h-9 w-full rounded-md border border-input bg-background px-2 text-right text-sm tabular-nums focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <div className="mb-2 h-6 text-right text-sm font-bold tabular-nums text-primary">
                  {expr && (calcResult != null ? `= ${Number(calcResult.toFixed(6))}` : "…")}
                </div>
                <div className="grid grid-cols-4 gap-1.5">
                  {KEYS.map((k) => (
                    <button
                      key={k}
                      onClick={() => setExpr((e) => e + k)}
                      className="h-8 rounded-md border border-input bg-background text-sm font-medium hover:bg-accent active:scale-95"
                    >
                      {k}
                    </button>
                  ))}
                  <button
                    onClick={() => setExpr((e) => e.slice(0, -1))}
                    className="col-span-2 h-8 rounded-md border border-input bg-background text-xs font-medium hover:bg-accent"
                  >
                    ⌫
                  </button>
                  <button
                    onClick={() => setExpr("")}
                    className="col-span-2 h-8 rounded-md border border-input bg-background text-xs font-medium hover:bg-accent"
                  >
                    Clear
                  </button>
                </div>
              </div>
            )}

            {tab === "draw" && (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    {PENS.map((c) => (
                      <button
                        key={c}
                        onClick={() => setPen(c)}
                        aria-label={`Pen colour ${c}`}
                        className={`h-5 w-5 rounded-full border-2 transition-transform ${
                          pen === c ? "scale-110 border-foreground" : "border-transparent"
                        }`}
                        style={{ backgroundColor: c }}
                      />
                    ))}
                  </div>
                  <button
                    onClick={clearCanvas}
                    className="rounded-md border border-input px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-accent"
                  >
                    Clear
                  </button>
                </div>
                <canvas
                  ref={canvasRef}
                  width={300}
                  height={220}
                  onPointerDown={penDown}
                  onPointerMove={penMove}
                  onPointerUp={penUp}
                  onPointerLeave={penUp}
                  className="h-52 w-full touch-none rounded-md border border-input bg-white"
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
