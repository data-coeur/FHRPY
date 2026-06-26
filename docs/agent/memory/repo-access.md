---
name: repo-access
description: FHRPY repo credentials and PAT scope limitations
metadata: 
  node_type: memory
  type: reference
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

Repo: https://github.com/data-coeur/FHRPY (org `data-coeur`). `gh` is authed as
`samuelboudetfmm` but cannot create/admin data-coeur repos. A **fine-grained PAT**
(provided in the brief) is scoped to this repo: it **can** push to `dev` and
create/edit issues, but **cannot** (403): change repo **visibility** (needs
Administration scope) or push **`.github/workflows/`** files (needs `workflow`
scope). Token is stored persistently in `~/.git-credentials` (gitignored).

`.github/workflows/` is temporarily gitignored until the PAT gets `workflow`
scope. Repo is PRIVATE until the human flips it or grants Administration scope —
tracked in issue #8. See [[github-workflow]].
