# Project instructions

## Akbar branch changelog

After completing work on any feature branch and before reporting the work to
the user, update `docs/akbar_changelog/` as follows:

1. Use today's file in `DD-MMM-YYYY.md` format, such as `07-Sep-2026.md`.
2. Create the file if it does not exist. Append without replacing existing
   entries when it does exist.
3. Add changes below the exact branch heading, such as `## akbar/ui-fixes`.
4. Continue that branch section's numbering and describe every completed change
   with this exact structure:

   ```markdown
   1.

      - Before: [the previous behavior or problem]
      - After: [the resulting behavior or fix]
   ```

5. Search earlier changelog files for useful context when revisiting a branch,
   but always record new work under today's date.
6. Stage the dated changelog file with the implementation so the permanent
   record reaches the repository in the same pull request.

The full convention is documented in `docs/akbar_changelog/README.md`.

## AI rate limits

All AI request limits are per user in a rolling one-hour window and are read
from the environment when the backend starts. Railway can change them without
a code change; restart the backend after editing a value.

- `RATE_LIMIT_QUIZ_GENERATION_PER_HOUR` (default `10`)
- `RATE_LIMIT_BLUEPRINT_PER_HOUR` (default `10`)
- `RATE_LIMIT_TOPIC_EXTRACTION_PER_HOUR` (default `10`)
- `RATE_LIMIT_QUESTION_REGENERATE_PER_HOUR` (default `10`)
- `RATE_LIMIT_QUESTION_EXPLAIN_PER_HOUR` (default `10`)
- `RATE_LIMIT_QUIZ_EXTRACTION_PER_HOUR` (default `10`)
