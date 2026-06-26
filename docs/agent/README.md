# Agent development notes

FHRPY is developed by an autonomous coding agent (Claude Code) under human
direction. This folder documents *how* that works, for transparency and so the
process is reproducible.

## The development loop

The agent runs on a recurring ~10-minute loop. Each iteration:

1. Pull the repo, review any background work, run the test suite.
2. Scan the GitHub issues for **new human feedback** (the human prefixes their
   comments with **`SB:`**), and address it as the top priority.
3. Continue the roadmap (the six "Étapes", tracked as issues #1–#8).
4. Commit small, described commits and **push to the `dev` branch every loop**.
   `main` is public and is updated **only on an explicit human-validated
   release** — never automatically.
5. Comment on the relevant issue with what was done (screenshots via Playwright
   when useful) and re-verify that all prior requests are complete.

The loop is self-rescheduling so it persists for hours, and stops on request.

## Memory

The agent keeps a small file-based memory (one fact per file). Snapshots of those
notes live in [`memory/`](memory/):

| Note | About |
|------|-------|
| [fhrpy-project](memory/fhrpy-project.md) | project overview, goals, roadmap |
| [github-workflow](memory/github-workflow.md) | dev-branch / release workflow |
| [english-only](memory/english-only.md) | all artifacts in English |
| [matlab-parity](memory/matlab-parity.md) | numerical parity with MATLAB (Octave) |
| [ci-badge-tests](memory/ci-badge-tests.md) | tests + CI badge |
| [self-check-loops](memory/self-check-loops.md) | re-verify every loop |
| [machine-limits](memory/machine-limits.md) | **dev-machine-specific** limits (not project constraints) |
| [aim-ctg-recruiting](memory/aim-ctg-recruiting.md) | AIM-CTG recruiting reminder |
| [repo-access](memory/repo-access.md) | repo/PAT scope notes |

> ⚠️ **`machine-limits` is specific to the development machine** (an RTX 2080 Ti
> capped at 150 W, thermal/OOM limits). These are operational constraints of that
> box — they are **not** requirements of the FHRPY toolbox.
