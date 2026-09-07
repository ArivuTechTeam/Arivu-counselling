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
