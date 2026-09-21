# Current faculty approval workflow

This policy supersedes the stricter approval requirements described in the
Phase 1–3 implementation history, following the founder's explicit request to
reduce faculty workload.

- Individual approval requires no explanation or resolution note, for either
  imported or generated questions, regardless of AI verification status.
- Approve all includes pending and needs-edit questions. It preserves already
  rejected questions; an individual question can still be explicitly reapproved.
- AI warnings and source excerpts remain available in a collapsed optional
  details section. They do not block approval and are not cleared to imply that
  the AI verified a teacher-approved question.
- Structurally invalid answers still need correction (for example, the correct
  option references an option that does not exist). Concurrently changed items
  are skipped and reported rather than approving a stale version.
- Approval records the teacher and time. Publication remains a separate action.
  No automatic publication or changes to existing questions occur on deployment.
- No database migration is needed. Deploy/restart the updated API and frontend.

The former `unsupported` label combines several checks: an unsupported answer,
unmatched/insufficient evidence, incorrect source pages, generic explanations,
and duplicates. It is not a reliable classification of “outside the syllabus.”
The interface now labels this as an AI review flag. Prompt instructions constrain
generation but do not guarantee model compliance or eliminate verifier mistakes.
