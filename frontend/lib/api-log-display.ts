import type { ApiCallLog } from "./api";

export const callStage = (callType: string) => ({
  document_profile: "Extraction — document profiling",
  topic_extraction: "Extraction — topic identification",
  topic_extraction_map: "Extraction — topic mapping",
  topic_extraction_reduce: "Extraction — topic consolidation",
  single_call_topic_analysis: "Topic analysis",
  question_repair: "Question repair",
  quiz_extraction: "Extraction — quiz questions",
  quiz_generation: "Quiz generation",
  blueprint_generation: "Quiz generation",
  question_verification: "Question verification",
  question_regeneration: "Question regeneration",
  question_explain: "Student explanation",
  unclassified: "Needs attribution (older call)",
}[callType] ?? callType.replaceAll("_", " "));

export function conversionRate(value: string): number | null {
  const rate = Number(value);
  return Number.isFinite(rate) && rate > 0 ? rate : null;
}

// Page-scoped paper groups, never an implied whole-history workflow total.
// Include tenant scope and typed keys so unlinked jobs cannot collide with papers.
export function groupApiLogs(items: ApiCallLog[]): [string, ApiCallLog[]][] {
  const groups = new Map<string, ApiCallLog[]>();
  for (const item of items) {
    const resource = item.document_id ? `paper:${item.document_id}`
      : item.job_id ? `job:${item.job_id}` : `call:${item.id}`;
    const key = `${item.tenant_id ?? "platform"}:${resource}`;
    const group = groups.get(key) ?? [];
    group.push(item);
    groups.set(key, group);
  }
  return Array.from(groups.entries());
}
