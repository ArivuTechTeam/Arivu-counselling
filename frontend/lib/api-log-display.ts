import type { ApiCallLog, QuizCostSummary } from "./api";

export const callStage = (callType: string) => ({
  document_profile: "Reading document structure",
  topic_extraction: "Finding topics",
  topic_extraction_map: "Finding topics in document sections",
  topic_extraction_reduce: "Combining topic results",
  single_call_topic_analysis: "Analyzing document topics",
  question_repair: "Fixing generated questions",
  quiz_extraction: "Importing questions from a document",
  quiz_generation: "Writing quiz questions",
  blueprint_generation: "Writing quiz questions",
  question_verification: "Checking answers",
  question_regeneration: "Rewriting questions",
  question_explain: "Student explanation",
  unclassified: "Other AI request",
}[callType] ?? callType.replaceAll("_", " "));

export function costActivityCopy(group: Pick<QuizCostSummary, "kind" | "workflow_id" | "stages">) {
  if (group.workflow_id) return group.kind === "extraction"
    ? { title: "Creating a quiz from existing questions", description: "Cost of this quiz import, including recorded retries. Document analysis and later question edits are separate." }
    : { title: "Creating a quiz", description: "Cost of writing, checking and fixing questions in this run, including recorded retries. Document analysis and later question edits are separate." };
  const types = group.stages.map(stage => stage.call_type);
  const analysisTypes = new Set(["document_profile", "topic_extraction", "topic_extraction_map", "topic_extraction_reduce", "single_call_topic_analysis"]);
  const title = types.length && types.every(type => analysisTypes.has(type)) ? "Document topic analysis"
    : types.length && types.every(type => type === "question_verification") ? "Answer checking"
    : types.length && types.every(type => type === "question_regeneration") ? "Question rewriting"
    : "Other AI activity";
  return {
    title,
    description: group.kind === "legacy"
      ? "These requests are linked to this document, but not to one quiz run. The cost may include repeated analysis or other work on the document; it is separate from quiz creation."
      : "These requests have no saved document or quiz link. Their cost is recorded, but cannot be assigned to a particular quiz. This does not mean the requests are old or failed.",
  };
}

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
