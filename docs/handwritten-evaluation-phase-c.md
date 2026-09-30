# Handwritten evaluation Phase C: fixed-rubric scoring

Phase C continues a clean Stage 1 checkpoint through `processing_stage2` and
persists one tenant-scoped evaluation, its question results, and visible-content
provider artifacts atomically. Submissions with non-fatal Stage 1 uncertainty
continue through scoring and the completed report is marked `review`, matching
ExamApp. Only a wholly illegible script stops before Stage 2. Transient Stage 2
failures resume from the saved extraction and do not pay to transcribe the
script again.

The scoring contract is `direct-score-v2`. The worker validates the frozen
rubric before any paid call, builds stable evidence IDs, enforces evidence
ownership and mapping states in Python, compiles marks against only the fixed
criterion IDs, applies deterministic MCQ and choice rules, and quantizes awards
to the rubric's permitted scale. DeepSeek receives text-mode requests; the
application parses the returned visible JSON text itself. Reasoning traces and
provider envelopes are neither logged nor persisted.

The default route grades top-level question groups independently. Any unmatched
evidence forces a whole-paper request so ownership is decided once. The database-backed DeepSeek
lease caps calls fleet-wide and fails open only when lease storage is unavailable.

Operational settings:

- `RATE_LIMIT_HANDWRITTEN_EVALUATION_PER_HOUR=10`
- `PER_QUESTION_STAGE2_ENABLED=true`
- `PER_QUESTION_STAGE2_CONCURRENCY=5`
- `DEEPSEEK_MODEL=deepseek-v4-flash`
- `DEEPSEEK_PER_QUESTION_MAX_TOKENS=32000`
- `DEEPSEEK_MAX_TOKENS=80000` for the whole-paper route
- `DEEPSEEK_THINKING_EFFORT=high`
- `DEEPSEEK_MAX_CONCURRENCY=24`
- `DEEPSEEK_SLOT_WAIT_SECONDS=30`

Apply `migration-81-handwritten-stage2.sql` before enabling the evaluation
worker with this code version.
