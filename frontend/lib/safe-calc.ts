// Safe arithmetic evaluator (no eval/Function): tokenize → shunting-yard to RPN
// → compute. Supports + - * / ( ) and decimals. Returns null on any malformed
// input — never throws, never executes arbitrary code. Used by the scratchpad
// calculator in the quiz player.
export function safeCalc(input: string): number | null {
  const tokens = input.match(/\d+\.?\d*|[+\-*/()]/g);
  if (!tokens || tokens.join("") !== input.replace(/\s+/g, "")) return null;
  const prec: Record<string, number> = { "+": 1, "-": 1, "*": 2, "/": 2 };
  const out: string[] = [];
  const ops: string[] = [];
  for (const t of tokens) {
    if (/\d/.test(t)) out.push(t);
    else if (t === "(") ops.push(t);
    else if (t === ")") {
      while (ops.length && ops[ops.length - 1] !== "(") out.push(ops.pop() as string);
      if (ops.pop() !== "(") return null;
    } else {
      while (ops.length && prec[ops[ops.length - 1]] >= prec[t]) out.push(ops.pop() as string);
      ops.push(t);
    }
  }
  while (ops.length) {
    const op = ops.pop() as string;
    if (op === "(") return null;
    out.push(op);
  }
  const st: number[] = [];
  for (const t of out) {
    if (/\d/.test(t)) st.push(parseFloat(t));
    else {
      const b = st.pop();
      const a = st.pop();
      if (a === undefined || b === undefined) return null;
      st.push(t === "+" ? a + b : t === "-" ? a - b : t === "*" ? a * b : a / b);
    }
  }
  const r = st.length === 1 ? st[0] : null;
  return r != null && Number.isFinite(r) ? r : null;
}
