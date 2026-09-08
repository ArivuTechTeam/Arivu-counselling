# Pavyaa branch changelog

This directory is the permanent Before/After record for branch work completed
for Pavyaa. Use the exact branch name as the section heading, including for a
branch that does not start with `pavyaa/`.

## File naming

- Keep one file per calendar date.
- Name files `DD-MMM-YYYY.md`, for example `08-Sep-2026.md`.
- Use `D-MMM-YYYY` in the document heading, for example `# 8-Sep-2026`.

## Required workflow

1. Before reporting completed branch work, open today's dated file.
2. If it does not exist, create it. If it exists, append without overwriting.
3. Find or add the exact branch heading.
4. Continue the numbering already present under that branch.
5. Record each completed change with a clear Before/After pair.
6. When revisiting an older branch, consult earlier files for context but put
   the new entry in today's file.
7. Commit the dated file with the corresponding branch changes.

Use this exact entry format:

```markdown
## pavyaa/example-branch

1.

   - Before: The previous behavior or problem.
   - After: The resulting behavior or fix.
```
