# How we merge branches into main (plain-language guide)

This doc explains branches, merge conflicts, and how to use the `/safe-merge`
Claude Code command we set up so that merging into `main` is never scary or
accidental. If you're new to git, read this once — you won't need to
memorize any git commands yourself, Claude runs them for you and asks before
doing anything risky.

## The basics

**A branch** is a separate copy of the code where you can make changes
without touching `main`. `main` is the "real" version of the app — the one
that's deployed. When you finish work on a branch, you eventually want it
merged into `main` so everyone gets your changes.

**A merge conflict** happens when two branches changed the *same lines of the
same file* in different ways, and git doesn't know which version is correct.
It's not an error you caused — it just means git needs a human to decide.
Most merges have *no* conflicts at all; you'll only see the conflict-resolving
steps below occasionally.

**A Pull Request (PR)** is GitHub's way of saying "here's a branch, please
review it before it goes into `main`." We always merge through a PR, never
by pushing directly to `main` — that way the other person can look at the
change before it's final, and there's a review step even for a two-person
team.

## The rule we follow: nothing reaches `main` silently

No matter what, merging into `main` always goes through a GitHub Pull
Request that a person clicks "Merge" on. Claude will never push to `main`
directly, never force-push anything, and never resolve a conflict on its
own judgment. If it's not 100% sure what to do, it stops and asks you in
plain language.

## How to use `/safe-merge`

Open Claude Code in this repo and type:

```
/safe-merge <branch-name>
```

For example, to merge the `akbar` branch into `main`:

```
/safe-merge akbar
```

### What happens next

**1. Claude checks things out first (nothing is changed yet).**
It fetches the latest `main`, compares it to your branch, and tells you:
- How many commits your branch is ahead/behind `main`.
- Which files changed on each side since they split apart.
- Whether merging would actually cause a conflict — checked in a safe,
  read-only way that doesn't touch your files.

**2a. If there are no conflicts:**
Claude tells you exactly what would be merged and asks a yes/no question:
*"Should I open a pull request from `<branch>` into `main`?"*
If you say yes, it opens the PR on GitHub. It does **not** merge anything
itself — you (or your teammate) still click "Merge" on GitHub afterward.

**2b. If there are conflicts:**
Claude will **never** pick a side for you. Instead, for each conflicting
file, one at a time, it will:
1. Show you `main`'s version and your branch's version, side by side, and
   explain in plain English what each one is trying to do.
2. Ask you directly: *"Which should I keep — main's version, the branch's
   version, or a combination? Tell me what to do."*
3. Wait for your answer before touching that file.
4. Show you the final result of that file so you can confirm it looks right.
5. Only move to the next conflicting file after you've approved this one.

Once every file is resolved and you've confirmed each one, Claude asks one
last time before finishing: *"All conflicts resolved as shown. Confirm I
should complete this merge?"* Only after you say yes does it create the
merge commit — and even then, that commit goes into a Pull Request, not
straight into `main`.

**3. After the PR is open:**
Claude gives you the PR link. Someone (you or your teammate) still needs to
open that link on GitHub, review it, and click "Merge" — `/safe-merge`
prepares the PR, it doesn't finish the job for you. This is intentional: a
second set of eyes on the actual merge is the whole point.

### If something feels wrong mid-conflict

You can always tell Claude to stop. If a merge is in progress locally and you
want to cancel it completely and go back to how things were, the command is
`git merge --abort` — Claude will mention this if a conflict resolution is
underway, and can run it for you if you ask.

### What `/safe-merge` will never do

- Push to `main` directly.
- Force-push anything, ever.
- Guess how to resolve a conflict instead of asking you.
- Resolve more than one file based on one answer.
- Delete a branch without asking first.
- Click "Merge" on the GitHub PR for you.

## Quick glossary

| Term | Meaning |
|---|---|
| Branch | A separate, isolated copy of the code for working on something without affecting `main`. |
| `main` | The branch that represents the real, current version of the app. |
| Commit | A saved snapshot of changes with a message describing them. |
| Merge | Combining the changes from one branch into another. |
| Merge conflict | When the same part of a file was changed differently on both branches, and a human needs to decide which version wins. |
| Pull Request (PR) | A GitHub page proposing "merge this branch into that branch," open for review before it's finalized. |
| `git fetch` | Downloads the latest info from GitHub without changing any of your files. |
| `git push` | Uploads your local commits to GitHub. |
