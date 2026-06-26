---
name: human-comment-prefix
description: "The human comments on GitHub issues from the same account, prefixed \"SB:\""
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

The human (Samuel Boudet) posts GitHub issue comments from the **same account**
my `gh` CLI is authed as (`samuelboudetfmm`), so filtering by author does NOT
distinguish his comments from mine. He prefixes his comments with **`SB:`**.

**Why:** I previously missed his feedback by filtering out the `samuelboudetfmm`
author entirely.

**How to apply:** each loop, scan ALL issue comments (don't exclude
`samuelboudetfmm`); treat any comment starting with `SB:` (or any comment that
isn't one of my own progress reports) as human feedback to address as a priority.
List comments by `createdAt` to spot the newest. See [[self-check-loops]],
[[github-workflow]].
