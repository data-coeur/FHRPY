---
name: ci-badge-tests
description: FHRPY needs unit tests with a CI status badge on GitHub
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

Write **unit tests** (pytest) and wire **CI** so a **status badge** shows on
GitHub (the human asked for "the logo on GitHub" = the CI badge in the README).

**Why:** visible proof the toolbox is tested; standard for a public toolbox.

**How to apply:** add a GitHub Actions workflow running pytest + a badge in
README. NOTE: pushing `.github/workflows/` needs the PAT `workflow` scope, which
it currently lacks (see [[repo-access]]) — coordinate with the human. Pair tests
with MATLAB parity checks ([[matlab-parity]]). See [[fhrpy-project]].
