# CLAUDE.md — FHRPY project guide

> Working notes for Claude Code. Keep this file current as the project evolves.
> **All code, comments, identifiers, docs and commit messages are in English.**
> (Issue replies to the human may be in French.)

## What this project is

**FHRPY** is a Python port of the MATLAB **FHRMA** toolbox (Fetal Heart Rate
Morphological Analysis), restricted to *our own* methods plus a clean, PHP-free,
Python-controllable **web CTG viewer**.

Scope we port (and ONLY this):
- **Baseline**: our **WMFB** method (Weighted Median Filter Bank) + morphological
  analysis: accelerations, decelerations, contractions (TOCO).
- **False-signal detection** (`fhrma-fs`): Doppler MHR/FHR confusion detection,
  including the training code.
- File I/O for `.fhr` / `.rcf` / `.rcfm` formats + our datasets and examples.

We DO NOT port other authors' baseline methods (Wrobel, Lu, Cazares, Houze,
Jimenez, Taylor, Ayres, Maeda, Mantel, Mongelli, Pardey). Shared preprocessing
utilities are ported as needed.

License: **MIT**. Repo: https://github.com/data-coeur/FHRPY

## Source material (read-only references, NOT part of the repo)
- MATLAB toolbox: `/home/sam/Desktop/fhr-demo/matlab/src/FHRMA/`
- Web viewer (PHP + JS): `/home/sam/Desktop/fhr-demo/web/src/` (real readable JS
  is in `web/src/old/js/*-source.js`)
- Analysis notes (this session): `scratchpad/viewer_analysis.md`,
  `scratchpad/matlab_analysis.md`

## Repository layout (target)
```
fhrpy/                 Python package
  io/                  .fhr/.rcf/.rcfm readers & writers, datasets loaders
  preprocess/          filtering, interpolation, resampling (NumPy)
  baseline/            WMFB baseline + accel/decel/contraction detection
  falsesignal/         fhrma-fs feature extraction + model + inference
  training/            FS model training scripts (kept, not for inference path)
  viewer/              Python wrapper around the web viewer (notebook/UI/server)
    web/               vanilla-JS ES module viewer + CSS + assets (no PHP/jQuery)
tests/                 pytest unit tests (+ MATLAB/Octave parity tests)
examples/              datasets + example notebooks
docs/                  documentation, demos
docker/                optional GPU/Octave docker-compose (NOT required by main)
```

## The 6 development steps (tracked as GitHub issues, milestone-style)
- **Étape 0** — project config: this CLAUDE.md, `.claude/settings.json`, repo, issues. ✅
- **Étape 1** — the web viewer (open/save `.rcf`/`.rcfm` + marker file; colored
  zones toggle for accel/decel/contraction; toggle FHR/MHR with linear interp of
  gaps; configurable signals-per-graph; 1cm/min & 3cm/min; works in local Python
  UI, in Jupyter (VSCode + Colab), and as standalone HTML; Python-controllable
  object with event listeners; dynamic height; responsive).
- **Étape 2** — false-signal detection (`fhrma-fs`) wired into the viewer.
- **Étape 3** — WMFB baseline + morpho, wired into the viewer.
- **Étape 4** — complete README (citation requirements like FHRMA; demo space;
  "we are recruiting for the **AIM-CTG** project" — details pending from human).
- **Étape 5** — MLOps real-time inference server (CPU 2-4 cores; 12 records of
  ~3h each processed in ~1 min; FS + baseline). Investigate fast MLP ops, avoid
  pytorch/tf cold-start; numpy CPU; optional Rust multi-core for hot loops.

## Hard requirements / constraints (from the human)
- **Everything in English** except issue replies.
- **Numerical parity with MATLAB**: signal-processing functions must produce
  the *same* output as MATLAB. Verify with an **Octave docker**; if needed, hand
  the human MATLAB snippets to run (heavy — a MATLAB license/docker is a fallback).
- Viewer must: open/save `.rcf` and `.rcfm` (= `.fhr`, 8 bytes/sample default)
  with a companion marker file; be a controllable Python object (set markers,
  scroll, etc.) exposing event listeners (scroll, every button, marker change);
  dynamic height; stay responsive; configurable number of signals per graph;
  1cm/min or 3cm/min; colored accel/decel/contraction zones (toggle); FHR/MHR
  toggle with linear interpolation of missing points.
- Viewer deployment targets: (1) local Python program with a UI, (2) Jupyter
  notebook rendering inline under **VSCode** and **Colab** (Colab may also spawn
  a web server for a new window), (3) standalone HTML pages bundling viewer+data,
  opening locally **without PHP**.
- Keep the FS training code.
- **Étape 5 forward-looking**: design inference so an MLP/feature pipeline runs
  fast on CPU (cold-start matters); numpy CPU first, optional Rust (multi-core).
- Unit tests with CI; CI status badge on GitHub.

## Git / GitHub workflow
- Develop on **`dev`**; **push every message/loop**.
- **`main` must become public** and is only updated on an explicit *release*
  instruction from the human (release must be validated by the human).
- ⚠️ Current blocker: the provided fine-grained PAT can push to `dev` but
  **cannot change repo visibility or create issues without proper scopes** —
  see `scratchpad/` / open question for the human. Repo is currently PRIVATE.
- Credentials: token stored in `~/.git-credentials` (gitignored, never commit).
- Commit message trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## Autonomous loop
- Runs every ~10 min. Each iteration: pull latest, check GitHub issues (new /
  updated), fix them, write tests, comment on the issue (with screenshots when
  possible, via Playwright), push to `dev`. Re-verify previous work is complete.
- Explain to the human how to access what was built, and what the human can do
  to help (test, answer questions, grant access).

## Machine / safety limits (this dev box)
- Do **little compute** here. Cap GPU at **150 W** (thermals). Watch fan/temps.
- No single computation longer than **2-3 min**.
- Heavy/GPU/large-RAM work must go in **docker-compose** to avoid OOM crashes.
- Root via SSH available: `home.samuelboudet.com`, user `sam` (sudo) — use sparingly.

## Tooling notes
- `node`/`npm` NOT installed here → viewer JS must be hand-written vanilla ES
  modules (no build step required) OR add a build step only if node is installed.
- `docker compose` plugin not present (only `docker`); `docker-compose` v1 may
  need install for Octave parity.
- Playwright MCP available for browser testing/screenshots.

## Key facts about the data format (verify against matlab_analysis.md)
- `.fhr`/`.rcfm`: ~4 Hz sampling; PHP math implied 32 bytes/sec on disk.
  Channels include FHR (FHR1/FHR2), TOCO (contractions), MHR, markers.
  Confirm exact byte layout from `fhropen.m`/`fhrsave.m` before coding I/O.
