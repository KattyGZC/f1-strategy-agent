# Development log

This project is built in working sessions with an AI coding agent (Claude Code). Each session leaves one entry here, in order, so the way the project was built stays visible: what was asked, what the agent proposed, where the author corrected it, what was decided and how it was checked.

Entries are written with the `devlog` skill (`.claude/skills/devlog/`) at the end of each session, drafted by the agent and approved by the author. An entry is not rewritten later; a later entry corrects it.

## Index

| Date | Entry |
|---|---|
| 2026-10-26 | [01. Audit of the first MVP and agent setup](2026-10-26-01-audit-and-agent-setup.md) |
| 2026-10-26 | [02. Phase 0: foundation](2026-10-26-02-phase-0-foundation.md) |
| 2026-10-26 | [03. Phase 1: ingestion](2026-10-26-03-phase-1-ingestion.md) |
| 2026-10-27 | [01. Telemetry of the latest Grand Prix](2026-10-27-01-latest-grand-prix-telemetry.md) |

## Template

File name: `YYYY-MM-DD-NN-<slug>.md`, where `NN` is the session number that day.

```markdown
# YYYY-MM-DD · NN. <Title>

**Goal:** one sentence.

## What happened

Short, in order: what was asked, what the agent did, what came out.

## Decisions

- <Decision>: why. Link the ADR if there is one.

## Corrections and redirections

- The agent proposed <X>. The author chose <Y>, because <reason>.

## Verification

- `<command>`: <result>. Or: not run, because <reason>.

## Next

- The first thing the next session does.
```

Sections with nothing to say are omitted.
