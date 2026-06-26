---
name: fhrpy-project
description: "FHRPY project overview, goals, deadline, and the 6-step roadmap"
metadata: 
  node_type: memory
  type: project
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

**FHRPY** = Python port of the MATLAB **FHRMA** toolbox, restricted to *our own*
methods + a clean PHP-free web CTG viewer. Repo: https://github.com/data-coeur/FHRPY
(currently PRIVATE — see [[repo-access]]). Source material lives at
`/home/sam/Desktop/fhr-demo/` (matlab/ and web/); dev notes in repo
`docs/dev-notes/{viewer,matlab}_analysis.md`.

Scope: WMFB baseline + morphology (accel/decel/contraction), false-signal
detection (`fhrma-fs`) + its training code, `.fhr/.rcf/.rcfm` I/O + datasets,
and a web viewer. Do NOT port other authors' baselines (Wrobel, Lu, etc.).

**Deadline: human presents the AIM-CTG project on 2026-06-27 (the day after the
brief) — the viewer (Étape 1) must work by then.** End goal: pip-installable.

Roadmap (GitHub issues #1–#8): 0=config #1, 1=viewer #2, 2=false-signal #3,
3=WMFB baseline #4, 4=README/AIM-CTG #5, 5=MLOps inference server #6,
brief/constraints #7, human action items #8. See [[github-workflow]],
[[matlab-parity]], [[machine-limits]], [[aim-ctg-recruiting]].
