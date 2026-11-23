# 2026-11-22 · 01. Phase 6: intent and spec

**Goal:** agree on what the assistant is for and write the phase 6 spec before any design or code.

## What happened

The author asked for the next step after phase 5 and the self-hosted fonts fix (#27); the devlog's Next pointed at planning phase 6. The agent explained the patterns and the security the assistant would need, in plain terms, then reviewed an external collection of agent skills and proposed the ones that fit this phase. The author chose to run them one by one, in order. The agent proposed one session per stage rather than per skill, since skills of the same stage feed each other and the adversarial review needs a fresh context.

The session ran the first stage. An interview, one question at a time with the agent's guess attached, settled the intent. The agent then wrote the spec in `docs/specs/phase-6-assistant.md`, and the author approved it.

## Decisions

- Audience: recruiters and interviewers in mind, never said in the product; anyone else is welcome.
- Success: within a minute, a visitor taps a suggested question, sees the agent's steps while it works, and opens a citation that leads to the real data.
- Scope: the races in the clean model, with three kinds of question: facts, what if (the phase 5 simulator), and rules applied to a race. Futures, live data, other seasons, general history and non-F1 topics are out.
- Budget: at most 25 USD a month, enforced by a spend limit on the provider's workspace. When it is reached, the tab shows a notice and a recorded example answer, and the rest of the app keeps working. Quality before savings: Claude Opus 5.5.
- Embeddings: Voyage AI, since indexing the regulations costs cents and avoids another container to deploy.
- Answers follow the question's language; the interface stays in English (issue #13).
- V1 answers one question at a time, with no conversation memory.
- Specs get their own folder, `docs/specs/`; decisions stay in ADRs.

## Corrections and redirections

- The agent guessed the assistant would target recruiters. The author agreed but asked that this not be stated anywhere ("I don't want to specify it", translated).

## Verification

- No code changed. `make check` was not run.

## Next

- Session 2, design: threat model of the assistant (security-and-hardening), the contract of the API and of the tools (api-and-interface-design), and every SDK use checked against its official documentation (source-driven-development), including open question 5 of the spec.
