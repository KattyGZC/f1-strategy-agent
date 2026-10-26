---
name: devlog
description: >-
  Write the development log entry for the current working session with the agent. Trigger at
  the end of a session, before the session's last commit, or when asked for "devlog", "log de
  la sesión", "cierra la sesión", "write up the session".
---

# Devlog

The devlog shows how this project was built with an AI agent: what was asked, what the agent proposed, where the author corrected or redirected it, what was decided and how it was verified. A reader (a recruiter, a reviewer, the author six months from now) should see judgment, not a transcript.

Format and index: `docs/devlog/README.md`. Read it first.

## Protocol

1. **Collect** from this session only: the chat, `git log main..HEAD`, `git diff --stat main...HEAD`, commands run and their results, ADRs added or changed.
2. **Ask** the author, in Spanish, only what you cannot see (at most five questions): why a direction changed, what they rejected and why, anything that happened outside the chat. Do not invent motives.
3. **Draft** the entry in English in the chat using the template in `docs/devlog/README.md`. Wait for an explicit OK or edits.
4. **Write** `docs/devlog/YYYY-MM-DD-NN-<slug>.md` (date of the session, `NN` = the session number that day, starting at `01`) and add one line to the index in `docs/devlog/README.md`, newest last.
5. The entry is committed with the session's work, or as its own `docs(devlog): ...` commit if the work is already committed. Show the commit plan first.

## Rules

- Facts only. Every claim of "verified" names the command or test and its result. Something skipped is written as skipped.
- **Corrections are the point.** When the author rejected, narrowed or redirected a proposal, say what was proposed, what they chose, and why. Do not soften it and do not dramatize it.
- Quote the author only when the exact words carry the decision, at most one or two short quotes per entry, translated to English and marked as translated.
- Link ADRs, commits and PRs instead of copying their content.
- No secrets, tokens, local absolute paths, personal data or private repo names.
- Straight quotes, no em-dashes. Short: an entry fits on one screen or two.
- An entry is never rewritten later with what happened after the session. A later session corrects it in its own entry.
