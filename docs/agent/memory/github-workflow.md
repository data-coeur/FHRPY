---
name: github-workflow
description: "FHRPY git workflow — develop on dev, push every loop, main only on release"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

Develop on branch **`dev`** and **push every message/loop**. The **`main`**
branch must be **public** and is updated **only when the human explicitly says
"release"** (each release must be validated by the human).

**Why:** the human reviews before anything reaches the public main branch.

**How to apply:** never push to `main` unprompted; keep committing small,
described commits to `dev` each loop with the Claude co-author trailer.
Maintain GitHub issues per step and comment on the relevant issue after each
step (with Playwright screenshots when possible), explaining how to access the
result and what the human can do to help. See [[fhrpy-project]], [[repo-access]].
