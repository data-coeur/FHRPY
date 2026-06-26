---
name: self-check-loops
description: "Each FHRPY loop, re-verify all prior requests and tests are actually done"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

The autonomous loop runs ~every 10 min. Each iteration must **re-check that all
of the human's requests from recent interactions have been addressed, and that
all feasible tests were run** — not just move forward. Also scan for new/updated
GitHub issues, fix them, test, and comment on the issue (with screenshots via
Playwright when possible).

**Why:** the human works asynchronously (testing, filing issues) and wants
nothing dropped.

**How to apply:** at the start of each loop, pull, list open issues + recent
human messages, diff against what's done; finish gaps before new work. Keep
issue #8 (human action items) updated. See [[fhrpy-project]], [[github-workflow]].
