export type AnswerTranscriptBlock =
  | { type: "text" | "heading"; text: string }
  | { type: "table"; rows: string[][] }
  | { type: "working" | "list"; lines: string[] }
  | {
      type: "verdict";
      prefix: string;
      verdict: string;
      explanation: string;
      text: string;
    };

const TABLE_SEPARATOR = /^:?-{2,}:?$/;
const ITEM_MARKER = String.raw`(?:\(\d+\)|\d+[.)]|\([ivxlcdm]+\)|[ivxlcdm]+[.)]|[a-z][.)])`;
const LIST_PREFIX = new RegExp(
  String.raw`^\s*(?:[-*•●▪]\s+|${ITEM_MARKER}\s+)`,
  "i",
);
const VERDICT_LINE = new RegExp(
  String.raw`^\s*(${ITEM_MARKER}\s*)?(true|false)\b\s*[:.-]?\s*(.*)$`,
  "i",
);
const NAMED_HEADING = /^(?:answer|solution|working notes?|journal entr(?:y|ies)|ledger|trial balance|balance sheet|cash book|bank reconciliation statement|trading(?: and| &)? (?:profit and loss|p&l) a\/?c|profit and loss a\/?c|statement of (?:profit|affairs)|capital expenditure|revenue expenditure)\s*:?[.]?$/i;
const MATH_SIGNAL = /(?:=>|->|→|=|@|[+×÷]|\b(?:add|less|total|balance|gross profit|net profit|loss|closing stock|opening stock|inventory|cost of goods sold|cogs)\b)/i;

function cleanLine(value: unknown): string {
  return String(value ?? "").replace(/\r/g, "").trim();
}

function looksLikeCalculation(line: string): boolean {
  const text = cleanLine(line);
  if (!text || text.length > 280 || !/\d/.test(text)) return false;
  return MATH_SIGNAL.test(text) || /\d\s*[-*/]\s*\d/.test(text);
}

function splitWorkingChain(line: string): string[] | null {
  const semicolonParts =
    String(line)
      .match(/[^;]+(?:;|$)/g)
      ?.map(cleanLine)
      .filter(Boolean) ?? [];
  if (
    semicolonParts.length >= 3 &&
    semicolonParts.filter(looksLikeCalculation).length >= 2
  ) {
    return semicolonParts;
  }

  const dashParts = String(line)
    .split(/\s+(?=[—–]\s*)/)
    .map((part) => cleanLine(part).replace(/^[—–]\s*/, ""))
    .filter(Boolean);
  if (
    dashParts.length >= 3 &&
    dashParts.filter(looksLikeCalculation).length >= 2
  ) {
    return dashParts;
  }
  return null;
}

function looksLikeHeading(line: string): boolean {
  const text = cleanLine(line);
  if (!text || text.length > 80 || /[=|@]/.test(text)) return false;
  if (NAMED_HEADING.test(text)) return true;
  if (text.endsWith(":") && text.split(/\s+/).length <= 9) return true;
  const words = text.replace(/[.:]$/, "").split(/\s+/).filter(Boolean);
  return (
    words.length <= 6 &&
    words.length >= 2 &&
    words.every(
      (word) =>
        /^[A-Z][A-Za-z/&-]*$/.test(word) ||
        /^(?:a|an|and|of|the|to|in|as|on)$/i.test(word),
    ) &&
    !/[.!?]$/.test(text)
  );
}

function tableRowsFromRun(run: string[]): string[][] {
  return run
    .map((line) => {
      const leading = line.trimStart().startsWith("|");
      const trailing = line.trimEnd().endsWith("|");
      let row = line.split("|").map((cell) => cell.trim());
      if (leading && row[0] === "") row = row.slice(1);
      if (leading && trailing && row.at(-1) === "") row = row.slice(0, -1);
      return row;
    })
    .filter((row) => !row.every((cell) => !cell || TABLE_SEPARATOR.test(cell)));
}

function isSpecialLine(line: string): boolean {
  return Boolean(
    line.includes("|") ||
      VERDICT_LINE.test(line) ||
      LIST_PREFIX.test(line) ||
      splitWorkingChain(line) ||
      looksLikeCalculation(line) ||
      looksLikeHeading(line),
  );
}

/**
 * Content-driven parser kept in parity with ExamApp's student report. It
 * preserves the student's words while turning tables, lists, calculations,
 * headings and true/false conclusions into readable report blocks.
 */
export function parseAnswerTranscript(value: unknown): AnswerTranscriptBlock[] {
  const lines = String(value ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: AnswerTranscriptBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.includes("|")) {
      const run: string[] = [];
      while (index < lines.length && lines[index].includes("|")) {
        run.push(lines[index]);
        index += 1;
      }
      const rows = tableRowsFromRun(run);
      blocks.push(
        rows.length >= 2 && Math.max(...rows.map((row) => row.length)) >= 2
          ? { type: "table", rows }
          : { type: "text", text: run.join("\n") },
      );
      continue;
    }

    const verdict = line.match(VERDICT_LINE);
    if (verdict) {
      blocks.push({
        type: "verdict",
        prefix: cleanLine(verdict[1]),
        verdict: verdict[2],
        explanation: verdict[3],
        text: cleanLine(line),
      });
      index += 1;
      continue;
    }

    if (LIST_PREFIX.test(line)) {
      const items: string[] = [];
      while (index < lines.length && LIST_PREFIX.test(lines[index])) {
        items.push(cleanLine(lines[index]));
        index += 1;
      }
      blocks.push({ type: "list", lines: items });
      continue;
    }

    const workingChain = splitWorkingChain(line);
    if (workingChain) {
      blocks.push({ type: "working", lines: workingChain });
      index += 1;
      continue;
    }

    if (looksLikeHeading(line)) {
      blocks.push({ type: "heading", text: cleanLine(line) });
      index += 1;
      continue;
    }

    if (looksLikeCalculation(line)) {
      const workingLines: string[] = [];
      while (
        index < lines.length &&
        lines[index].trim() &&
        looksLikeCalculation(lines[index]) &&
        !splitWorkingChain(lines[index])
      ) {
        workingLines.push(cleanLine(lines[index]));
        index += 1;
      }
      blocks.push({ type: "working", lines: workingLines });
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isSpecialLine(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "text", text: paragraph.join("\n").trim() });
  }

  return blocks;
}
